"""The bot must come back with a transcript.

It didn't: the bot joined, recorded, reached `done`, and no notes arrived. Recall's own
logs named the cause on 2026-08-13 —

    Zoom failed to enable captions for meeting, transcript will not be available

— because the default provider, `meeting_captions`, does not transcribe audio. It reads
Zoom's caption stream, and Zoom will not let a bot that is not the host turn captions on.

So two guarantees:

  1. The bot is created with a provider that transcribes AUDIO, so a transcript never
     depends on a setting in someone else's meeting.
  2. A recording that finished WITHOUT a transcript is asked to be transcribed now, rather
     than being polled to death and written off — which recovers the calls already
     recorded under the old default.
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


def test_the_bot_transcribes_audio_rather_than_reading_zooms_captions(provider, monkeypatch):
    """The whole bug, in one assertion.

    ``meeting_captions`` reads Zoom's caption stream instead of transcribing audio, and Zoom
    refuses to enable captions for a bot that is not the host — so the bot attended every
    call and produced nothing. Recall's log, verbatim: "Zoom failed to enable captions for
    meeting, transcript will not be available"."""
    posts, _ = _capture_calls(provider, monkeypatch)
    provider.invite(join_url="https://zoom.example/j/1", meeting_ref="7")

    assert len(posts) == 1
    path, payload = posts[0]
    assert path == "/bot/"
    assert payload == {
        "meeting_url": "https://zoom.example/j/1",
        "bot_name": "Chordential Notetaker",
        "recording_config": {"transcript": {"provider": {
            "recallai_streaming": {"mode": "prioritize_accuracy", "language_code": "auto"}}}},
    }
    json.dumps(payload)          # a body Recall cannot parse is the same as no bot


def test_the_captions_provider_is_never_the_default(provider, monkeypatch):
    """A regression here is silent — the bot still joins, still records, still finishes.
    Nothing but this test would catch it going back."""
    posts, _ = _capture_calls(provider, monkeypatch)
    provider.invite(join_url="https://zoom.example/j/1", meeting_ref="7")
    assert "meeting_captions" not in posts[0][1]["recording_config"]["transcript"]["provider"]


def test_the_captions_provider_is_still_available_to_anyone_who_wants_it(monkeypatch):
    """It is a bad default, not a bad option: with the bot made a co-host, or captions on,
    it works and costs less. The env var still selects it, with its own (empty) options."""
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
