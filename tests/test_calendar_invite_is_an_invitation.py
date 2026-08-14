"""A calendar invite has to arrive as an INVITATION, not as a file to download.

The operator's report: "When the client has agreed on a time to have the Zoom meeting,
it used to block my calendar. That's no longer working."

Everything up to the wire was right. The client accepts a time, the booking runs the one
engine, a valid VCALENDAR/METHOD:REQUEST is built with the correct DTSTART, DTEND, UID
and ORGANIZER, and it is attached to both the client's and the operator's confirmation.

Then it was attached with `add_attachment()`, which stamps

    Content-Disposition: attachment; filename="invite.ics"

A text/calendar part marked as an attachment is a FILE. Gmail, Apple Mail and Outlook
offer to download it; none of them treat it as an invitation, so no block ever lands on
anyone's calendar. The invite was being built correctly, sent correctly, and presented
as a download.

An invitation is an ALTERNATIVE part with no Content-Disposition — the shape Google
Calendar and Outlook themselves send.
"""
import pytest

ICS = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nMETHOD:REQUEST\r\nBEGIN:VEVENT\r\n"
       "UID:chord-meeting-8@chordential.com\r\nDTSTART:20260920T150000Z\r\n"
       "DTEND:20260920T153000Z\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")


def _msg(html=None):
    from chordential_oia.mailer import _build_message
    return _build_message("dana@vance.example", "Discovery call confirmed",
                          "text body", html, "jon@chordential.com", ICS)


def _calendar_part(msg):
    for p in msg.walk():
        if p.get_content_type() == "text/calendar":
            return p
    return None


def test_the_calendar_part_is_not_an_attachment():
    """The bug, in one assertion. As an attachment it is a download, not an invite."""
    cal = _calendar_part(_msg())
    assert cal is not None, "no text/calendar part at all"
    assert not cal.get("Content-Disposition"), (
        "a calendar part marked as an attachment is a file the client offers to "
        "download; it never reaches anyone's calendar")


def test_it_carries_method_request():
    """Without method=REQUEST a client shows an event preview and no RSVP."""
    cal = _calendar_part(_msg())
    assert cal.get_param("method") == "REQUEST"
    assert (cal.get_param("charset") or "").upper() == "UTF-8"


def test_it_sits_inside_multipart_alternative():
    """An invitation is an ALTERNATIVE to the body text, not something bolted beside
    it — that is the shape Google Calendar and Outlook themselves send."""
    msg = _msg()
    alt = [p for p in msg.walk() if p.get_content_type() == "multipart/alternative"]
    assert alt, "the calendar must be an alternative part"
    kinds = [p.get_content_type() for p in alt[0].walk()]
    assert "text/plain" in kinds and "text/calendar" in kinds


def test_the_invitation_survives_an_html_body():
    msg = _msg(html="<p>Your discovery call is confirmed.</p>")
    alt = [p for p in msg.walk() if p.get_content_type() == "multipart/alternative"][0]
    kinds = [p.get_content_type() for p in alt.walk()]
    assert kinds.count("text/calendar") == 1
    assert "text/html" in kinds
    assert not _calendar_part(msg).get("Content-Disposition")


def test_a_downloadable_copy_is_still_offered():
    """Some clients only look for a file. It is second, and application/ics, so it
    cannot compete with the invitation above it."""
    msg = _msg()
    files = [p for p in msg.walk()
             if (p.get("Content-Disposition") or "").startswith("attachment")]
    assert len(files) == 1
    assert files[0].get_content_type() == "application/ics"
    assert files[0].get_filename() == "invite.ics"


def test_the_body_is_still_readable_without_any_calendar_client():
    msg = _msg()
    plain = [p for p in msg.walk() if p.get_content_type() == "text/plain"][0]
    assert "text body" in plain.get_content()


def test_no_calendar_means_a_plain_message():
    from chordential_oia.mailer import _build_message
    msg = _build_message("a@b.c", "s", "t", None, "f@g.h", None)
    assert msg.get_content_type() == "text/plain"
    assert _calendar_part(msg) is None


def test_accepting_a_time_sends_an_invitation_to_both_sides(monkeypatch, tmp_path):
    """End to end on the path the operator reported: the client picks an option."""
    import importlib

    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "c.sqlite"))
    monkeypatch.setenv("CHORDENTIAL_OPERATOR_EMAIL", "jon@chordential.com")
    from chordential_oia.web import db as dbm
    importlib.reload(dbm)
    from chordential_oia import mailer
    from chordential_oia.web import meeting_scheduler as ms
    from chordential_oia.models import Opportunity

    conn = dbm.connect()
    dbm.init_db(conn)
    sent = []
    monkeypatch.setattr(mailer, "send_email",
                        lambda to, subject, text, ics=None, **kw:
                        sent.append((to, ics or "")))

    opp_id = dbm.insert_opportunity(conn, Opportunity(
        client="Vance Athletic", need="Spring launch", description=""))
    pid = dbm.create_meeting_proposal(
        conn, opp_id=opp_id, token="tk_cal",
        slots=["2026-09-20T15:00:00+00:00"], meeting_type="zoom", duration_min=30,
        client_name="Dana", client_email="dana@vance.example", message="",
        join_url="https://zoom.example/j/9")
    conn.execute("UPDATE meeting_proposals SET status='sent' WHERE id = ?", (pid,))
    conn.commit()

    ms.book_from_proposal(conn, dbm.meeting_proposal_by_token(conn, "tk_cal"), 0)
    conn.close()

    assert len(sent) == 2, "both the client and the operator must be invited"
    for to, ics in sent:
        assert "BEGIN:VCALENDAR" in ics, f"{to} got no invite"
        assert "METHOD:REQUEST" in ics
        assert "DTSTART:20260920T150000Z" in ics
