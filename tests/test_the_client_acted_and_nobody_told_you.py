"""Every client action in the workspace reaches the operator's phone.

    "when the client signs the discovery summary I don't get a notification"
                                                        — the operator, 2026-08-27

Traced, it was not a missing channel. `_notify_operator_review` pushes both Web Push and
ntfy, and ELEVEN delivery events call it — a composer submitting a take, a reviewer leaving
a comment, a deliverable landing. Every one of those reaches a phone.

The four client actions in `workspace_routes` reached none of them. Confirming the scope,
flagging it as wrong, approving the proposal, SIGNING it: all four emailed the operator and
stopped there. So the events that close a deal were the quietest in the product, and the
one that closes it hardest was silent.

The cause is banal and worth naming, because it is the kind that recurs: the only helper
available built a DELIVERY CONSOLE url. That is the wrong destination for a signature —
there is no project yet — so the caller reached for it, found it did not fit, and reached
for nothing instead. Splitting the push out from the URL is the whole fix.
"""
import importlib
import time

import pytest

pytest.importorskip("fastapi")


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "w.db"))
    monkeypatch.setenv("CHORDENTIAL_OPERATOR_EMAIL", "jon@chordential.example")
    monkeypatch.setenv("CHORDENTIAL_PUBLIC_DOMAIN", "https://chordential.com")
    monkeypatch.delenv("CHORDENTIAL_ADMIN_TOKEN", raising=False)
    for m in ("db", "campaign_intelligence", "campaigns", "next_action", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.models import BuyerType, MusicRequirement, Opportunity
    from chordential_oia.web import app as app_mod, workspace_routes as W

    pushed = []
    monkeypatch.setattr(W.delivery_ops, "notify_operator",
                        lambda title, body, url: pushed.append(
                            {"title": title, "body": body, "url": url}))
    db = app_mod.db
    with TestClient(app_mod.app) as c:
        conn = db.connect()
        try:
            oid = db.insert_opportunity(conn, Opportunity(
                client="Pike and Rowan", need="Autumn brand film",
                description="A two-minute brand film with a 30-second cut.",
                buyer_type=BuyerType.BRAND,
                music_requirement=MusicRequirement.ORIGINAL))
            conn.execute("UPDATE opportunities SET contact_email=? WHERE id=?",
                         ("marisa@pike.example", oid))
            conn.commit()
            db.create_meeting(conn, opp_id=oid, start_at="2026-08-20T14:00:00+00:00",
                              status="ingested")
            token = db.ensure_share_token(conn, oid)
        finally:
            conn.close()
        yield c, token, oid, pushed


def _settle(pushed, want=1, timeout=3.0):
    """The push is fired off the request thread — it must never make the client wait for
    a notification addressed to somebody else."""
    deadline = time.time() + timeout
    while len(pushed) < want and time.time() < deadline:
        time.sleep(0.05)
    return pushed


def test_signing_reaches_the_operator(workspace):
    c, token, oid, pushed = workspace
    c.post(f"/workspace/{token}/sign",
           data={"typed_name": "Marisa del Rio", "signer_email": "marisa@pike.example",
                 "consent": "1"}, follow_redirects=False)
    got = _settle(pushed)
    assert got, "the client signed and nothing was pushed"
    assert "Signed" in got[0]["title"] and "Pike and Rowan" in got[0]["title"]
    assert "Marisa del Rio" in got[0]["body"]


def test_the_push_lands_on_the_agreement_not_a_delivery_console(workspace):
    """THE CAUSE, pinned. The only helper available built a delivery-console URL, which is
    meaningless for a signature — there is no project yet. A push that opens the wrong page
    is a push the operator learns to ignore."""
    c, token, oid, pushed = workspace
    c.post(f"/workspace/{token}/sign",
           data={"typed_name": "Marisa del Rio", "signer_email": "", "consent": "1"},
           follow_redirects=False)
    url = _settle(pushed)[0]["url"]
    assert url.endswith(f"/opportunity/{oid}#agreement"), url
    assert "/project/" not in url and "delivery" not in url


def test_approving_the_proposal_reaches_the_operator(workspace):
    """Approving closes the deal as surely as signing. It had the same gap, one screen
    over, and would have been reported the same way a week later."""
    c, token, oid, pushed = workspace
    from chordential_oia.web import app as app_mod
    conn = app_mod.db.connect()
    try:
        app_mod.db.release_commercial_review(conn, oid, 1, "{}")
        conn.commit()
    finally:
        conn.close()
    c.post(f"/workspace/{token}/approve",
           data={"approver_name": "Marisa del Rio", "approver_email": "m@pike.example",
                 "scope_ok": "1"}, follow_redirects=False)
    got = _settle(pushed)
    assert got, "the client approved and nothing was pushed"
    assert "Approved" in got[0]["title"]


def test_a_client_saying_the_summary_is_wrong_reaches_the_operator(workspace):
    """The most urgent thing in the file. Every hour it sits unread is an hour the client
    thinks we misheard them and are proceeding anyway."""
    c, token, oid, pushed = workspace
    c.post(f"/workspace/{token}/confirm-scope",
           data={"decision": "no", "confirmed_by": "Marisa del Rio",
                 "comment": "The term is twelve months, not three years."},
           follow_redirects=False)
    got = _settle(pushed)
    assert got, "the client flagged a correction and nothing was pushed"
    assert "fix" in got[0]["title"].lower()
    assert "twelve months" in got[0]["body"]
    assert got[0]["url"].endswith("edit=1"), "the push must open the editor"


def test_confirming_the_scope_reaches_the_operator(workspace):
    c, token, oid, pushed = workspace
    c.post(f"/workspace/{token}/confirm-scope",
           data={"decision": "yes", "confirmed_by": "Marisa del Rio"},
           follow_redirects=False)
    assert _settle(pushed), "the client confirmed and nothing was pushed"


def test_no_client_action_in_the_workspace_is_silent():
    """The class, not the instance. Every POST a CLIENT can make from their workspace has
    to tell the operator something — a new one added without a push is this bug again."""
    import pathlib
    import re
    from chordential_oia.web import app as app_mod
    src = pathlib.Path(app_mod.__file__).with_name("workspace_routes.py").read_text(
        encoding="utf-8")
    posts = re.findall(r'@router\.post\("(/workspace/[^"]+)"\)', src)
    assert len(posts) >= 4, posts
    assert src.count("delivery_ops.notify_operator") >= len(posts) - 1, (
        f"{len(posts)} client actions, "
        f"{src.count('delivery_ops.notify_operator')} pushes — one is silent")


def test_the_push_helper_is_one_place(workspace):
    """`_notify_operator_review` and the workspace both send through it, so a channel added
    later reaches every event rather than the eleven that remembered."""
    from chordential_oia.web import delivery_ops
    import inspect
    body = inspect.getsource(delivery_ops._notify_operator_review)
    assert "notify_operator(" in body
    assert "send_web_push" not in body, "the review path pushes on its own again"
