"""The bot must come back with a transcript.

It didn't. The bot joined, recorded, reached `done` — and no notes ever arrived, with no
error anywhere to say why. The cause was the transcription provider: `meeting_captions`
reads the MEETING PLATFORM's closed captions, so it only produces anything when the host
has captions switched on. With them off it yields nothing, silently, for ever. Recall's
own documentation names this as the usual reason a bot produces no transcript.

So two guarantees, and they are the fix:

  1. A new bot is created with Recall's OWN speech-to-text, which needs no third-party key
     and nothing switched on in someone else's Zoom account.
  2. A recording that already finished WITHOUT a transcript is asked to be transcribed now,
     rather than being polled to death and written off. The audio still exists; that is what
     rescues every call already lost this way.
"""
import json

import pytest


@pytest.fixture()
def provider(monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_RECALL_API_KEY", "test-key")
    monkeypatch.delenv("CHORDENTIAL_RECALL_TRANSCRIPT_PROVIDER", raising=False)
    monkeypatch.delenv("CHORDENTIAL_RECALL_LANGUAGE", raising=False)
    from chordential_oia.meetings.recall import RecallCaptureProvider
    return RecallCaptureProvider()


def _capture_calls(provider, monkeypatch, get_result=None):
    """Record every POST/GET the provider makes, without touching the network."""
    posts, gets = [], []

    def fake_post(path, payload):
        posts.append((path, payload))
        return {"id": "bot-1"}

    def fake_get(path):
        gets.append(path)
        return get_result if get_result is not None else {}

    monkeypatch.setattr(provider, "_post", fake_post)
    monkeypatch.setattr(provider, "_get", fake_get)
    return posts, gets


def test_a_new_bot_does_not_depend_on_the_host_enabling_captions(provider, monkeypatch):
    """The regression itself. meeting_captions transcribes only if the HOST turned
    captions on — a setting we neither control nor can see."""
    posts, _ = _capture_calls(provider, monkeypatch)
    provider.invite(join_url="https://zoom.example/j/1", meeting_ref="7")

    assert len(posts) == 1
    path, payload = posts[0]
    assert path == "/bot/"
    chosen = payload["recording_config"]["transcript"]["provider"]
    assert "meeting_captions" not in chosen, (
        "the platform-captions provider fails silently when the host has captions off — "
        "it must not be the default")
    assert "recallai_streaming" in chosen, chosen
    # and it is configured, not an empty object that falls back to a default we didn't pick
    assert chosen["recallai_streaming"]["language_code"] == "auto"
    assert chosen["recallai_streaming"]["mode"] == "prioritize_accuracy"


def test_the_payload_is_json_serialisable_and_asks_for_speaker_separation(provider, monkeypatch):
    posts, _ = _capture_calls(provider, monkeypatch)
    provider.invite(join_url="https://zoom.example/j/1", meeting_ref="7")
    payload = posts[0][1]
    json.dumps(payload)          # a body Recall cannot parse is the same as no bot
    assert payload["recording_config"]["transcript"]["diarization"][
        "use_separate_streams_when_available"] is True


def test_an_explicit_provider_is_still_honoured_with_its_own_option_shape(monkeypatch):
    """The env override stays — but each provider takes a DIFFERENT options object, so an
    unknown one gets an empty object rather than options invented for it."""
    monkeypatch.setenv("CHORDENTIAL_RECALL_API_KEY", "k")
    monkeypatch.setenv("CHORDENTIAL_RECALL_TRANSCRIPT_PROVIDER", "meeting_captions")
    from chordential_oia.meetings.recall import RecallCaptureProvider
    p = RecallCaptureProvider()
    posts, _ = _capture_calls(p, monkeypatch)
    p.invite(join_url="https://zoom.example/j/1", meeting_ref="7")
    chosen = posts[0][1]["recording_config"]["transcript"]["provider"]
    assert chosen == {"meeting_captions": {}}


def test_a_finished_recording_with_no_transcript_is_asked_to_be_transcribed(provider, monkeypatch):
    """The rescue. This is the shape of every call already lost: done, recorded, and
    carrying no transcript artifact at all."""
    done_bot_no_transcript = {
        "id": "bot-1",
        "status_changes": [{"code": "done"}],
        "recordings": [{"id": "rec-9", "media_shortcuts": {}}],
    }
    posts, _gets = _capture_calls(provider, monkeypatch, get_result=done_bot_no_transcript)

    out = provider.fetch_transcript("bot-1")
    assert out is None, "nothing to return yet — it was only just requested"
    assert posts, "a finished recording with no transcript must be sent for transcription"
    path, payload = posts[0]
    assert path == "/recording/rec-9/create_transcript/"
    assert payload == {"provider": {"recallai_async": {"language_code": "auto"}}}


def test_a_recording_that_already_has_a_transcript_is_downloaded_not_re_requested(
        provider, monkeypatch):
    bot = {
        "id": "bot-1",
        "status_changes": [{"code": "done"}],
        "recordings": [{"id": "rec-9", "media_shortcuts": {
            "transcript": {"data": {"download_url": "https://signed.example/t.json"}}}}],
    }
    posts, _ = _capture_calls(provider, monkeypatch, get_result=bot)
    monkeypatch.setattr(provider, "_download", lambda url: [
        {"speaker": "Dana", "words": [{"text": "Budget", "start_timestamp": 1.0},
                                      {"text": "is $40k", "end_timestamp": 2.0}]}])

    t = provider.fetch_transcript("bot-1")
    assert t is not None and "Budget" in t.text
    assert not posts, "it already had a transcript — asking for another would be wrong"


def test_a_bot_still_recording_is_left_alone(provider, monkeypatch):
    posts, _ = _capture_calls(provider, monkeypatch,
                              get_result={"id": "bot-1", "status_changes": [
                                  {"code": "in_call_recording"}]})
    assert provider.fetch_transcript("bot-1") is None
    assert not posts, "a call still in progress must not be sent for transcription"


def test_a_refused_transcript_request_is_not_an_exception(provider, monkeypatch):
    """Recall refuses a second request for a recording that already has one. That is a
    normal answer on a backoff, not a crash in the poll loop."""
    def boom(path, payload):
        raise RuntimeError("Recall HTTP 400: transcript already exists")
    monkeypatch.setattr(provider, "_post", boom)
    monkeypatch.setattr(provider, "_get", lambda path: {
        "id": "bot-1", "status_changes": [{"code": "done"}],
        "recordings": [{"id": "rec-9", "media_shortcuts": {}}]})
    assert provider.fetch_transcript("bot-1") is None      # reported, never raised


def test_the_recording_id_is_found_across_recalls_shapes():
    from chordential_oia.meetings.recall import _recording_id
    assert _recording_id({"recordings": [{"id": "r1"}]}) == "r1"
    assert _recording_id({"recording": {"id": "r2"}}) == "r2"
    assert _recording_id({"recording": "r3"}) == "r3"
    assert _recording_id({"recordings": []}) == ""
    assert _recording_id(None) == ""
