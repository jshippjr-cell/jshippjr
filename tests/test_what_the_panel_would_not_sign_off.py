"""Four things the review panel refused to pass, and what each of them costs.

After the room was built, six reviewers walked it (executive team, software engineer,
composer, audio engineer, agency EP, editor). Four findings survived triage:

1. **The audio engineer, on sync.** The take followed the picture with one remedy — past
   0.12s, slam ``audio.currentTime``. Three frames is not a lock when the job is judging
   a hit, and a hard seek mid-phrase *clicks*: the correction announces itself louder
   than the error. Worse, it ran on ``timeupdate`` (~4×/sec), so most drift was never
   measured at all. Correct in the frame loop, trim the rate for anything small, seek
   only for a real dropout — and put the number on screen.

2. **The audio engineer, on monitoring.** Nothing in the room said what its playback IS.
   A person can approve a mix on laptop speakers at whatever level the browser is at,
   believing they judged it. The honesty rule applies to our own surfaces first.

3. **The editor, on cuts.** A take is written against ONE picture. Play v2 (scored to
   cut 1) against cut 2 and every hit lands late — and the room looked entirely normal,
   so the composer reads the drift as their own mistake.

4. **The executive team, on the roster.** The client's room named the freelancers: the
   presence roster ("Ada · talent"), every note author, every event in the live feed.
   Their explicit condition on putting this page in front of a real client. The roster
   IS the business, and it walks out of the door with the name.

(4) is the one that can cost an account rather than a round, so it is tested hardest —
and at the SERVER, because ADR-0068's rule is that a role's copy is built by never
putting the thing in it.
"""
import pathlib
import re

import pytest

from chordential_oia.web import room as R

ROOM = (pathlib.Path(__file__).resolve().parent.parent / "src" / "chordential_oia"
        / "web" / "templates" / "creator_portal.html")


@pytest.fixture(scope="module")
def markup() -> str:
    return ROOM.read_text(encoding="utf-8")


def _sync(markup: str) -> str:
    start = markup.index("function syncAudio(")
    body = markup[start:markup.index("function paintSync()", start)]
    return "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("//"))


# ── 1. sync ─────────────────────────────────────────────────────────────────────────
def test_sync_is_measured_every_frame_not_four_times_a_second(markup):
    loop = markup[markup.index("function loop()"):]
    loop = loop[:loop.index("requestAnimationFrame(loop)")]
    assert "syncAudio()" in loop, (
        "correction is back on timeupdate only — a quarter-second of drift goes "
        "unmeasured between samples")


def test_small_drift_is_trimmed_not_seeked(markup):
    body = _sync(markup)
    assert "setRate(" in body, (
        "the only remedy is still a hard seek, which clicks mid-phrase")
    trim = re.search(r"\bTRIM = (0\.\d+)", markup)
    assert trim and float(trim.group(1)) <= 0.01, (
        "the rate trim is over ±1%; an audible pitch shift is worse than the drift")


def test_the_correction_is_not_applied_every_frame(markup):
    """The regression this shape exists to prevent, reported live: *"the audio playback
    is clipping, it sounds like the audio is chopped in milliseconds"*. Both remedies
    were running at 60Hz — a hard `currentTime =` restarts the decoder and every
    `playbackRate` write rebuilds the time-stretcher. Measuring wants the frame; acting
    does not."""
    body = _sync(markup)
    assert "ACT_MS" in body and "lastAct" in body, (
        "corrections are unthrottled again; at 60Hz the remedy is the artefact")
    assert "SEEK_MS" in body and "lastSeek" in body, (
        "a hard seek has no floor between attempts, so an unrecoverable gap becomes "
        "a click track")
    assert "audio.seeking" in body, (
        "a correction can be issued while a seek is still in flight")


def test_the_trim_does_not_engage_a_time_stretcher(markup):
    """A ±0.5% resample is inaudible as pitch and free to engage. WSOLA is neither."""
    assert "preservesPitch" in markup, (
        "the rate trim time-stretches, which chops on exactly the material this room "
        "is for")


def test_the_trim_has_a_deadband(markup):
    """One rate write per correction episode. A controller that recomputes a fresh
    target from a buffer-quantised clock chatters across its own threshold."""
    body = _sync(markup)
    assert "SYNC_OK" in body and "SYNC_TRIM" in body, (
        "engage and release share one threshold; the trim will chatter on it")
    assert "trimming" in body, "no held state, so the trim is recomputed every pass"


