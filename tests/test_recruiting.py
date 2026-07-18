"""Recruiting campaign — the 'Why Chordential for artists' page + invite composer.

The composer drafts a personalized, honest invite (respect + fair terms + first-look,
never volume/salary); Jon copies, edits, and sends it. Deterministic, no LLM.
"""

import importlib

import pytest

from chordential_oia import recruiting
from chordential_oia.talent import Talent
from chordential_oia.models import MusicDiscipline


def test_invite_personalizes_with_credit():
    t = Talent(name="Mara Velez", disciplines=[MusicDiscipline.COMPOSITION],
               credits="Scored two national auto spots")
    inv = recruiting.compose_invite(
        t, apply_url="https://x/apply", artists_url="https://x/for-artists")
    assert "Mara" in inv["subject"]
    assert "Scored two national auto spots".lower() in inv["body"].lower()
    assert "https://x/apply" in inv["body"]
    assert "https://x/for-artists" in inv["body"]


def test_invite_falls_back_to_discipline_without_credit():
    t = Talent(name="Devin Park", disciplines=[MusicDiscipline.SOUND_DESIGN])
    inv = recruiting.compose_invite(
        t, apply_url="https://x/apply", artists_url="https://x/a")
    # No credit → leads with the craft, not a fabricated credit.
    assert "roster" in inv["body"].lower()
    assert inv["body"].startswith("Hi Devin,")


def test_invite_is_honest_never_promises_salary():
    t = Talent(name="Sofia Ramos", disciplines=[MusicDiscipline.SONIC_BRANDING])
    body = recruiting.compose_invite(
        t, apply_url="https://x/apply", artists_url="https://x/a")["body"].lower()
    assert "salary" not in body
    assert "steady income" not in body
    assert "we're early" in body  # under-promises volume


def test_skip_blocks():
    t = Talent(name="Ada", disciplines=[MusicDiscipline.COMPOSITION])
    inv = recruiting.compose_invite(
        t, apply_url="https://x/apply", artists_url="https://x/a", skip=["signoff"])
    assert "Chordential" in inv["body"]
    assert not inv["body"].rstrip().endswith("— Jon, Chordential")


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "test.db"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c, db_mod


def test_for_artists_page_renders(ctx):
    client, _ = ctx
    r = client.get("/for-artists")
    assert r.status_code == 200
    assert "Real briefs" in r.text
    assert "/apply" in r.text and "/refer" in r.text


def test_talent_detail_shows_invite_composer(ctx):
    client, db_mod = ctx
    conn = db_mod.connect()
    tid = db_mod.insert_talent(conn, Talent(
        name="Mara Velez", disciplines=[MusicDiscipline.COMPOSITION],
        credits="Scored two spots"))
    conn.close()
    page = client.get(f"/talent/{tid}").text
    assert "Recruiting invite" in page


def test_send_invite_falls_back_to_manual(ctx):
    # No email + null mailer → no send, stays Prospect, flagged manual (never crashes).
    client, db_mod = ctx
    conn = db_mod.connect()
    tid = db_mod.insert_talent(conn, Talent(
        name="No Email", disciplines=[MusicDiscipline.COMPOSITION]))
    conn.close()
    r = client.post(f"/talent/{tid}/invite/send", follow_redirects=False)
    assert r.status_code == 303
    assert "invite=manual" in r.headers["location"]
    conn = db_mod.connect()
    try:
        inv = conn.execute(
            "SELECT invite_status FROM talent WHERE id=?", (tid,)).fetchone()[0]
    finally:
        conn.close()
    assert inv == "Prospect"  # unchanged — nothing was sent


