"""Six live reports from one session, and the loop they were all standing on.

    "There should be a way for us to delete a note in 'the room'… the client also has the
     ability to request a new version multiple times without the composer response and it
     spends their rounds… lets put a gate between versions… also the ask for the client
     name and email is still there."
    "the client's notes dont show up on the composer's side of the room"
    "composer's arent going to jot down things in this platform.. remove it"
    "uploading a different version and the button is stuck at uploading even though the
     upload went through"
                                                    — the operator, 2026-08-30

The one that matters most is the third. A client left notes, the composer's room showed
nothing, and both sides were behaving exactly as designed: ADR-0069 says an unpriced note
is not work, so the composer's copy subtracts it — and the only prompt to price anything
lived on the delivery console, which is not where the operator works. Nobody was told
anything. The client looked ignored, the composer looked idle, and the notes sat one
classification away from being visible.
"""
import importlib
import re
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("fastapi")


@pytest.fixture()
def stage(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "s.db"))
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
    # THE REPORTED SHAPE: a deal carrying no contact at all. The first fix read
    # `contact_email` and answered nothing here, which is why the boxes came back.
    conn.execute("UPDATE opportunities SET contact_name='', contact_email='' WHERE id=?",
                 (opp_id,))
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
    tid = conn.execute("INSERT INTO talent (name, email, created_at) VALUES (?,?,?)",
                       ("Maya Okafor", "maya@roster.com", "2026-08-30")).lastrowid
    conn.execute("INSERT INTO assignments (project_id, talent_id, role, created_at) "
                 "VALUES (?,?,?,?)", (pid, tid, "Composer", "2026-08-30"))
    conn.commit()
    ptok = db.ensure_talent_portal_token(conn, tid)
    conn.close()
    return jon, client, app_mod, db, pid, token, ptok


def _note(client, db, pid, token, body="brass too loud", t="12"):
    client.post(f"/project/{pid}/review/comment",
                data={"k": token, "origin": "room", "version": "1", "t": t, "body": body})
    conn = db.connect()
    try:
        return [n for n in db.list_review_comments(conn, pid) if n["kind"] == "comment"][-1]
    finally:
        conn.close()


# ── 1. the ask is gone, on the deal that still had it ───────────────────────────────
def test_the_identity_chain_reaches_the_signature(stage):
    """The first fix read `opportunities.contact_*` and stopped. A deal entered without a
    contact still had nothing, so the boxes came back — reported a second time. The chain
    now ends at the SIGNATURE and then the organisation."""
    _jon, client, _app, _db, pid, token, _ptok = stage
    page = client.get(f"/room/{pid}?k={token}").text
    assert 'placeholder="Your name" required' not in page, "it still demands a name"
    assert 'class="nb-name-in" value="Marisa del Rio"' in page, (
        "the signer — the only person on file — was not found")


def test_our_own_countersignature_is_never_the_buyer(stage):
    """Caught in the walkthrough, and it would have been ugly: the first version took the
    NEWEST signature on the deal, which is Jon's countersignature, and prefilled the
    client's note bar with the operator's own name — about to be signed to their words."""
    from chordential_oia.web.project_routes import _deal_identity
    _jon, _client, _app, db, pid, _token, _ptok = stage
    conn = db.connect()
    try:
        name, _mail = _deal_identity(conn, pid)
    finally:
        conn.close()
    assert name == "Marisa del Rio"
    assert "operator" not in name.lower() and "passphrase" not in name.lower()


def test_a_note_lands_with_nothing_typed(stage):
    """The point of the whole chain: the note must RECORD. An empty pair used to post 303
    and write nothing, silently, on a page whose only purpose is saying something."""
    _jon, client, _app, db, pid, token, _ptok = stage
    n = _note(client, db, pid, token)
    assert n["author"] == "Marisa del Rio"
    assert n["author_role"] == "client"


# ── 2. a note can be changed or taken back ──────────────────────────────────────────
def test_the_author_can_edit_and_delete_their_own_note(stage):
    _jon, client, _app, db, pid, token, _ptok = stage
    n = _note(client, db, pid, token)
    r = client.post(f"/project/{pid}/review/note/{n['id']}/edit",
                    data={"k": token, "body": "the brass is too loud at the turn"})
    assert r.status_code == 200
    conn = db.connect()
    try:
        assert db.get_review_comment(conn, n["id"])["body"] == \
            "the brass is too loud at the turn"
    finally:
        conn.close()
    d = client.post(f"/project/{pid}/review/note/{n['id']}/delete", data={"k": token})
    assert d.status_code == 200
    conn = db.connect()
    try:
        assert db.get_review_comment(conn, n["id"]) is None
    finally:
        conn.close()