def test_a_hard_seek_is_reserved_for_a_real_dropout(markup):
    body = _sync(markup)
    assert "SYNC_SEEK" in body and "audio.currentTime = t" in body, (
        "no seek path at all — a stalled stream would never recover")
    threshold = re.search(r"SYNC_SEEK = (0\.\d+)", markup)
    assert threshold, "the seek threshold is not declared"
    assert float(threshold.group(1)) >= 0.1, (
        "seeking below ~100ms puts the click back: that is the window a rate trim owns")


def test_the_room_says_how_far_out_it_is(markup):
    assert "sr-sync" in markup, "no sync readout"
    assert re.search(r'syncEl\.textContent = "sync "', markup), (
        "the readout does not report the measured drift")


# ── 2. monitoring honesty ───────────────────────────────────────────────────────────
#
# AMENDED 2026-08-28 (ADR-0070a), on the operator's question — *"why is this
# necessary?"* — of the standing banner. The FINDING stands; the shape was wrong.
#
# It sat above the work, permanently, for every role: the client, the studio, and the
# mixer whose profession it was explaining. A banner that is always on screen is
# furniture by the fortieth visit, which means it would have been invisible at the one
# moment it exists for — and it was the first thing a buyer read in a room they had just
# paid to enter. So it moved to the two presses that actually assert the mix is right.
#
# These tests now hold the harder line: the words must be there, AND they must be at the
# decision, AND they must not be back above the room.
def _notes(markup):
    return re.findall(r'class="monitor-note"[^>]*>(.*?)</p>', markup, re.S)


def test_the_room_states_what_its_playback_is_good_for(markup):
    notes = _notes(markup)
    assert notes, "no monitoring-honesty note anywhere in the room"
    for raw in notes:
        note = re.sub(r"\s+", " ", raw).lower()
        for claim in ("level", "low end", "stereo width"):
            assert claim in note, f"a note does not say {claim!r} cannot be judged here"
        assert "timing" in note, (
            "the note only says what playback is bad for; it must also say what it IS "
            "good for, or it reads as an apology for the room")


def test_the_note_is_at_the_sign_off_and_not_standing_over_the_room():
    """Where it is, is the whole amendment.

    Both presses that assert the music is right carry it — the master approval and the
    deliverable sign-off, which are the mixes — and neither is reachable by a role that
    cannot make that call, because both blocks are already gated on `client_verdict` and
    `sign_off_asset`. Nothing carries it outside those blocks.
    """
    markup = ROOM.read_text()
    approve = markup.index('action="/project/{{ a.project_id }}/review/approve"')
    signoff = markup.index("Sign off your deliverables")
    at = [m.start() for m in re.finditer(r'class="monitor-note"', markup)]
    assert len(at) == 2, f"expected the note at both sign-offs, found {len(at)}"
    # one inside the master verdict block, one at the deliverables heading
    assert any(approve < i < approve + 2500 for i in at), (
        "the master approval does not carry it")
    assert any(signoff < i < signoff + 2500 for i in at), (
        "the deliverable sign-off does not carry it")
    # …and it is not back above the room, where it was furniture
    assert '<div class="monitor-note"' not in markup, (
        "the standing banner is back — a note nobody reads is not honesty")


# ── 3. a take is bound to the cut it was written against ────────────────────────────
def test_a_submission_records_the_cut_it_was_written_against():
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "chordential_oia"
           / "web" / "uploads.py").read_text(encoding="utf-8")
    body = src[src.index("def _store_pending_submission"):]
    body = body[:body.index("\nasync def ")]
    assert '"cut"' in body, (
        "a take lands with no record of which picture it was scored to")


def test_publishing_carries_the_cut_into_the_ladder():
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "chordential_oia"
           / "web" / "project_routes.py").read_text(encoding="utf-8")
    body = src[src.index("def _publish_pending_submission"):]
    body = body[:body.index("@router.post", body.index("versions.append"))]
    assert re.search(r'"cut": pv\.get\("cut"\)', body), (
        "the cut is dropped at publish, so the long-lived record cannot answer "
        "'was this ever scored to this picture?'")


def test_the_chip_names_the_cut(markup):
    assert 'data-cut="{{ v.cut' in markup, "take chips carry no cut"
    assert "cut {{ v.cut }}" in markup, "the chip does not READ 'v2 · cut 2'"


def test_playing_a_take_against_another_cut_says_so(markup):
    assert "sr-conform-warn" in markup, "no out-of-conform band"
    fn = markup[markup.index("function paintConform("):]
    fn = fn[:fn.index("function loadTake(")]
    assert "takeCut === pictureCut" in fn, (
        "the band is not driven by comparing the take's cut to the picture's")
    load = markup[markup.index("function loadTake(chip){"):]
    assert "paintConform(chip)" in load[:load.index("audio.src = src")], (
        "the band is not repainted when the take changes, so switching chips leaves "
        "the previous take's verdict on screen")