def test_send_invite_emails_and_advances(ctx, monkeypatch):
    client, db_mod = ctx
    from chordential_oia.web import app as app_mod
    sent = {}

    def fake_send(to, subject, text, html=None):
        sent.update(to=to, subject=subject, text=text, html=html)
        return "sent"

    monkeypatch.setattr(app_mod.mailer, "mail_configured", lambda: True)
    monkeypatch.setattr(app_mod.mailer, "send_email", fake_send)
    conn = db_mod.connect()
    tid = db_mod.insert_talent(conn, Talent(
        name="Mara Velez", email="mara@example.com",
        disciplines=[MusicDiscipline.COMPOSITION], credits="Scored two spots"))
    conn.close()
    r = client.post(f"/talent/{tid}/invite/send", follow_redirects=False)
    assert "invite=sent" in r.headers["location"]
    assert sent["to"] == "mara@example.com"
    assert "Chordential" in sent["text"]
    # Branded like the capabilities doc email — same wordmark shell, not a
    # plain-text-only send.
    assert sent["html"] is not None
    assert "wordmark-dark.png" in sent["html"]
    conn = db_mod.connect()
    try:
        inv = conn.execute(
            "SELECT invite_status FROM talent WHERE id=?", (tid,)).fetchone()[0]
    finally:
        conn.close()
    assert inv == "Invited"  # funnel advanced on a successful send


# --------------------------------------------------------------------------- #
# Accept/decline notification — reported live: "the talent that applied need
# to know if they've been accepted or declined... in what capacity, the
# rate, terms."
# --------------------------------------------------------------------------- #
def test_compose_review_decision_accepted_includes_role_and_rate():
    t = Talent(name="Mara Velez", disciplines=[MusicDiscipline.COMPOSITION],
               rate=1200, rate_unit="project")
    dec = recruiting.compose_review_decision(t, accepted=True, artists_url="https://x/a")
    assert "You're in" in dec["body"] or "you're in" in dec["body"].lower()
    assert "composition" in dec["body"].lower()
    assert "$1,200/project" in dec["body"]
    assert "roster" in dec["subject"].lower()


def test_compose_review_decision_accepted_without_rate_omits_rate_line():
    t = Talent(name="Devin Park", disciplines=[MusicDiscipline.SOUND_DESIGN])
    dec = recruiting.compose_review_decision(t, accepted=True, artists_url="https://x/a")
    assert "$" not in dec["body"]


def test_compose_review_decision_declined_is_kind_and_honest():
    t = Talent(name="Sofia Ramos", disciplines=[MusicDiscipline.SONIC_BRANDING])
    dec = recruiting.compose_review_decision(t, accepted=False, artists_url="https://x/a")
    body = dec["body"].lower()
    assert "not a fit" in body
    assert "judgment on the work" in body
    assert "reject" not in body  # no harsh language


def test_talent_review_route_emails_on_a_real_transition_to_approved(ctx, monkeypatch):
    client, db_mod = ctx
    from chordential_oia.web import app as app_mod
    sent = {}
    monkeypatch.setattr(app_mod.mailer, "mail_configured", lambda: True)
    monkeypatch.setattr(
        app_mod.mailer, "send_email",
        lambda to, subject, text, html=None: sent.update(
            to=to, subject=subject, text=text, html=html) or "sent",
    )
    conn = db_mod.connect()
    tid = db_mod.insert_talent(conn, Talent(
        name="Mara Velez", email="mara@example.com",
        disciplines=[MusicDiscipline.COMPOSITION], rate=90, rate_unit="hourly"))
    conn.close()

    r = client.post(f"/talent/{tid}/review", data={"review_status": "Approved"},
                     follow_redirects=False)
    assert r.status_code == 303
    assert sent["to"] == "mara@example.com"
    assert "$90/hr" in sent["text"]
    assert sent["html"] is not None and "wordmark-dark.png" in sent["html"]


def test_talent_review_route_does_not_resend_on_a_repeat_click(ctx, monkeypatch):
    """Clicking the already-current status pill again must not re-email —
    only a REAL transition does."""
    client, db_mod = ctx
    from chordential_oia.web import app as app_mod
    calls = []
    monkeypatch.setattr(app_mod.mailer, "mail_configured", lambda: True)
    monkeypatch.setattr(
        app_mod.mailer, "send_email",
        lambda to, subject, text, html=None: calls.append(to) or "sent",
    )
    conn = db_mod.connect()
    tid = db_mod.insert_talent(conn, Talent(
        name="Mara Velez", email="mara@example.com",
        disciplines=[MusicDiscipline.COMPOSITION]))
    conn.close()

    client.post(f"/talent/{tid}/review", data={"review_status": "Approved"})
    client.post(f"/talent/{tid}/review", data={"review_status": "Approved"})
    assert calls == ["mara@example.com"]  # only the first, real transition


