"""A signature you can draw with a finger, and a price guide that says what a question costs.

Two asks, one commit. The drawn mark is a courtesy to what people EXPECT a signature to
look like — it is deliberately not the evidence, because what makes an electronic
signature binding under ESIGN/UETA is intent, consent and attribution, all of which the
typed name and the recorded consent already carry. So the mark is optional, validated
rather than trusted, and its absence never blocks a signature: a client on a browser
where the canvas fails must still be able to sign.

The price guide answers the other half. The four licence questions were already on the
prep sheet and already flagged as the ones that get dropped when a call runs long. What
the sheet could not say was what dropping them costs.
"""
import base64
import importlib
import zlib

import pytest

from chordential_oia.signing import (
    DOC_PROPOSAL, MAX_DRAWN_MARK, build_signature, clean_drawn_mark,
)

pytest.importorskip("fastapi")


def _png(width: int = 4) -> str:
    """A genuinely valid 4x4 PNG, as the canvas would produce."""
    raw = b"".join(b"\x00" + b"\xff\xff\xff" * width for _ in range(width))
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (len(data).to_bytes(4, "big") + tag + data
                + zlib.crc32(tag + data).to_bytes(4, "big"))
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", width.to_bytes(4, "big") + width.to_bytes(4, "big")
                   + bytes([8, 2, 0, 0, 0]))
           + chunk(b"IDAT", zlib.compress(raw))
           + chunk(b"IEND", b""))
    return "data:image/png;base64," + base64.b64encode(png).decode()


# ── the mark is validated, never trusted ─────────────────────────────────────────────
def test_a_real_png_from_the_pad_is_kept():
    mark = _png()
    assert clean_drawn_mark(mark) == mark


@pytest.mark.parametrize("hostile", [
    "javascript:alert(1)",
    "data:text/html;base64," + base64.b64encode(b"<script>alert(1)</script>").decode(),
    "data:image/svg+xml;base64," + base64.b64encode(b"<svg onload=alert(1)>").decode(),
    "data:image/png;base64,<script>alert(1)</script>",
    "data:image/png;base64,not!valid!base64!",
    # Correctly-encoded base64 that is NOT a PNG — the label alone must not be enough.
    "data:image/png;base64," + base64.b64encode(b"<html>hello</html>").decode(),
    "<img src=x onerror=alert(1)>",
    "",
    "   ",
])
def test_anything_that_is_not_a_png_is_dropped_not_sanitised(hostile):
    """This value arrives from a token-gated PUBLIC form and is rendered straight back
    into an <img src> for every later reader of the document. Dropping is the safe
    direction to fail, and it is safe precisely because the signature never depended on
    the drawing."""
    assert clean_drawn_mark(hostile) == ""


def test_an_enormous_mark_is_dropped():
    assert clean_drawn_mark("data:image/png;base64," + "A" * (MAX_DRAWN_MARK + 4)) == ""


def test_a_signature_stands_without_any_drawing():
    """The load-bearing property. A browser where the canvas fails, a client who cannot
    draw with a mouse, a screen reader user — all still sign."""
    sig = build_signature(doc_kind=DOC_PROPOSAL, opportunity_id=7,
                          document_text="TERMS\nFee: $10,000",
                          signer_name="Nadia Okonjo", typed_name="Nadia Okonjo")
    assert sig.drawn_mark == ""
    assert sig.digest and sig.consent_text


def test_the_drawing_is_not_part_of_what_is_signed():
    """The digest must cover the DOCUMENT and nothing else. If the mark entered it, two
    signatures on identical terms would disagree, and re-rendering a signature image
    slightly differently would read as a tampered contract."""
    common = dict(doc_kind=DOC_PROPOSAL, opportunity_id=7,
                  document_text="TERMS\nFee: $10,000",
                  signer_name="Nadia", typed_name="Nadia")
    assert (build_signature(**common, drawn_mark=_png()).digest
            == build_signature(**common).digest)


def test_a_hostile_mark_never_reaches_the_stored_signature():
    sig = build_signature(doc_kind=DOC_PROPOSAL, opportunity_id=7,
                          document_text="TERMS", signer_name="N", typed_name="N",
                          drawn_mark="data:text/html;base64,PHNjcmlwdD4=")
    assert sig.drawn_mark == ""