# ── 4. the roster is not the client's ───────────────────────────────────────────────
def test_a_client_cannot_see_who():
    assert not R.can(R.CLIENT, "see_who")
    assert R.can(R.OPERATOR, "see_who")
    assert R.can(R.TALENT, "see_who")


def test_a_talent_note_reaches_the_client_signed_by_the_studio():
    assert R.attribute(R.CLIENT, "talent", "Ada Cheng") == R.STUDIO_VOICE
    assert R.attribute(R.OPERATOR, "talent", "Ada Cheng") == "Ada Cheng"


def test_the_clients_own_words_stay_theirs():
    """Stripping the client's own side would make their conversation unreadable —
    and they already know who their people are."""
    assert R.attribute(R.CLIENT, "client", "Marta Ruiz") == "Marta Ruiz"


def test_an_unattributed_row_is_treated_as_ours():
    """Fail closed. A row with no recorded side is far more likely to be a system
    event than the buyer speaking, and guessing wrong the other way costs a name."""
    assert R.attribute(R.CLIENT, "", "Ada Cheng") == R.STUDIO_VOICE
    assert R.attribute(R.CLIENT, None, "Ada Cheng") == R.STUDIO_VOICE


def test_the_subtraction_happens_in_room_view_not_the_template():
    """ADR-0068: content a role may not see is ABSENT from the dict. A template that
    forgets an `{% if %}` must leak nothing."""
    built = {
        "versions": [{"n": 1, "label": "v1", "from_creator": "Ada Cheng"}],
        "feedback": {"notes": [
            {"id": 1, "author": "Ada Cheng", "author_role": "talent", "body": "low brass",
             "replies": [{"author": "Studio", "author_role": "operator", "body": "noted",
                          "internal": False}]},
            {"id": 2, "author": "Marta Ruiz", "author_role": "client", "body": "love it",
             "replies": []},
        ]},
        "pending": {"url": "/uploads/x.mp3"}, "contributors": [{"name": "Ada"}],
        "captures": [], "deliverables": [],
    }
    view = R.room_view(None, None, 7, R.CLIENT, build=lambda *a: built)
    authors = [n["author"] for n in view["feedback"]["notes"]]
    assert authors == [R.STUDIO_VOICE, "Marta Ruiz"], authors
    assert view["feedback"]["notes"][0]["replies"][0]["author"] == R.STUDIO_VOICE
    assert view["versions"][0]["from_creator"] == "", (
        "the Takes sheet still names the composer on every published version")


def test_the_operators_room_is_untouched():
    built = {
        "versions": [{"n": 1, "label": "v1", "from_creator": "Ada Cheng"}],
        "feedback": {"notes": [{"id": 1, "author": "Ada Cheng", "author_role": "talent",
                                "body": "low brass", "replies": []}]},
        "pending": None, "contributors": [], "captures": [], "deliverables": [],
    }
    view = R.room_view(None, None, 7, R.OPERATOR, build=lambda *a: built)
    assert view["feedback"]["notes"][0]["author"] == "Ada Cheng"
    assert view["versions"][0]["from_creator"] == "Ada Cheng"


def test_the_live_feed_and_the_presence_roster_obey_the_same_rule():
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "chordential_oia"
           / "web" / "project_routes.py").read_text(encoding="utf-8")
    poll = src[src.index("def session_room_poll"):]
    poll = poll[:poll.index("@router.post")]
    assert "room.attribute(role" in poll, (
        "the event feed still names the actor to whoever is listening")
    assert 'room.can(role, "see_who")' in poll, (
        "the presence roster is not gated; a client watches the freelancers arrive "
        "and leave by name")
    assert "STUDIO_VOICE" in poll, (
        "our side of the room must collapse to ONE participant, not vanish — a client "
        "should still see that the studio is here")


def test_a_note_records_which_side_of_the_room_it_came_from():
    """The subtraction cannot subtract what was never recorded. Every arm of the note
    route already knew the answer and threw it away."""
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "chordential_oia"
           / "web" / "project_routes.py").read_text(encoding="utf-8")
    body = src[src.index("def review_comment("):]
    body = body[:body.index("_PRESENCE_TTL")]
    assert 'who_role = "talent"' in body and 'who_role = "operator"' in body, (
        "a creator's or the studio's note is still recorded as the client's")
    assert "author_role=who_role" in body, "the comment row does not carry the side"
    assert "actor_role=who_role" in body, (
        "the event still hardcodes actor_role='client', so the live feed mis-attributes "
        "every note in the room")
