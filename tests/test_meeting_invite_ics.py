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