# ── it survives the round trip ───────────────────────────────────────────────────────
@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "sign.db"))
    monkeypatch.delenv("CHORDENTIAL_ADMIN_TOKEN", raising=False)
    for m in ("db", "campaign_intelligence", "campaigns", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod
    with TestClient(app_mod.app) as c:
        yield c, app_mod


def _signable_deal(app_mod):
    """A deal that has HAD its call, so the summary carries the proposal."""
    from chordential_oia.models import BuyerType, MusicRequirement, Opportunity
    db = app_mod.db
    conn = db.connect()
    try:
        oid = db.insert_opportunity(conn, Opportunity(
            client="The Larkspur Trust", need="Winter appeal film",
            description="Three-minute charity film with a 90-second wordless middle "
                        "section, plus a 30-second social cut.",
            buyer_type=BuyerType.BRAND, music_requirement=MusicRequirement.ORIGINAL))
        db.create_meeting(conn, opp_id=oid, start_at="2026-07-01T14:00:00+00:00",
                          status="ingested")
        return oid, db.ensure_share_token(conn, oid)
    finally:
        conn.close()


def test_the_pad_is_on_the_page_the_client_signs(client):
    c, app_mod = client
    _oid, token = _signable_deal(app_mod)
    page = c.get(f"/workspace/{token}").text
    assert 'id="sig-pad"' in page and "<canvas" in page
    assert "use your finger or mouse" in page
    assert "touch-action:none" in page, (
        "without it the page scrolls out from under a stroke, which is the failure that "
        "makes web signature pads feel broken on a phone")


def test_a_drawn_signature_is_stored_and_shown_back(client):
    c, app_mod = client
    oid, token = _signable_deal(app_mod)
    mark = _png()
    r = c.post(f"/workspace/{token}/sign",
               data={"typed_name": "Nadia Okonjo", "signer_email": "nadia@larkspur.example",
                     "consent": "1", "drawn_signature": mark},
               follow_redirects=False)
    assert r.status_code == 303
    conn = app_mod.db.connect()
    try:
        sig = app_mod.db.latest_opportunity_signature(conn, oid, DOC_PROPOSAL)
    finally:
        conn.close()
    assert sig is not None and sig["typed_name"] == "Nadia Okonjo"
    assert sig["drawn_mark"] == mark
    assert mark in c.get(f"/workspace/{token}").text, "the mark belongs ON the document"


def test_signing_without_drawing_still_signs(client):
    c, app_mod = client
    oid, token = _signable_deal(app_mod)
    c.post(f"/workspace/{token}/sign",
           data={"typed_name": "Nadia Okonjo", "signer_email": "n@l.example",
                 "consent": "1", "drawn_signature": ""}, follow_redirects=False)
    conn = app_mod.db.connect()
    try:
        sig = app_mod.db.latest_opportunity_signature(conn, oid, DOC_PROPOSAL)
    finally:
        conn.close()
    assert sig is not None and (sig["drawn_mark"] or "") == ""


def test_a_hostile_mark_posted_directly_is_not_stored(client):
    """The pad is ours; the POST is the internet's."""
    c, app_mod = client
    oid, token = _signable_deal(app_mod)
    c.post(f"/workspace/{token}/sign",
           data={"typed_name": "Nadia", "signer_email": "n@l.example", "consent": "1",
                 "drawn_signature": "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg=="},
           follow_redirects=False)
    conn = app_mod.db.connect()
    try:
        sig = app_mod.db.latest_opportunity_signature(conn, oid, DOC_PROPOSAL)
    finally:
        conn.close()
    assert sig is not None, "the signature still stands; only the drawing was refused"
    assert (sig["drawn_mark"] or "") == ""
    # The page has its own <script> tags, so assert on the PAYLOAD: neither the injected
    # call nor the data URL carrying it may appear anywhere in what a reader is served.
    page = c.get(f"/workspace/{token}").text
    assert "alert(1)" not in page
    assert "data:text/html" not in page


def test_the_operator_view_offers_no_pad(client):
    """The person who WROTE the document must not be able to sign it for the client from
    the page that composes it."""
    c, app_mod = client
    oid, _token = _signable_deal(app_mod)
    page = c.get(f"/opportunity/{oid}/capabilities").text
    assert 'id="sig-pad"' not in page
    assert "The client signs this from their workspace" in page


def test_the_operator_sees_the_signature_on_their_own_copy(client):
    """The person who has to countersign and start production could otherwise only learn
    the client had signed from an email — the document itself, the thing that WAS signed,
    said nothing."""
    c, app_mod = client
    oid, token = _signable_deal(app_mod)
    mark = _png()
    c.post(f"/workspace/{token}/sign",
           data={"typed_name": "Nadia Okonjo", "signer_email": "n@l.example",
                 "consent": "1", "drawn_signature": mark}, follow_redirects=False)
    page = c.get(f"/opportunity/{oid}/capabilities").text
    assert "Signed by Nadia Okonjo" in page
    assert mark in page
    assert "The document is unchanged since signing" in page
    assert 'id="sig-pad"' not in page, "still no form on the author's copy"


def test_both_copies_of_the_document_are_the_same_document(client):
    """The invariant under the two tests above, pinned directly.

    It was broken on the first attempt: the client's copy re-derived the agreement with
    the real deposit figure and the operator's kept the prose fallback, so the two texts
    differed and an UNTOUCHED document reported SUPERSEDED. A digest is only worth
    anything if every surface builds the same bytes — testing the rendered verdict alone
    would have let the next surface drift the same way."""
    from chordential_oia.web import opportunity_routes, workspace_routes
    from chordential_oia.signing import document_digest
    c, app_mod = client
    oid, token = _signable_deal(app_mod)
    c.get(f"/workspace/{token}"), c.get(f"/opportunity/{oid}/capabilities")
    conn = app_mod.db.connect()
    try:
        client_doc = workspace_routes._live_brief_ctx(conn, oid)["doc"]
    finally:
        conn.close()
    # The operator's text, as its route builds it — reached through the rendered page so
    # the whole route is exercised rather than a re-implementation of it here.
    page = c.get(f"/opportunity/{oid}/capabilities").text
    assert "Agreement" in page
    client_text = client_doc.agreement.signable_text()
    assert "Deposit: $" in client_text, "the client signs a document naming a real figure"
    c.post(f"/workspace/{token}/sign",
           data={"typed_name": "Nadia Okonjo", "signer_email": "n@l.example",
                 "consent": "1"}, follow_redirects=False)
    conn = app_mod.db.connect()
    try:
        sig = app_mod.db.latest_opportunity_signature(conn, oid, DOC_PROPOSAL)
    finally:
        conn.close()
    assert sig["digest"] == document_digest(client_text)
    assert "unchanged since signing" in c.get(f"/opportunity/{oid}/capabilities").text, (
        "the operator's copy hashes to something else — the two surfaces have drifted")


def test_the_operator_is_told_when_a_signed_document_has_since_changed(client):
    """SUPERSEDED is the answer the old typed-name model could not give, and the one that
    matters. Edit the summary after it is signed and the operator's copy says so rather
    than showing a signature that no longer covers anything."""
    c, app_mod = client
    oid, token = _signable_deal(app_mod)
    c.post(f"/workspace/{token}/sign",
           data={"typed_name": "Nadia Okonjo", "signer_email": "n@l.example",
                 "consent": "1"}, follow_redirects=False)
    assert "unchanged since signing" in c.get(f"/opportunity/{oid}/capabilities").text
    conn = app_mod.db.connect()
    try:
        app_mod.db.update_doc_override(
            conn, oid, "understanding",
            "Actually a six-minute film, and the fee has moved.")
    finally:
        conn.close()
    page = c.get(f"/opportunity/{oid}/capabilities").text
    assert "HAS CHANGED since" in page
    assert "covers the earlier version" in page


# ── the price guide on the prep sheet ────────────────────────────────────────────────
def test_the_prep_sheet_prices_every_licence_question(client):
    c, app_mod = client
    oid, _token = _signable_deal(app_mod)
    page = c.get(f"/opportunity/{oid}/prep").text
    assert "What each answer is worth" in page
    for question in ("Media", "Territory", "Licence term", "Exclusivity"):
        assert question in page
    assert "on this deal" in page, "the swing is the reason to ask"
    assert "Our floor is" in page


def test_the_guide_shows_what_the_market_charges(client):
    c, app_mod = client
    oid, _token = _signable_deal(app_mod)
    page = c.get(f"/opportunity/{oid}/prep").text
    assert "Swell Music + Sound" in page and "$10,000" in page
    assert "NOT calibrated on Chordential actuals" in page, (
        "priors presented as measurements is the honesty rule broken on our own numbers")


def test_the_guide_agrees_with_the_proposal():
    """One derivation, two reporters. A guide that quoted a number the proposal would not
    honour would be worse than no guide — the operator would promise it on the call."""
    from chordential_oia.estimation import build_estimate
    from chordential_oia.models import (
        BuyerType, MusicDiscipline, MusicRequirement, Opportunity,
    )
    from chordential_oia.pricing import LicenceTerms, build_quote, price_guide
    opp = Opportunity(client="X", need="Winter appeal film",
                      description="Three-minute charity film.",
                      buyer_type=BuyerType.BRAND,
                      music_requirement=MusicRequirement.ORIGINAL)
    est = build_estimate(opp, [], MusicDiscipline.COMPOSITION)
    guide = price_guide(est, LicenceTerms())
    assert guide["quote"].total == build_quote(est, LicenceTerms()).total
    for row in guide["rows"]:
        for option in row["options"]:
            if option["current"]:
                assert option["total"] == guide["quote"].total


def test_the_loudest_question_is_listed_first():
    """A sheet read while a call overruns has to put the expensive question at the top."""
    from chordential_oia.estimation import build_estimate
    from chordential_oia.models import (
        BuyerType, MusicDiscipline, MusicRequirement, Opportunity,
    )
    from chordential_oia.pricing import price_guide
    opp = Opportunity(client="X", need="Winter appeal film",
                      description="Three-minute charity film.",
                      buyer_type=BuyerType.BRAND,
                      music_requirement=MusicRequirement.ORIGINAL)
    rows = price_guide(build_estimate(opp, [], MusicDiscipline.COMPOSITION))["rows"]
    spreads = [r["spread"] for r in rows]
    assert spreads == sorted(spreads, reverse=True)
    assert rows[0]["spread"] > 0
