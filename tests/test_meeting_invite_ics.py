"""Calendar invites reach BOTH parties, provider-independent (reported live: the client got
a Zoom link but neither party got a calendar block, and the operator email had no join link).

Booking now attaches a standard ``.ics`` (text/calendar; method=REQUEST) to both confirmation
emails, so the event lands on any calendar straight from the email with no Google-API connection
required — and the operator's email carries the join + manage links too.
"""
import importlib

import pytest

from chordential_oia.models import BuyerType, MusicRequirement, Opportunity


def _mods(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "m.db"))
    monkeypatch.setenv("CHORDENTIAL_OPERATOR_EMAIL", "jon@chordential.com")
    from chordential_oia.web import db as dbm
    dbm = importlib.reload(dbm)
    from chordential_oia.web import meeting_scheduler as ms
    ms = importlib.reload(ms)
    conn = dbm.connect(str(tmp_path / "m.db"))
    dbm.init_db(conn)
    return dbm, ms, conn


def _opp(dbm, conn):
    oid = dbm.insert_opportunity(conn, Opportunity(
        client="Aurora", need="Holiday anthem", description="x",
        buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
        budget_min=0, budget_max=0))
    return dbm.get_opportunity(conn, oid)


def _meeting(dbm, conn, opp, **kw):
    base = dict(opp_id=opp["id"], start_at="2026-07-12T18:00:00+00:00", duration_min=30,
                join_url="https://us04web.zoom.us/j/123", meeting_type="zoom",
                client_name="Ena Shipp", client_email="client@aurora.com",
                manage_token="tok123")
    base.update(kw)
    mid = dbm.create_meeting(conn, **base)
    return dbm.get_meeting(conn, mid)


def test_build_invite_ics_is_a_valid_vevent_with_both_attendees(tmp_path, monkeypatch):
    dbm, ms, conn = _mods(tmp_path, monkeypatch)
    opp = _opp(dbm, conn)
    m = _meeting(dbm, conn, opp)
    ics = ms.build_invite_ics(m, opp)
    assert ics and "BEGIN:VCALENDAR" in ics and "BEGIN:VEVENT" in ics
    assert "METHOD:REQUEST" in ics and "STATUS:CONFIRMED" in ics
    assert f"UID:chord-meeting-{m['id']}@chordential.com" in ics
    assert "DTSTART:20260712T180000Z" in ics and "DTEND:20260712T183000Z" in ics
    # both parties are attendees; the join link is embedded so the block is actionable
    assert "mailto:client@aurora.com" in ics and "mailto:jon@chordential.com" in ics
    assert "https://us04web.zoom.us/j/123" in ics
    assert ics.endswith("\r\n") and "END:VCALENDAR" in ics


def test_no_ics_without_a_real_start_time(tmp_path, monkeypatch):
    dbm, ms, conn = _mods(tmp_path, monkeypatch)
    opp = _opp(dbm, conn)
    m = _meeting(dbm, conn, opp, start_at="")
    assert ms.build_invite_ics(m, opp) is None


def test_confirmations_attach_ics_to_both_and_give_operator_the_join_link(tmp_path, monkeypatch):
    dbm, ms, conn = _mods(tmp_path, monkeypatch)
    opp = _opp(dbm, conn)
    m = _meeting(dbm, conn, opp)
    sent = []
    monkeypatch.setattr(ms.mailer, "send_email",
                        lambda to, subject, text, html=None, ics=None:
                        sent.append(dict(to=to, subject=subject, text=text, ics=ics)) or "sent")
    ms._send_confirmations(opp, m)
    by_to = {s["to"]: s for s in sent}
    assert "client@aurora.com" in by_to and "jon@chordential.com" in by_to
    # both carry a real calendar invite
    assert by_to["client@aurora.com"]["ics"] and "BEGIN:VEVENT" in by_to["client@aurora.com"]["ics"]
    assert by_to["jon@chordential.com"]["ics"] and "BEGIN:VEVENT" in by_to["jon@chordential.com"]["ics"]
    # the operator email now contains the join link AND the manage link (it had neither)
    op_text = by_to["jon@chordential.com"]["text"]
    assert "https://us04web.zoom.us/j/123" in op_text
    assert "/meeting/" in op_text and "k=tok123" in op_text


