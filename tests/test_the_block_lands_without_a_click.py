"""A booked call must appear on the calendar without anyone pressing anything.

Reported live, after the invite was fixed to arrive as an invitation rather than as a
download: *"I dont want to click anything ... it was automatically booked in both my and
the clients calendar."*

Three separate things stood between a booking and a block, and only the first of them was
about the MIME type:

  1. The operator was listed as a GUEST of their own meeting — ``RSVP=TRUE``,
     ``PARTSTAT=NEEDS-ACTION`` — so their own calendar greyed the entry out and waited for
     a Yes. They are the ORGANIZER; nobody has to accept their own invitation.
  2. ``ORGANIZER`` named the operator while the mail left from ``CHORDENTIAL_SMTP_FROM``.
     An invitation whose organiser is unrelated to its sender reads as forged, and a
     calendar that suspects a forgery shows the mail and books nothing. ``SENT-BY`` is the
     property that authorises the difference (RFC 5545 §3.2.18).
  3. ``SEQUENCE`` was hardcoded — 0 on booking, 1 on EVERY reschedule. A calendar ignores
     an update that does not outrank the one it holds, so the second time a call moved,
     the block stayed where it was and nothing anywhere reported a failure.

The client's side has a floor: an invitation asks, it cannot write to a stranger's
calendar, and a system that could would be worse than one that asks. What is guaranteed
here is that the client's invitation is genuinely sent and genuinely well-formed.
"""
import importlib

import pytest

from chordential_oia.models import BuyerType, MusicRequirement, Opportunity


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "c.db"))
    monkeypatch.setenv("CHORDENTIAL_OPERATOR_EMAIL", "jon@chordential.com")
    monkeypatch.delenv("CHORDENTIAL_SMTP_FROM", raising=False)
    monkeypatch.delenv("CHORDENTIAL_CALENDAR_PROVIDER", raising=False)
    from chordential_oia.web import db as dbm
    dbm = importlib.reload(dbm)
    from chordential_oia.web import meeting_scheduler as ms
    ms = importlib.reload(ms)
    conn = dbm.connect(str(tmp_path / "c.db"))
    dbm.init_db(conn)
    opp_id = dbm.insert_opportunity(conn, Opportunity(
        client="Aurora", need="Holiday anthem", description="x",
        buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL))
    opp = dbm.get_opportunity(conn, opp_id)
    mid = dbm.create_meeting(
        conn, opp_id=opp_id, start_at="2026-09-20T15:00:00+00:00", duration_min=30,
        join_url="https://us04web.zoom.us/j/123", meeting_type="zoom",
        client_name="Ena Shipp", client_email="client@aurora.com", manage_token="tok")
    try:
        yield dbm, ms, conn, opp, dbm.get_meeting(conn, mid)
    finally:
        conn.close()


def _lines(ics: str) -> list:
    """Content lines, unfolded — RFC 5545 wraps at 75 octets, so nothing can be read off
    the wire text directly (this test suite learned that the same way a parser would)."""
    return ics.replace("\r\n ", "").split("\r\n")


def _line(ics: str, prefix: str, addr: str = "") -> str:
    for line in _lines(ics):
        if line.startswith(prefix) and (not addr or line.endswith(f"mailto:{addr}")):
            return line
    raise AssertionError(f"no {prefix} line for {addr or '—'} in:\n{ics}")


def _attendee(ics: str, addr: str) -> str:
    return _line(ics, "ATTENDEE", addr)


# ── 1. nobody accepts their own meeting ──────────────────────────────────────────
def test_the_operator_is_the_organiser_not_a_guest_awaiting_their_own_reply(env):
    _dbm, ms, _conn, opp, m = env
    line = _attendee(ms.build_invite_ics(m, opp), "jon@chordential.com")
    assert "PARTSTAT=ACCEPTED" in line, "the organiser's own block must land already booked"
    assert "RSVP=TRUE" not in line, "nothing to press: the operator scheduled this call"
    assert "ROLE=CHAIR" in line


def test_the_client_is_asked_because_asking_is_all_an_invitation_can_do(env):
    _dbm, ms, _conn, opp, m = env
    line = _attendee(ms.build_invite_ics(m, opp), "client@aurora.com")
    assert "RSVP=TRUE" in line and "PARTSTAT=NEEDS-ACTION" in line


# ── 2. the invitation is authorised to come from the address that sent it ────────
def test_sent_by_authorises_a_sender_that_is_not_the_organiser(env, monkeypatch):
    _dbm, ms, _conn, opp, m = env
    monkeypatch.setenv("CHORDENTIAL_SMTP_FROM", "hello@chordential.com")
    org = _line(ms.build_invite_ics(m, opp), "ORGANIZER")
    assert 'SENT-BY="mailto:hello@chordential.com"' in org
    assert org.endswith("mailto:jon@chordential.com"), "the operator still owns the meeting"


def test_no_sent_by_when_the_operator_is_the_sender(env, monkeypatch):
    _dbm, ms, _conn, opp, m = env
    monkeypatch.setenv("CHORDENTIAL_SMTP_FROM", "JON@chordential.com")   # same, cased oddly
    assert "SENT-BY" not in _line(ms.build_invite_ics(m, opp), "ORGANIZER")


