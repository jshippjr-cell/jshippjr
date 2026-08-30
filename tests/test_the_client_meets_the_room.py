"""The client's half of the room, as a client actually meets it.

    "remove the requirement to input their name and email in order to make a comment.
     Also when they click to make a comment it needs to stop the playback, so they don't
     lose their placement. also nothing tells the client that they can scrub and highlight
     a range… the client needs the ability to move the comment marker to the exact spot…
     the button labelled 'request changes' should be next to the approval button… the
     client was confused by the wording 'request changes' they thought submitting notes
     was the same thing… we need to incorporate a quick platform tutorial"
                                                    — the operator, 2026-08-28

Seven reports, one theme: the room was built by people who already knew how it worked.
Every one of them is a place where a control was correct and unlearnable.

The expensive one is the wording. Leaving a note and "requesting changes" read as the
same act, and they are not remotely: notes are the conversation about this take and cost
nothing, while that button sends the composer away to write a NEW VERSION and spends one
of a finite number of rounds. A buyer who confuses the two either says nothing (afraid of
spending a round) or spends rounds saying things a note would have carried.
"""
import importlib
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("fastapi")


@pytest.fixture()
def room(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "r.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "passphrase")
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    for m in ("db", "campaigns", "uploads", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod, db
    from chordential_oia.web.opportunity_ops import agreement_doc_for
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    with TestClient(app_mod.app):
        pass
    jon = TestClient(app_mod.app)
    jon.cookies.set(ADMIN_COOKIE, admin_cookie_value("passphrase"))

    past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    conn = db.connect()
    opp_id = None
    for r in conn.execute("SELECT id FROM opportunities ORDER BY id").fetchall():
        if not db.list_meetings(conn, r["id"]):
            db.create_meeting(conn, opp_id=r["id"], start_at=past, status="ingested")
        conn.execute("UPDATE meetings SET start_at=?, status='ingested' WHERE opp_id=?",
                     (past, r["id"]))
        conn.commit()
        *_rest, doc, _d = agreement_doc_for(conn, r["id"])
        if getattr(getattr(doc, "agreement", None), "price_low", None):
            opp_id = r["id"]
            break
    if opp_id is None:
        pytest.skip("no signable demo deal")
    # The buyer of record — the person this room's link is sent to.
    conn.execute("UPDATE opportunities SET contact_name=?, contact_email=? WHERE id=?",
                 ("Marisa del Rio", "marisa@pikerowan.com", opp_id))
    conn.commit()
    token = db.ensure_share_token(conn, opp_id)
    conn.close()

    client = TestClient(app_mod.app)
    client.post(f"/workspace/{token}/sign",
                data={"typed_name": "Marisa del Rio",
                      "signer_email": "marisa@pikerowan.com", "consent": "1"},
                follow_redirects=False)
    jon.post(f"/opportunity/{opp_id}/countersign",
             data={"typed_name": "Jon Shipp", "consent": "1"}, follow_redirects=False)
    conn = db.connect()
    pid = db.project_for_opp(conn, opp_id)["id"]
    db.update_delivery(conn, pid, "versions",
                       [{"n": 1, "label": "v1 Concept", "url": "/x.mp3",
                         "filename": "x.mp3", "name": "x",
                         "created_at": "2026-08-01T00:00:00"}])
    db.update_delivery(conn, pid, "state", "In review")
    conn.close()
    return jon, client, app_mod, db, pid, token


def _page(client, pid, token):
    return client.get(f"/room/{pid}?k={token}").text


# ── 1. nobody is asked who they are ─────────────────────────────────────────────────
def test_the_client_is_not_interrogated_before_they_can_speak(room):
    """Two required boxes stood in front of the one thing the room is for.

    It was never a real question: this link went to a named contact on a signed deal, and
    `opportunities.contact_email` is who it went to — evidence we hold (ADR-0050), not a
    guess. So it is used and the boxes come down.
    """
    _jon, client, _app, _db, pid, token = room
    page = _page(client, pid, token)
    assert 'placeholder="Your name" required' not in page, "it still demands a name"
    assert 'placeholder="you@agency.com" required' not in page
    assert 'class="nb-name-in" value="Marisa del Rio"' in page, (
        "the buyer of record was not carried into the note bar")


def test_a_note_records_without_the_client_typing_an_identity(room):
    """The point of the prefill: the note must actually LAND. The route requires a real
    name+email, so an empty pair posts 303 and records nothing — which is how this was
    broken before, one layer up."""
    _jon, client, _app, db, pid, token = room
    client.post(f"/project/{pid}/review/comment",
                data={"k": token, "origin": "room", "version": "1", "t": "12",
                      "body": "the brass is fighting the VO",
                      "author": "Marisa del Rio", "email": "marisa@pikerowan.com"})
    conn = db.connect()
    try:
        notes = [n for n in db.list_review_comments(conn, pid) if n["kind"] == "comment"]
    finally:
        conn.close()
    assert notes, "the note did not record"
    assert notes[-1]["author"] == "Marisa del Rio"
    assert notes[-1]["author_role"] == "client", "the side that spoke was not recorded"


def test_a_colleague_on_a_forwarded_link_can_still_correct_it(room):
    """Prefilled is not the same as fixed. The share link is forwardable, so the name has
    to stay correctable — otherwise every note from the agency's producer is signed by
    whoever the account contact happens to be."""
    _jon, client, _app, _db, pid, token = room
    page = _page(client, pid, token)
    assert "nb-notyou" in page and "Marisa del Rio?" in page


# ── 2. the transport holds still while you write ────────────────────────────────────
def test_clicking_into_the_note_box_stops_the_music(room):
    """It kept playing while you typed, so the moment you were writing about slid away
    underneath you — and the mark went with it."""
    _jon, client, _app, _db, pid, token = room
    page = _page(client, pid, token)
    assert 'body.addEventListener("focus"' in page, "focus does not pause"
    assert "function pause(){" in page, (
        "no pause primitive — `toggle()` would START a parked transport")


# ── 3. the marks explain themselves ─────────────────────────────────────────────────
def test_the_room_says_how_to_mark_a_passage_and_move_a_mark(room):
    """Both existed and nothing said so, which is the same as neither existing."""
    _jon, client, _app, _db, pid, token = room
    page = _page(client, pid, token)
    assert "nb-hint" in page
    assert "drag its pin" in page, "nothing says a mark can be moved"
    assert "waveform" in page and "Range" in page, "nothing says a passage can be marked"


# ── 4. the mark can be put where it belongs ─────────────────────────────────────────
def _note(client, db, pid, token, t="12", t_end=""):
    client.post(f"/project/{pid}/review/comment",
                data={"k": token, "origin": "room", "version": "1", "t": t,
                      "t_end": t_end, "body": "here", "author": "Marisa del Rio",
                      "email": "marisa@pikerowan.com"})
    conn = db.connect()
    try:
        return [n for n in db.list_review_comments(conn, pid) if n["kind"] == "comment"][-1]
    finally:
        conn.close()


def test_the_client_can_move_their_own_mark(room):
    """A note is a claim about a MOMENT, and the moment used to be wherever the playhead
    was when Send was pressed — never the thing itself."""
    _jon, client, _app, db, pid, token = room
    n = _note(client, db, pid, token, t="12")
    r = client.post(f"/project/{pid}/review/note/{n['id']}/move",
                    data={"t": "7.5", "k": token})
    assert r.status_code == 200, f"the move was refused ({r.status_code})"
    conn = db.connect()
    try:
        assert abs(db.get_review_comment(conn, n["id"])["t_seconds"] - 7.5) < 0.01
    finally:
        conn.close()


def test_the_move_door_is_not_behind_the_admin_login(room):
    """The exemption list has drifted from the routes before — resolve and asset were
    added without it and bounced every client to the operator's login, which answers
    200 with a login page and looks exactly like success."""
    from chordential_oia.web import publicpaths
    assert publicpaths._REVIEW_NOTE_MOVE_RE.match("/project/7/review/note/3/move")
    assert not publicpaths._REVIEW_NOTE_MOVE_RE.match("/project/7/review/note/3/species"), (
        "the operator's classification door was exempted too")


def test_a_range_moves_whole(room):
    """A passage is ONE claim. Shifting one end of it would be a different claim."""
    _jon, client, _app, db, pid, token = room
    n = _note(client, db, pid, token, t="20", t_end="28")
    client.post(f"/project/{pid}/review/note/{n['id']}/move",
                data={"t": "30", "t_end": "38", "k": token})
    conn = db.connect()
    try:
        moved = db.get_review_comment(conn, n["id"])
    finally:
        conn.close()
    assert (moved["t_seconds"], moved["t_end"]) == (30.0, 38.0), "the span did not survive"


def test_nobody_moves_a_mark_their_side_did_not_write(room):
    """Moving someone else's mark changes what they said. The client's note is their
    evidence about their own picture; the studio nudging it is the same species of edit
    as rewriting the words."""
    jon, client, _app, db, pid, token = room
    n = _note(client, db, pid, token, t="12")
    r = jon.post(f"/project/{pid}/review/note/{n['id']}/move", data={"t": "3"})
    assert r.status_code == 403, f"the studio moved the buyer's mark ({r.status_code})"
    conn = db.connect()
    try:
        assert abs(db.get_review_comment(conn, n["id"])["t_seconds"] - 12.0) < 0.01
    finally:
        conn.close()


def test_a_reply_has_no_mark_to_move(room):
    """It hangs off its parent and carries no timecode, so there is nothing to move."""
    _jon, client, _app, db, pid, token = room
    n = _note(client, db, pid, token, t="12")
    conn = db.connect()
    try:
        rid = db.add_review_comment(conn, pid, body="agreed", author="Marisa del Rio",
                                    email="marisa@pikerowan.com", parent_id=n["id"],
                                    author_role="client")
        assert db.move_review_comment(conn, pid, rid, 5.0) is False
    finally:
        conn.close()


# ── 5. the two verdicts, and what they are called ───────────────────────────────────
def test_the_ask_stands_beside_approve_and_says_what_it_costs(room):
    """The client read leaving notes and "request changes" as the same act — a fair
    reading of those words, and an expensive mistake."""
    _jon, client, _app, _db, pid, token = room
    page = _page(client, pid, token)
    assert "Ask for a new version" in page, "the button still hides what it does"
    assert "Request changes" not in page, "the confusing wording survives somewhere"
    assert "v-ask-open" in page, "the ask is not weighted beside Approve"
    # …and it explains itself in the one place it matters
    assert "not the same as leaving a note" in page


def test_the_ask_box_only_appears_once_you_have_asked(room):
    """An open text field next to Approve reads like somewhere to leave a note, which is
    the exact confusion being fixed."""
    _jon, client, _app, _db, pid, token = room
    page = _page(client, pid, token)
    assert 'class="v-no" hidden' in page, "the change box is open before it is chosen"
    assert "v-ask-cancel" in page, "no way back out of it"


def test_the_explainer_names_the_button_that_exists(room):
    """"What approving commits" still said "Request changes spends one" — an explainer
    pointing at a button nobody can find is worse than none."""
    _jon, client, _app, _db, pid, token = room
    page = _page(client, pid, token)
    assert "What approving commits" in page
    assert "Ask for a new version</b> spends one" in page


# ── 6. the tour ─────────────────────────────────────────────────────────────────────
def test_the_client_gets_a_tour_and_can_reopen_it(room):
    _jon, client, _app, _db, pid, token = room
    page = _page(client, pid, token)
    assert 'id="sr-tour"' in page, "no tour"
    assert 'id="tour-open"' in page, "a tour you cannot re-open is one you must remember"
    # it teaches the thing that was actually misread
    assert "Notes are free" in page
    assert "spends one of your rounds" in page


def test_the_tour_is_the_clients_alone(room):
    """A composer and the studio live here. Explaining the play button to them is the
    mistake the monitoring banner made (ADR-0070a)."""
    jon, _client, app_mod, db, pid, _token = room
    from fastapi.testclient import TestClient
    assert 'id="sr-tour"' not in jon.get(f"/room/{pid}").text, "the studio got the tour"
    conn = db.connect()
    try:
        tid = conn.execute("INSERT INTO talent (name, email, created_at) VALUES (?,?,?)",
                           ("Maya Okafor", "maya@roster.com", "2026-08-28")).lastrowid
        conn.execute("INSERT INTO assignments (project_id, talent_id, role, created_at) "
                     "VALUES (?,?,?,?)", (pid, tid, "Composer", "2026-08-28"))
        conn.commit()
        ptok = db.ensure_talent_portal_token(conn, tid)
    finally:
        conn.close()
    creator = TestClient(app_mod.app).get(f"/creator/{ptok}")
    assert creator.status_code == 200
    assert 'id="sr-tour"' not in creator.text, "the composer got the client's tour"