def test_nobody_edits_the_other_sides_words(stage):
    """Rewriting someone else's note is a worse edit than moving their mark."""
    jon, client, _app, db, pid, token, _ptok = stage
    n = _note(client, db, pid, token)
    assert jon.post(f"/project/{pid}/review/note/{n['id']}/edit",
                    data={"body": "nope"}).status_code == 403
    assert jon.post(f"/project/{pid}/review/note/{n['id']}/delete").status_code == 403


def test_a_note_that_spent_a_round_cannot_be_deleted(stage):
    """The one refusal, and it protects the CLIENT: delete it and the counter still reads
    a round spent with nothing on the page saying what it was for. That is a bill with the
    line items torn out."""
    _jon, client, _app, db, pid, token, _ptok = stage
    client.post(f"/project/{pid}/review/changes",
                data={"k": token, "origin": "room", "body": "try it warmer"},
                follow_redirects=False)
    conn = db.connect()
    try:
        cr = [n for n in db.list_review_comments(conn, pid)
              if n["kind"] == "change_request"][-1]
    finally:
        conn.close()
    r = client.post(f"/project/{pid}/review/note/{cr['id']}/delete", data={"k": token})
    assert r.status_code == 409
    assert "revision round" in r.json()["why"]
    # …and the wording can still be fixed, which is the whole distinction.
    assert client.post(f"/project/{pid}/review/note/{cr['id']}/edit",
                       data={"k": token, "body": "warmer, and shorter"}
                       ).status_code == 200


def test_deleting_a_note_takes_its_replies_with_it(stage):
    """A reply is an answer. Left behind when its question is gone it reads as a remark
    about the take, which nobody wrote."""
    _jon, client, _app, db, pid, token, _ptok = stage
    n = _note(client, db, pid, token)
    conn = db.connect()
    try:
        rid = db.add_review_comment(conn, pid, body="on it", author="Studio",
                                    email="s@c.com", parent_id=n["id"],
                                    author_role="operator")
    finally:
        conn.close()
    client.post(f"/project/{pid}/review/note/{n['id']}/delete", data={"k": token})
    conn = db.connect()
    try:
        assert db.get_review_comment(conn, rid) is None
    finally:
        conn.close()


# ── 3. one round per version ────────────────────────────────────────────────────────
def test_a_second_ask_before_the_first_is_written_spends_nothing(stage):
    """A round buys A VERSION. Asking twice before the first has been written buys one
    and charges for two — the client paying for our latency."""
    _jon, client, _app, db, pid, token, _ptok = stage
    client.post(f"/project/{pid}/review/changes",
                data={"k": token, "origin": "room", "body": "warmer"},
                follow_redirects=False)
    conn = db.connect()
    try:
        after_one = int(db.get_delivery(conn, pid).get("revisions_used") or 0)
    finally:
        conn.close()
    assert after_one == 1
    r = client.post(f"/project/{pid}/review/changes",
                    data={"k": token, "origin": "room", "body": "and shorter"},
                    follow_redirects=False)
    conn = db.connect()
    try:
        after_two = int(db.get_delivery(conn, pid).get("revisions_used") or 0)
    finally:
        conn.close()
    assert after_two == 1, "the second ask spent a round the client did not get a version for"
    assert "already-asked" in (r.headers.get("location") or "")


def test_the_room_stops_offering_it_and_says_why(stage):
    """Refused server-side AND not offered, because a control you can see and cannot
    press teaches nothing. Notes stay open — that is the point of saying so."""
    _jon, client, _app, _db, pid, token, _ptok = stage
    client.post(f"/project/{pid}/review/changes",
                data={"k": token, "origin": "room", "body": "warmer"},
                follow_redirects=False)
    page = client.get(f"/room/{pid}?k={token}").text
    assert "already writing your next version" in page
    # the BUTTON, not the stylesheet rule that names its class
    assert 'class="v-btn v-ask-open"' not in page, (
        "the ask is still offered while we owe them a version")
    assert "nb-body" in page, "notes were closed too — they are free and they still count"