def test_talent_review_route_never_crashes_without_email_or_mail(ctx):
    client, db_mod = ctx
    conn = db_mod.connect()
    tid = db_mod.insert_talent(conn, Talent(
        name="No Email", disciplines=[MusicDiscipline.COMPOSITION]))
    conn.close()
    r = client.post(f"/talent/{tid}/review", data={"review_status": "Approved"},
                     follow_redirects=False)
    assert r.status_code == 303


# --------------------------------------------------------------------------- #
# Project-scope email on signing — reported live: "when I sign the talent,
# email blasts should go out... giving them a scope of what the project is."
# --------------------------------------------------------------------------- #
def test_compose_project_assignment_includes_client_role_and_rate_not_budget():
    t = Talent(name="Ada Lin", disciplines=[MusicDiscipline.COMPOSITION],
               rate=1500, rate_unit="project")
    scope = recruiting.compose_project_assignment(
        t, role="Composer", client="Acme Corp", need="A 30s brand anthem",
        deadline="2026-08-01",
    )
    body = scope["body"]
    assert "Acme Corp" in body
    assert "Composer" in body
    assert "A 30s brand anthem" in body
    # the creator sees THEIR rate, never the client's project budget (not tactful)
    assert "$1,500/project" in body
    assert "Budget" not in body
    assert "2026-08-01" in body
    assert "Acme Corp" in scope["subject"]


def test_compose_client_assignment_update_is_warm_and_hides_the_rate():
    scope = recruiting.compose_client_assignment_update(
        role="Composer", creator_name="Ada Lin", need="A 30s brand anthem",
        contact_name="Sam Rivera", workspace_url="https://chordential.com/workspace/tok",
    )
    body = scope["body"]
    assert "Sam" in body                      # greets the client contact by first name
    assert "Ada" in body and "Composer" in body
    assert "A 30s brand anthem" in body
    assert "/workspace/tok" in body           # points them at their workspace
    assert "rate" not in body.lower() and "$" not in body   # never leaks cost


def test_project_assign_route_emails_the_signed_creator(ctx, monkeypatch):
    client, db_mod = ctx
    from chordential_oia.web import app as app_mod
    sent = {}
    monkeypatch.setattr(app_mod.mailer, "mail_configured", lambda: True)
    monkeypatch.setattr(
        app_mod.mailer, "send_email",
        lambda to, subject, text, html=None: sent.update(
            to=to, subject=subject, text=text, html=html) or "sent",
    )
    conn = db_mod.connect()
    tid = db_mod.insert_talent(conn, Talent(
        name="Ada Lin", email="ada@example.com",
        disciplines=[MusicDiscipline.COMPOSITION], rate=90.0))
    # ADR-0024: assignment requires an executed agreement + rate on file.
    db_mod.set_talent_agreement(conn, tid, "2026-07-18", "test agreement")
    pid = db_mod.insert_project(
        conn, opp_id=None, client="Acme Corp", need="A 30s brand anthem",
        budget_min=4000, budget_max=6000, deadline="2026-08-01", roles=["Composer"],
    )
    conn.close()

    r = client.post(f"/project/{pid}/assign",
                     data={"role": "Composer", "talent_id": tid},
                     follow_redirects=False)
    assert r.status_code == 303
    assert sent["to"] == "ada@example.com"
    assert "Acme Corp" in sent["text"]
    assert "Composer" in sent["text"]
    assert sent["html"] is not None


def test_project_assign_never_crashes_without_email_or_mail(ctx):
    client, db_mod = ctx
    conn = db_mod.connect()
    tid = db_mod.insert_talent(conn, Talent(
        name="No Email", disciplines=[MusicDiscipline.COMPOSITION]))
    pid = db_mod.insert_project(
        conn, opp_id=None, client="Acme Corp", need="Brand anthem",
        budget_min=None, budget_max=None, deadline="", roles=["Composer"],
    )
    conn.close()
    r = client.post(f"/project/{pid}/assign",
                     data={"role": "Composer", "talent_id": tid},
                     follow_redirects=False)
    assert r.status_code == 303
