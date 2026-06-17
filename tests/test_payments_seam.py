"""Payment seam (Cycle 3.3) — provider isolation, Stripe wires in later.

The deterministic engines never import a payment SDK; the provider is selected by
env and defaults to a deterministic no-op. Importing the Stripe stub must not
require the stripe package.
"""

import importlib

import pytest

from chordential_oia.payments import (
    NullPaymentProvider,
    get_payment_provider,
)


def test_default_provider_is_null(monkeypatch):
    monkeypatch.delenv("CHORDENTIAL_PAYMENT_PROVIDER", raising=False)
    assert isinstance(get_payment_provider(), NullPaymentProvider)


def test_null_checkout_is_deterministic_no_network():
    p = NullPaymentProvider()
    inv = {"id": 7, "kind": "Deposit"}
    ref = p.create_checkout(inv)
    assert ref == p.create_checkout(inv)        # deterministic
    assert ref == "null-checkout-deposit-7"


def test_provider_selection_honors_env(monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_PAYMENT_PROVIDER", "stripe")
    # Selecting stripe must not require the SDK just to construct the provider.
    provider = get_payment_provider()
    assert provider.name == "stripe"


def test_stripe_stub_imports_without_sdk():
    # Importing the module never imports the stripe package at top level.
    mod = importlib.import_module("chordential_oia.payments.stripe")
    assert hasattr(mod, "StripePaymentProvider")


def test_engines_do_not_import_stripe():
    import sys
    # Importing the deterministic engines must not pull in the stripe SDK.
    for m in ("chordential_oia.proposals", "chordential_oia.invoicing"):
        importlib.import_module(m)
    assert "stripe" not in sys.modules


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "test.db"))
    monkeypatch.delenv("CHORDENTIAL_PAYMENT_PROVIDER", raising=False)
    from fastapi.testclient import TestClient
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c, db_mod


def test_checkout_route_stores_external_ref(ctx):
    client, db_mod = ctx
    from chordential_oia.models import BuyerType, MusicRequirement, Opportunity
    conn = db_mod.connect()
    opp_id = db_mod.insert_opportunity(conn, Opportunity(
        client="Acme", need="Original spot music",
        buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
        budget_min=8000, budget_max=15000,
    ))
    conn.close()
    pid = int(client.post(f"/opportunity/{opp_id}/project",
                          follow_redirects=False).headers["location"].split("/project/")[1])
    client.post(f"/project/{pid}/proposal")
    client.post(f"/project/{pid}/invoice", data={"kind": "Deposit"})
    conn = db_mod.connect()
    iid = db_mod.list_invoices(conn, pid)[0]["id"]
    conn.close()

    client.post(f"/invoice/{iid}/checkout")
    conn = db_mod.connect()
    try:
        inv = db_mod.get_invoice(conn, iid)
    finally:
        conn.close()
    assert inv["status"] == "Issued"
    assert inv["external_ref"] == "null-checkout-deposit-" + str(iid)