def test_the_studios_own_change_request_is_never_gated(stage):
    """The studio asking for a change is direction, not a revision — it never charged a
    round, so it is never gated by one."""
    jon, _client, _app, db, pid, _token, _ptok = stage
    for body in ("darker", "and slower"):
        assert jon.post(f"/project/{pid}/review/changes", data={"body": body},
                        follow_redirects=False).status_code == 303
    conn = db.connect()
    try:
        assert int(db.get_delivery(conn, pid).get("revisions_used") or 0) == 0
    finally:
        conn.close()


# ── 4. the notes reach the composer, or somebody is told why not ────────────────────
def _island(page):
    m = re.search(r'class="sr-notes-data">\s*(\[.*?\])\s*</script>', page, re.S)
    import json
    return json.loads(m.group(1)) if m else None


def test_an_unpriced_note_is_not_silence(stage):
    """The report. ADR-0069 holds — the composer still cannot read or act on an unpriced
    note — but "cannot act on" had been built as "does not exist", so their room said the
    client had left nothing at all."""
    from fastapi.testclient import TestClient
    _jon, client, app_mod, db, pid, token, ptok = stage
    _note(client, db, pid, token)
    composer = TestClient(app_mod.app).get(f"/creator/{ptok}").text
    assert _island(composer) == [], "ADR-0069 was reversed; unpriced work reached them"
    assert "with the studio being reviewed" in composer, (
        "the composer was shown silence and concluded the client said nothing")
    assert "brass too loud" not in composer, "the words leaked before they were priced"


def test_the_studio_prices_notes_in_the_room(stage):
    """The prompt lived only on the delivery console, which is not where the operator
    works: *"you keep referencing the delivery console, but im testing things in the
    room."*"""
    _jon, client, _app, db, pid, token, _ptok = stage
    jon = stage[0]
    _note(client, db, pid, token)
    room_page = jon.get(f"/room/{pid}").text
    assert "waiting on you" in room_page
    assert "brass too loud" in room_page, "the studio cannot read what it is pricing"
    assert re.search(r'/project/\d+/note/\d+/disposition', room_page), "no way to price it"


def test_pricing_one_hands_it_to_the_composer(stage):
    from fastapi.testclient import TestClient
    jon, client, app_mod, db, pid, token, ptok = stage
    n = _note(client, db, pid, token)
    jon.post(f"/project/{pid}/note/{n['id']}/disposition",
             data={"how": "revision", "return_to": f"/room/{pid}"},
             follow_redirects=False)
    composer = TestClient(app_mod.app).get(f"/creator/{ptok}").text
    assert len(_island(composer)) == 1
    assert "brass too loud" in composer


def test_the_queue_names_the_notes_nobody_priced(stage):
    """So the operator finds out without opening a page they do not use."""
    _jon, client, _app, db, pid, token, _ptok = stage
    jon = stage[0]
    _note(client, db, pid, token)
    q = jon.get("/queue").text
    assert "client note" in q and "Price" in q
    assert "the composer cannot see them" in q.lower()


# ── 5. the capture shelf is gone (see tests/test_range_notes.py for the store) ───────
def test_no_capture_shelf_anywhere_in_the_room(stage):
    from fastapi.testclient import TestClient
    jon, client, app_mod, _db, pid, token, ptok = stage
    for page in (jon.get(f"/room/{pid}").text,
                 client.get(f"/room/{pid}?k={token}").text,
                 TestClient(app_mod.app).get(f"/creator/{ptok}").text):
        assert "Hum a motif at 2am" not in page
        assert 'class="shelf"' not in page


# ── 6. the upload button says what is happening ─────────────────────────────────────
def test_the_upload_button_stops_saying_uploading_once_it_has_uploaded(stage):
    """*"the button is stuck at uploading even though the upload went through"* — it was
    not stuck. `progress` measures BYTES SENT, so it hits 100% when the last byte leaves
    and everything after is the server writing the master. The button said "Uploading…"
    through all of it, over a full bar, which is the picture of a hang."""
    from fastapi.testclient import TestClient
    _jon, _client, app_mod, _db, _pid, _token, ptok = stage
    page = TestClient(app_mod.app).get(f"/creator/{ptok}").text
    assert 'btn.textContent = "Saving…"' in page, "the label still lies after the send"
    assert 'xhr.timeout' in page, "it could still sit forever"
    assert 'var was = btn.textContent' in page, (
        "the original label is hard-coded back, which relabels the other form on failure")
    assert 'btn.textContent = "Submit for review"' not in page