def _sent(ms, monkeypatch):
    out = []
    monkeypatch.setattr(ms.mailer, "send_email",
                        lambda to, subject, text, html=None, ics=None:
                        out.append(dict(to=to, text=text, ics=ics)) or "sent")
    return out


def test_no_ics_when_the_provider_really_invited_them(tmp_path, monkeypatch):
    """OAuth-as-the-operator: Google natively invites both parties, so our own .ics would
    put a SECOND entry on both calendars. Suppress it — this half was always right."""
    dbm, ms, conn = _mods(tmp_path, monkeypatch)
    opp = _opp(dbm, conn)
    m = _meeting(dbm, conn, opp, calendar_event_id="google-evt-abc")
    monkeypatch.setenv("CHORDENTIAL_CALENDAR_PROVIDER", "google")
    monkeypatch.setattr(ms.M, "get_calendar_provider",
                        lambda: type("P", (), {"invites_attendees": lambda self: True})())
    sent = _sent(ms, monkeypatch)
    ms._send_confirmations(opp, m)
    assert sent and all(s["ics"] is None for s in sent)   # no duplicate calendar attachment


def test_the_ics_still_goes_when_the_provider_invited_nobody(tmp_path, monkeypatch):
    """The service-account case, and the bug: a native event exists, so the .ics was
    suppressed — but a service account cannot invite guests on a consumer calendar and is
    called with no attendees at all. The operator got their block and the CLIENT got an
    email telling them about an invitation that had been withheld."""
    dbm, ms, conn = _mods(tmp_path, monkeypatch)
    opp = _opp(dbm, conn)
    m = _meeting(dbm, conn, opp, calendar_event_id="google-evt-abc")
    monkeypatch.setenv("CHORDENTIAL_CALENDAR_PROVIDER", "google")
    monkeypatch.setattr(ms.M, "get_calendar_provider",
                        lambda: type("P", (), {"invites_attendees": lambda self: False})())
    sent = _sent(ms, monkeypatch)
    ms._send_confirmations(opp, m)
    by_to = {s["to"]: s for s in sent}
    assert by_to["client@aurora.com"]["ics"], "the client's only route to a calendar block"
    assert by_to["jon@chordential.com"]["ics"] is None, (
        "the operator already has the native event — a second invitation double-books them")


def test_the_email_never_promises_an_invite_it_did_not_send(tmp_path, monkeypatch):
    dbm, ms, conn = _mods(tmp_path, monkeypatch)
    opp = _opp(dbm, conn)
    m = _meeting(dbm, conn, opp, calendar_event_id="google-evt-abc")
    monkeypatch.setenv("CHORDENTIAL_CALENDAR_PROVIDER", "google")
    monkeypatch.setattr(ms.M, "get_calendar_provider",
                        lambda: type("P", (), {"invites_attendees": lambda self: True})())
    sent = _sent(ms, monkeypatch)
    ms._send_confirmations(opp, m)
    for s in sent:
        assert s["ics"] is None
        assert "on your calendar" not in s["text"], (
            "the copy claimed a calendar block that this email did not carry")


def test_reschedule_bumps_sequence_so_the_same_event_updates(tmp_path, monkeypatch):
    dbm, ms, conn = _mods(tmp_path, monkeypatch)
    opp = _opp(dbm, conn)
    m = _meeting(dbm, conn, opp)
    first = ms.build_invite_ics(m, opp, sequence=0)
    updated = ms.build_invite_ics(m, opp, sequence=1)
    assert "SEQUENCE:0" in first and "SEQUENCE:1" in updated
    # same UID → an update to the existing calendar entry, not a duplicate
    uid = f"UID:chord-meeting-{m['id']}@chordential.com"
    assert uid in first and uid in updated
    cancelled = ms.build_invite_ics(m, opp, sequence=2, cancel=True)
    assert "METHOD:CANCEL" in cancelled and "STATUS:CANCELLED" in cancelled