# ── 3. every move outranks the last ──────────────────────────────────────────────
def test_a_second_reschedule_still_moves_the_block(env, monkeypatch):
    """The one that fails silently: a calendar drops an update whose SEQUENCE does not
    exceed what it holds, so under the old fixed 1 the first move landed and no other did."""
    dbm, ms, conn, opp, m = env
    monkeypatch.setattr(ms, "_safe_mail", lambda *a, **k: None)
    seqs = []
    real = ms.build_invite_ics
    monkeypatch.setattr(ms, "build_invite_ics",
                        lambda mt, o, **kw: seqs.append(kw.get("sequence", 0)) or real(mt, o, **kw))

    ms._send_confirmations(opp, m)                                  # the booking
    ms.reschedule(conn, dbm.get_meeting(conn, m["id"]), "2026-09-21T15:00:00+00:00")
    ms.reschedule(conn, dbm.get_meeting(conn, m["id"]), "2026-09-22T15:00:00+00:00")
    ms.cancel(conn, dbm.get_meeting(conn, m["id"]))

    assert seqs == sorted(set(seqs)) and len(seqs) == 4, (
        f"every invitation must outrank the last, got {seqs}")


def test_the_sequence_is_advanced_in_one_statement(env):
    """Two changes racing must not be handed the same number — a repeated SEQUENCE is not
    a collision that raises, it is a change that vanishes."""
    dbm, _ms, conn, _opp, m = env
    assert dbm.bump_ical_sequence(conn, m["id"]) == 1
    assert dbm.bump_ical_sequence(conn, m["id"]) == 2
    assert dbm.get_meeting(conn, m["id"])["ical_sequence"] == 2


def test_a_row_written_before_the_column_existed_still_builds_an_invite(env):
    _dbm, ms, _conn, opp, m = env
    assert ms._ical_seq({"ical_sequence": None}) == 0
    assert ms._ical_seq({}) == 0


# ── 4. a line no strict parser will refuse ───────────────────────────────────────
def test_long_lines_are_folded_and_unfold_back_to_what_was_written(env):
    """RFC 5545 §3.1 caps a content line at 75 octets. Lenient parsers ignore it; strict
    ones reject the whole VEVENT — and a DESCRIPTION carrying a Zoom link with a password
    clears 75 without trying. Folding must also never cut a multi-byte character in half,
    which would corrupt the very titles our copy is full of (·, ×)."""
    _dbm, ms, conn, opp, m = env
    long_join = ("https://us04web.zoom.us/j/1234567890?pwd="
                 + "abcdefghijklmnopqrstuvwxyz0123456789")
    _dbm.update_meeting(conn, m["id"], join_url=long_join)
    ics = ms.build_invite_ics(_dbm.get_meeting(conn, m["id"]), opp)

    assert all(len(line.encode("utf-8")) <= 75 for line in ics.split("\r\n")), ics
    unfolded = ics.replace("\r\n ", "")
    assert long_join in unfolded, "folding must be reversible"
    assert "SUMMARY:Discovery call · Chordential × Ena Shipp" in unfolded


# ── 5. an invitation goes to whoever the provider did not reach ──────────────────
@pytest.mark.parametrize("connected,invites,expect", [
    (False, False, ("ics", "ics")),      # nothing connected: both invited by email
    (True, True, (None, None)),          # OAuth: Google invites both; ours would duplicate
    (True, False, ("ics", None)),        # service account: books the operator, invites nobody
])
def test_each_side_is_invited_exactly_once(env, monkeypatch, connected, invites, expect):
    """Three configurations, three answers — and the code used to have two. Whichever way
    you answer "does an event id mean everyone was invited", one of these comes out wrong:
    the client loses their only block, or the operator gets the same call twice."""
    dbm, ms, conn, opp, m = env
    if connected:
        conn.execute("UPDATE meetings SET calendar_event_id = 'g-evt' WHERE id = ?",
                     (m["id"],))
        conn.commit()
        monkeypatch.setenv("CHORDENTIAL_CALENDAR_PROVIDER", "google")
        monkeypatch.setattr(ms.M, "get_calendar_provider",
                            lambda: type("P", (), {"invites_attendees": lambda s: invites})())
    client_ics, op_ics = ms.invites_for(dbm.get_meeting(conn, m["id"]), opp)
    got = tuple("ics" if v else None for v in (client_ics, op_ics))
    assert got == expect


# ── the shape of the whole thing, end to end ─────────────────────────────────────
def test_booking_puts_a_well_formed_invitation_in_both_inboxes(env, monkeypatch):
    _dbm, ms, _conn, opp, m = env
    sent = []
    monkeypatch.setattr(ms.mailer, "send_email",
                        lambda to, subject, text, html=None, ics=None:
                        sent.append((to, text, ics)) or "sent")
    ms._send_confirmations(opp, m)
    by_to = {to: (text, ics) for to, text, ics in sent}
    assert set(by_to) == {"client@aurora.com", "jon@chordential.com"}
    for to, (text, ics) in by_to.items():
        assert ics and "METHOD:REQUEST" in ics and "SEQUENCE:0" in ics
        assert "DTSTART:20260920T150000Z" in ics
        assert "on your calendar" in text, f"{to} was not told where the call went"
    assert "nothing to accept" in by_to["jon@chordential.com"][0]