# ── 7. an alert is a shortcut, or it is noise ───────────────────────────────────────
def test_every_alert_carries_the_door_it_is_about(stage):
    """*"all it does is tell me something happened but nothing is clickable to take me
    to the area where the new thing took place… the concept behind this is for you to
    alert me and give me a clickable shortcut to the thing that needs my attention"*
    (operator, 2026-08-30).

    The URL was never missing — the phone push has always carried one and opens it. The
    outbox discarded it at the record, so the dashboard could name a thing and not reach
    it. Nothing new is computed; a value that already existed is kept.
    """
    import time
    from chordential_oia.web import delivery_ops
    jon, _client, _app, db, pid, _token, _ptok = stage
    delivery_ops._notify_operator_review(pid, None, "Film music · new note",
                                         "marisa commented: too low")
    time.sleep(0.5)
    conn = db.connect()
    try:
        alerts = db.recent_alerts(conn, 5)
    finally:
        conn.close()
    assert alerts and alerts[0]["url"], "the alert has nowhere to go"
    page = jon.get("/dashboard").text
    assert f'href="/room/{pid}#p{pid}"' in page, "the row is not a link"


def test_the_alert_points_at_the_room_not_the_console(stage):
    """A shortcut to the wrong page is a second navigation. Every operator alert pointed
    at the delivery console, which is not where this operator works — said twice — and
    the room now carries the listening, the notes, the pricing and the checklist."""
    from chordential_oia.web import delivery_ops
    assert delivery_ops._operator_room_url(7) == "/room/7#p7"


# ── 8. the queue is decisions, not housekeeping ─────────────────────────────────────
def test_a_proposed_fact_is_not_a_decision_waiting_on_you(stage):
    """*"This list is ridiculous, i dont need proposed facts to confirm to show up on my
    to do"* — twenty-two of them, from one campaign, each naming the same campaign and
    differing only by a dotted key. That is the extractor working correctly, and it
    buried five real supply-side blocks under itself.

    A CONFLICT stays: the machine read something a human-owned value disagrees with, and
    ADR-0013 forbids it overwriting them silently, so a person must choose.
    """
    from chordential_oia.web import queue as queue_mod
    _jon, _client, _app, db, pid, _token, _ptok = stage
    conn = db.connect()
    try:
        ci = conn.execute("SELECT id, opp_id FROM campaign_intelligence LIMIT 1").fetchone()
        if ci is None:
            pytest.skip("no campaign intelligence in the demo set")
        for status, key in (("needs_review", "music_budget"), ("conflicted", "deadline")):
            conn.execute(
                "INSERT INTO campaign_intelligence_field (ci_id, facet, key, status, "
                "updated_at) VALUES (?,?,?,?,?)",
                (ci["id"], "engagement", key, status, "2026-08-30T00:00:00"))
        conn.commit()
        cards = queue_mod.compute_queue(conn, db)
    finally:
        conn.close()
    titles = [c["title"] for c in cards]
    assert not [t for t in titles if "Proposed fact" in t], (
        "proposed facts are back on the to-do list")
    assert [t for t in titles if "Conflict to resolve" in t], (
        "the conflict went with them — that one IS a decision")


