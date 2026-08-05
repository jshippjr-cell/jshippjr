"""Invoice pay links reach the CLIENT (reported live: the final invoice just sat in the
operator's queue). Both the operator button and the automatic send on delivery email the
client a branded payment request with a link to their token-gated portal."""
import importlib

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from chordential_oia.models import BuyerType, MusicRequirement, Opportunity  # noqa: E402
# ADR-0044: reached where they live. `app.py` is the application object now and
# imports none of these; using it as a namespace for the package is what kept 55
# dead imports alive in it.
from chordential_oia import mailer  # noqa: E402
from chordential_oia.web.billing import _invoice_from_proposal_row  # noqa: E402


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "w.db"))
    for m in ("db", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from chordential_oia.web import app as app_mod
    return app_mod


def _project_with_final_invoice(app_mod, conn):
    db = app_mod.db
    oid = db.insert_opportunity(conn, Opportunity(
        client="Hoagies", need="Sonic logo", description="x", buyer_type=BuyerType.AGENCY,
        music_requirement=MusicRequirement.ORIGINAL, budget_min=20000, budget_max=20000))
    conn.execute("UPDATE opportunities SET contact_email=?, contact_name=? WHERE id=?",
                 ("client@hoagies.com", "Pat Hoagie", oid))
    tok = db.ensure_share_token(conn, oid)
    pid = db.insert_project(conn, opp_id=oid, client="Hoagies", need="Sonic logo",
                            budget_min=20000, budget_max=20000, deadline="",
                            roles=["Composer"], share_token=tok)
    from chordential_oia.proposals import build_proposal
    from chordential_oia.web.estimate import build_estimate
    from chordential_oia.web.evaluate import evaluate
    opp = db.opportunity_from_row(db.get_opportunity(conn, oid))
    qual, _ = evaluate(opp)
    est = build_estimate(opp, qual.team_shape or qual.discipline.team_shape, qual.discipline)
    db.insert_proposal(conn, pid, oid, build_proposal(opp, qual, est))
    invid = db.insert_invoice(conn, pid, db.proposal_for_project(conn, pid)["id"],
                              _invoice_from_proposal_row(
                                  db.get_project(conn, pid),
                                  db.proposal_for_project(conn, pid), "Final"))
    return pid, invid


def test_send_pay_link_emails_the_client_with_a_portal_link(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    sent = {}
    monkeypatch.setattr(mailer, "mail_configured", lambda: True)
    monkeypatch.setattr(mailer, "send_email",
                        lambda to, subject, text, html=None: sent.update(
                            to=to, subject=subject, text=text) or "sent")
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    pid, invid = _project_with_final_invoice(app_mod, conn); conn.close()
    with TestClient(app_mod.app) as c:
        r = c.post(f"/invoice/{invid}/send-pay-link", follow_redirects=False)
    assert r.status_code == 303 and "pay=sent" in r.headers["location"]
    assert sent["to"] == "client@hoagies.com"
    assert "Final due" in sent["subject"] and "Sonic logo" in sent["subject"]
    assert "/delivery-portal" in sent["text"] and "k=" in sent["text"]  # token-gated pay link
    # issuing it also flipped the invoice off Draft so it's actually payable
    conn = app_mod.db.connect()
    assert app_mod.db.get_invoice(conn, invid)["status"] == "Issued"; conn.close()


def test_send_pay_link_reports_a_missing_client_email(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    monkeypatch.setattr(mailer, "mail_configured", lambda: True)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    pid, invid = _project_with_final_invoice(app_mod, conn)
    conn.execute("UPDATE opportunities SET contact_email='' WHERE id="
                 "(SELECT opp_id FROM projects WHERE id=?)", (pid,))
    conn.commit(); conn.close()
    with TestClient(app_mod.app) as c:
        r = c.post(f"/invoice/{invid}/send-pay-link", follow_redirects=False)
    assert "pay=no_email" in r.headers["location"]        # honest — no silent no-op


def test_proposal_page_offers_the_email_pay_link_button(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    pid, _invid = _project_with_final_invoice(app_mod, conn); conn.close()
    with TestClient(app_mod.app) as c:
        page = c.get(f"/project/{pid}/proposal").text
    assert "Email pay link to client" in page
    assert "/send-pay-link" in page
