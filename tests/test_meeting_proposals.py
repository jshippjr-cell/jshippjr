"""Meeting Proposals — the operator offers up to three Eastern times; the client's pick
books through the ONE engine and the other options expire (ADR-0016/0017).

Covers: the propose→preview→send→pick lifecycle, the first-pick-wins lock, Eastern-time
display (never UTC in anything client-facing), the direct-book mode, and the CI timeline
event the booking writes.
"""
import importlib
import json

import pytest

from chordential_oia.models import BuyerType, MusicRequirement, Opportunity

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402
# ADR-0044: reached where they live. `app.py` is the application object now and
# imports none of these; using it as a namespace for the package is what kept 55
# dead imports alive in it.
from chordential_oia.web import meeting_scheduler  # noqa: E402


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "web.db"))
    monkeypatch.setenv("CHORDENTIAL_CAMPAIGN_WORKSPACE", "1")
    for m in ("db", "campaign_intelligence", "campaign_intake", "intake_lanes",
              "campaigns", "meeting_scheduler", "meetings_service", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from chordential_oia.web import app as app_mod
    return app_mod


def _opp(dbm, conn, email="sarah@halcyon.com"):
    oid = dbm.insert_opportunity(conn, Opportunity(
        client="Halcyon Creative", need="Holiday anthem", description="Campaign.",
        buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
        budget_min=0, budget_max=0))
    if email:
        conn.execute("UPDATE opportunities SET contact_email=?, contact_name=? WHERE id=?",
                     (email, "Sarah Chen", oid))
        conn.commit()
    return oid


def _propose(c, opp_id, **extra):
    data = {"mode": "propose", "meeting_type": "zoom",
            "date": "2026-07-14", "time": "10:00",
            "date2": "2026-07-15", "time2": "14:00",
            "date3": "2026-07-16", "time3": "11:30",
            "duration_min": "30", "client_name": "Sarah Chen",
            "client_email": "sarah@halcyon.com"}
    data.update(extra)
    return c.post(f"/opportunity/{opp_id}/schedule", data=data, follow_redirects=False)


# --------------------------------------------------------------------------- #
# Eastern time — clients never see UTC.
# --------------------------------------------------------------------------- #
def test_fmt_et_renders_eastern_with_honest_label(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    ms = meeting_scheduler
    # July → EDT; 14:00 UTC == 10:00 AM EDT
    assert ms.fmt_et("2026-07-14T14:00:00+00:00", long=True) == "Tuesday · July 14 · 10:00 AM EDT"
    # January → EST; 15:00 UTC == 10:00 AM EST
    assert ms.fmt_et("2026-01-13T15:00:00+00:00", long=True) == "Tuesday · January 13 · 10:00 AM EST"


def test_et_to_utc_round_trips(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    ms = meeting_scheduler
    iso = ms.et_to_utc_iso("2026-07-14", "10:00")
    assert iso.startswith("2026-07-14T14:00:00")          # EDT = UTC-4
    assert ms.fmt_et(iso, long=True).endswith("10:00 AM EDT")


# --------------------------------------------------------------------------- #
# Propose → preview → send.
# --------------------------------------------------------------------------- #
def test_propose_creates_draft_and_preview_shows_eastern_options(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn); conn.close()
    with TestClient(app_mod.app) as c:
        r = _propose(c, opp_id)
        assert r.status_code == 303 and "/proposal/" in r.headers["location"]
        page = c.get(r.headers["location"])
        assert page.status_code == 200
        # the machine proposes, the operator disposes — nothing sent yet
        conn = app_mod.db.connect()
        prop = app_mod.db.list_meeting_proposals(conn, opp_id)[0]
        conn.close()
        assert prop["status"] == "draft"
        assert len(json.loads(prop["slots_json"])) == 3
        # options render Eastern, never UTC (the email body is checked in the send test;
        # page chrome contains a UTC-conversion script comment, so scope to the times)
        assert "10:00 AM EDT" in page.text and "2:00 PM EDT" in page.text
        assert "AM UTC" not in page.text and "PM UTC" not in page.text
        assert "Send to the client" in page.text


def test_send_marks_sent_and_emails_the_options(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn); conn.close()
    sent = []
    monkeypatch.setattr(meeting_scheduler.mailer, "send_email",
                        lambda to, sub, body, html=None, ics=None: sent.append((to, sub, body)))
    with TestClient(app_mod.app) as c:
        loc = _propose(c, opp_id).headers["location"]
        pid = int(loc.rstrip("/").split("/")[-1])
        r = c.post(f"/opportunity/{opp_id}/proposal/{pid}/send", follow_redirects=False)
        assert r.status_code == 303
    conn = app_mod.db.connect()
    prop = app_mod.db.get_meeting_proposal(conn, pid); conn.close()
    assert prop["status"] == "sent"
    assert sent and sent[0][0] == "sarah@halcyon.com"
    body = sent[0][2]
    assert "Option 1" in body and "Option 3" in body
    assert "10:00 AM EDT" in body and "UTC" not in body
    assert f"/meet/{prop['token']}" in body               # the pick links


# --------------------------------------------------------------------------- #
# The client picks — first pick wins, everything books, timeline records it.
# --------------------------------------------------------------------------- #
def test_client_pick_books_expires_others_and_records_timeline(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn); conn.close()
    monkeypatch.setattr(meeting_scheduler.mailer, "send_email",
                        lambda *a, **k: None)
    with TestClient(app_mod.app) as c:
        loc = _propose(c, opp_id).headers["location"]
        pid = int(loc.rstrip("/").split("/")[-1])
        c.post(f"/opportunity/{opp_id}/proposal/{pid}/send")
        conn = app_mod.db.connect()
        token = app_mod.db.get_meeting_proposal(conn, pid)["token"]; conn.close()
        # GET never books (email scanners prefetch links)
        page = c.get(f"/meet/{token}?pick=1")
        assert page.status_code == 200 and "Confirm this time" in page.text
        conn = app_mod.db.connect()
        assert app_mod.db.get_meeting_proposal(conn, pid)["status"] == "sent"; conn.close()
        # the POST books option 2 (index 1) = Wed 2:00 PM EDT
        r = c.post(f"/meet/{token}/pick", data={"pick": "1"}, follow_redirects=False)
        assert r.status_code == 303
        done = c.get(f"/meet/{token}")
        assert "booked" in done.text.lower()
        assert "2:00 PM EDT" in done.text
    conn = app_mod.db.connect()
    prop = app_mod.db.get_meeting_proposal(conn, pid)
    assert prop["status"] == "booked" and prop["meeting_id"]
    meeting = app_mod.db.get_meeting(conn, prop["meeting_id"])
    assert meeting["start_at"].startswith("2026-07-15T18:00:00")   # 2 PM EDT in UTC
    assert meeting["initiated_by"] == "client_pick"
    # the Opportunity timeline recorded the meeting (ADR-0017)
    ci = app_mod.db.ci_for_opportunity(conn, opp_id)
    events = conn.execute(
        "SELECT * FROM campaign_intelligence_event WHERE ci_id=? AND verb='meeting_scheduled'",
        (ci["id"],)).fetchall()
    conn.close()
    assert events and "EDT" in events[0]["to_value"]


def test_first_pick_wins_second_pick_sees_booked_page(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn); conn.close()
    monkeypatch.setattr(meeting_scheduler.mailer, "send_email",
                        lambda *a, **k: None)
    with TestClient(app_mod.app) as c:
        loc = _propose(c, opp_id).headers["location"]
        pid = int(loc.rstrip("/").split("/")[-1])
        c.post(f"/opportunity/{opp_id}/proposal/{pid}/send")
        conn = app_mod.db.connect()
        token = app_mod.db.get_meeting_proposal(conn, pid)["token"]; conn.close()
        c.post(f"/meet/{token}/pick", data={"pick": "0"})
        c.post(f"/meet/{token}/pick", data={"pick": "2"})   # too late — no second meeting
    conn = app_mod.db.connect()
    prop = app_mod.db.get_meeting_proposal(conn, pid)
    meetings = app_mod.db.list_meetings(conn, opp_id=opp_id)
    conn.close()
    assert prop["status"] == "booked"
    assert len(meetings) == 1
    assert meetings[0]["start_at"].startswith("2026-07-14T14:00:00")  # option 1 held


def test_withdraw_expires_the_client_link(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn); conn.close()
    with TestClient(app_mod.app) as c:
        loc = _propose(c, opp_id).headers["location"]
        pid = int(loc.rstrip("/").split("/")[-1])
        c.post(f"/opportunity/{opp_id}/proposal/{pid}/cancel")
        conn = app_mod.db.connect()
        token = app_mod.db.get_meeting_proposal(conn, pid)["token"]; conn.close()
        page = c.get(f"/meet/{token}")
        assert "expired" in page.text.lower()
        r = c.post(f"/meet/{token}/pick", data={"pick": "0"})
        conn = app_mod.db.connect()
        assert app_mod.db.get_meeting_proposal(conn, pid)["status"] == "canceled"
        assert not app_mod.db.list_meetings(conn, opp_id=opp_id); conn.close()


# --------------------------------------------------------------------------- #
# Direct mode + the manual path.
# --------------------------------------------------------------------------- #
def test_direct_mode_books_immediately_in_eastern(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn); conn.close()
    monkeypatch.setattr(meeting_scheduler.mailer, "send_email",
                        lambda *a, **k: None)
    with TestClient(app_mod.app) as c:
        r = _propose(c, opp_id, mode="direct", date2="", time2="", date3="", time3="")
        assert r.status_code == 303 and r.headers["location"].endswith("#discovery")
    conn = app_mod.db.connect()
    meetings = app_mod.db.list_meetings(conn, opp_id=opp_id); conn.close()
    assert len(meetings) == 1
    assert meetings[0]["start_at"].startswith("2026-07-14T14:00:00")  # 10 AM EDT → UTC


def test_create_discovery_call_button_always_present(tmp_path, monkeypatch):
    """The manual path exists from ANY opportunity — even one that already met once."""
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn)
    app_mod.db.create_meeting(conn, opp_id=opp_id, start_at="2026-07-01T14:00:00+00:00")
    conn.close()
    with TestClient(app_mod.app) as c:
        page = c.get(f"/opportunity/{opp_id}")
        assert "Create discovery call" in page.text


def test_confirmation_emails_speak_eastern_not_utc(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn)
    opp = app_mod.db.get_opportunity(conn, opp_id)
    sent = []
    monkeypatch.setattr(meeting_scheduler.mailer, "send_email",
                        lambda to, sub, body, html=None, ics=None: sent.append((to, sub, body)))
    meeting_scheduler.schedule(
        conn, opp, start_at="2026-07-14T14:00:00+00:00",
        client_email="sarah@halcyon.com", client_name="Sarah Chen")
    conn.close()
    assert sent
    for to, sub, body in sent:
        assert "UTC" not in sub and "UTC" not in body
    assert any("10:00 AM EDT" in s[1] for s in sent)


# --------------------------------------------------------------------------- #
# "Review before it sends" is literal: the operator can edit the exact email.
# --------------------------------------------------------------------------- #
def _pid(c, opp_id):
    loc = _propose(c, opp_id).headers["location"]
    return int(loc.rstrip("/").split("/")[-1])


def test_preview_offers_an_editable_subject_and_body(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn); conn.close()
    with TestClient(app_mod.app) as c:
        pid = _pid(c, opp_id)
        page = c.get(f"/opportunity/{opp_id}/proposal/{pid}").text
    # real form fields, not a read-only <pre>
    assert 'name="subject"' in page and 'name="body"' in page
    assert "<textarea" in page and "Save draft" in page


def test_edited_body_is_persisted_and_sent_verbatim(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn); conn.close()
    sent = []
    monkeypatch.setattr(meeting_scheduler.mailer, "send_email",
                        lambda to, sub, body, html=None, ics=None: sent.append((to, sub, body)))
    custom = "Hi Ena,\n\nHand-written note about Kid audiobooks.\nOption 1 — pick here: link"
    with TestClient(app_mod.app) as c:
        pid = _pid(c, opp_id)
        # Save draft (no send) persists the edit and it survives a reload
        c.post(f"/opportunity/{opp_id}/proposal/{pid}/edit",
               data={"subject": "Custom subject line", "body": custom})
        page = c.get(f"/opportunity/{opp_id}/proposal/{pid}").text
        assert "Custom subject line" in page and "Hand-written note about Kid audiobooks" in page
        # Send delivers exactly what was saved
        c.post(f"/opportunity/{opp_id}/proposal/{pid}/send", follow_redirects=False)
    assert sent and sent[0][1] == "Custom subject line"
    assert sent[0][2] == custom


def test_send_uses_the_current_box_even_without_a_separate_save(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn); conn.close()
    sent = []
    monkeypatch.setattr(meeting_scheduler.mailer, "send_email",
                        lambda to, sub, body, html=None, ics=None: sent.append((to, sub, body)))
    with TestClient(app_mod.app) as c:
        pid = _pid(c, opp_id)
        # Post straight to /send carrying edited fields — no prior /edit call
        c.post(f"/opportunity/{opp_id}/proposal/{pid}/send",
               data={"subject": "Edited on send", "body": "Body edited on send"},
               follow_redirects=False)
    assert sent and sent[0][1] == "Edited on send" and sent[0][2] == "Body edited on send"


def test_reset_restores_the_generated_draft(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn); conn.close()
    with TestClient(app_mod.app) as c:
        pid = _pid(c, opp_id)
        c.post(f"/opportunity/{opp_id}/proposal/{pid}/edit",
               data={"subject": "Temp", "body": "Temp body"})
        c.post(f"/opportunity/{opp_id}/proposal/{pid}/edit", data={"reset": "1"})
        page = c.get(f"/opportunity/{opp_id}/proposal/{pid}").text
    # back to the generated copy, not the operator's temp text
    assert "Temp body" not in page
    assert "Let&#39;s find a time" in page or "Let's find a time" in page