def test_a_round_after_the_master_is_locked_is_a_real_one(stage):
    """The gate is for the ask nobody has answered — not for every second ask.

    A client can approve a master and come back wanting something else. That is a REAL
    second round on the same take, stamped `after_lock` so a scope conversation has a
    record to stand on (ADR-0019), and nothing is owed at that moment: the previous ask
    was answered and approved. Gating it would have made approval the end of the
    conversation. Learned the hard way — the first gate blocked it and a production-spine
    test caught it.
    """
    _jon, client, _app, db, pid, token, _ptok = stage
    jon = stage[0]
    client.post(f"/project/{pid}/review/changes",
                data={"k": token, "origin": "room", "body": "warmer"},
                follow_redirects=False)
    jon.post(f"/project/{pid}/creative-lock", data={"action": "set"})
    conn = db.connect()
    try:
        db.update_delivery(conn, pid, "state", "In review")   # they are listening again
        was = int(db.get_delivery(conn, pid).get("revisions_used") or 0)
    finally:
        conn.close()
    client.post(f"/project/{pid}/review/changes",
                data={"k": token, "origin": "room", "body": "actually, new melody?"},
                follow_redirects=False)
    conn = db.connect()
    try:
        assert int(db.get_delivery(conn, pid).get("revisions_used") or 0) == was + 1, (
            "a genuine post-lock round was refused as a double-spend")
    finally:
        conn.close()


# ── 9. four more from the walkthrough (2026-08-30, second pass) ─────────────────────
def test_switching_takes_keeps_the_music_playing(stage):
    """*"When the client clicks back to version one, presses play, and then clicks back to
    version two, the music does not play back."*

    Assigning `audio.src` stops the element dead and nothing restarted it — so A/B-ing one
    take against another, which is the entire reason both chips are on the bar, went
    silent on the second press. The resume waits for `loadedmetadata` because `dur` still
    holds the PREVIOUS take's length until then, and the sync guard reads a playhead past
    a stale `dur` as "off the end of this take" and pauses.
    """
    _jon, client, _app, _db, pid, token, _ptok = stage
    page = client.get(f"/room/{pid}?k={token}").text
    fn = page[page.index("function loadTake(chip){"):]
    fn = fn[:fn.index("function decodePeaks")]
    assert "var wasPlaying" in fn, "nothing remembers that it was playing"
    assert "loadedmetadata" in fn, (
        "it resumes before the new take reports its duration, so the stale one pauses it")
    assert "audio.play()" in fn


def test_the_client_is_never_offered_the_boxes_again(stage):
    """The "Not <name>?" affordance re-opened the two fields the whole change existed to
    remove — the ask, one click further away."""
    _jon, client, _app, _db, pid, token, _ptok = stage
    page = client.get(f"/room/{pid}?k={token}").text
    assert "nb-notyou" not in page and "notYou" not in page
    assert 'placeholder="Your name" required' not in page


def test_the_producer_card_names_someone(stage):
    """*"under producer, it says your producer at chordential"* — the shape of a name with
    no name in it, on the one card the client is meant to write to. It read an environment
    variable nothing sets in production; it now falls through to the instance's OWNER
    account (ADR-0054 — evidence, not one more variable) and then to the studio itself.
    "Chordential" is not a placeholder: it is who the buyer contracted with."""
    from chordential_oia.web import kickoff
    _jon, _client, _app, db, pid, _token, _ptok = stage
    conn = db.connect()
    try:
        conn.execute("INSERT INTO user_account (email, name, password_hash, role, "
                     "created_at) VALUES (?,?,?,?,?)",
                     ("jon@chordential.com", "Jon Shipp", "x", "owner", "2026-08-30"))
        conn.commit()
        ready = kickoff.readiness_for_project(conn, db, pid, discover=False)
    finally:
        conn.close()
    assert ready["team"][0]["name"] == "Jon Shipp"
    assert ready["summary"]["producer"] == "Jon Shipp"


def test_the_producer_falls_back_to_the_studio_not_a_placeholder(stage):
    from chordential_oia.web import kickoff
    _jon, _client, _app, db, pid, _token, _ptok = stage
    conn = db.connect()
    try:
        ready = kickoff.readiness_for_project(conn, db, pid, discover=False)
    finally:
        conn.close()
    assert ready["team"][0]["name"] == "Chordential"
    assert "Your producer" not in ready["team"][0]["name"]


def test_the_sheet_closer_is_a_button_not_a_key_that_does_nothing(stage):
    """It always CLOSED the sheet on click; the word on it named a key that does not,
    because Escape was deliberately unbound for sheets (a layer dismissed by three
    different gestures felt like it fell shut on its own). The label was the lie."""
    _jon, client, _app, _db, pid, token, _ptok = stage
    page = client.get(f"/room/{pid}?k={token}").text
    assert ">ESC<" not in page, "it still promises a key that does nothing"
    assert 'class="esc sr-close" aria-label="Close">✕' in page
