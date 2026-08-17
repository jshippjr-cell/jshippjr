"""After the signature lands, everything downstream has to know.

Reported live, minutes after a real client signed a real proposal:

* *"The email that comes back saying it's signed doesn't give me a copy of the signed
  document."* — it carried a fee and a truncated digest. A receipt, not a contract.
* *"Inside the dashboard, there is no signed document, and it's telling me the next step
  is to release the proposal, although we already did that step."* — the signature was
  only rendered on the Campaign Brief, and the next-action ladder had never heard of it,
  so the deal page showed an unsigned deal and pointed at a step already taken.
* *"If there is a countersign, I don't see where to do that."* — because there was
  nowhere. The acceptance text the client signs promises it in as many words, so the
  first sentence of our first binding document was one the product could not keep.
"""
import importlib

import pytest

from chordential_oia.signing import DOC_PROPOSAL, DOC_PROPOSAL_COUNTERSIGN

pytest.importorskip("fastapi")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "signed.db"))
    monkeypatch.delenv("CHORDENTIAL_ADMIN_TOKEN", raising=False)
    for m in ("db", "campaign_intelligence", "campaigns", "next_action", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod
    with TestClient(app_mod.app) as c:
        yield c, app_mod


def _deal(app_mod):
    from chordential_oia.models import BuyerType, MusicRequirement, Opportunity
    db = app_mod.db
    conn = db.connect()
    try:
        oid = db.insert_opportunity(conn, Opportunity(
            client="The Larkspur Trust", need="Three-minute fundraising film",
            description="Three-minute charity film with a 90-second wordless middle "
                        "section, plus a 30-second social cut.",
            buyer_type=BuyerType.BRAND, music_requirement=MusicRequirement.ORIGINAL))
        conn.execute("UPDATE opportunities SET contact_email=? WHERE id=?",
                     ("nadia@larkspur.example", oid))
        conn.commit()
        db.create_meeting(conn, opp_id=oid, start_at="2026-07-01T14:00:00+00:00",
                          status="ingested")
        return oid, db.ensure_share_token(conn, oid)
    finally:
        conn.close()


def _sign(c, token, name="Nadia Okonjo"):
    return c.post(f"/workspace/{token}/sign",
                  data={"typed_name": name, "signer_email": "nadia@larkspur.example",
                        "consent": "1"}, follow_redirects=False)


# ── the deal page shows what was signed ──────────────────────────────────────────────
def test_the_deal_page_shows_the_signature_and_the_document(client):
    c, app_mod = client
    oid, token = _deal(app_mod)
    assert "SIGNED" not in c.get(f"/opportunity/{oid}").text
    _sign(c, token)
    page = c.get(f"/opportunity/{oid}").text
    assert "SIGNED" in page
    assert "Nadia Okonjo" in page and "nadia@larkspur.example" in page
    assert "The signed document" in page, "the document itself must be on the page"
    assert "DISCOVERY SUMMARY &amp; PROPOSAL" in page or "DISCOVERY SUMMARY & PROPOSAL" in page
    assert "ACCEPTANCE" in page, "the text they agreed to, not a summary of it"


def test_the_next_action_stops_asking_for_a_step_already_taken(client):
    """The reported symptom exactly: 'it's telling me next step is to release the
    proposal, although we already did that step.'"""
    c, app_mod = client
    oid, token = _deal(app_mod)
    _sign(c, token)
    page = c.get(f"/opportunity/{oid}").text
    assert "Release the proposal" not in page
    assert "Countersign the agreement" in page


# ── countersigning exists, because the signed text promises it ───────────────────────
def test_the_operator_can_countersign(client):
    c, app_mod = client
    oid, token = _deal(app_mod)
    _sign(c, token)
    assert "Countersign</button>" in c.get(f"/opportunity/{oid}").text
    r = c.post(f"/opportunity/{oid}/countersign",
               data={"typed_name": "Jon Shipp", "consent": "1"}, follow_redirects=False)
    assert r.status_code == 303
    conn = app_mod.db.connect()
    try:
        cs = app_mod.db.latest_opportunity_signature(conn, oid, DOC_PROPOSAL_COUNTERSIGN)
        client_sig = app_mod.db.latest_opportunity_signature(conn, oid, DOC_PROPOSAL)
    finally:
        conn.close()
    assert cs is not None and cs["typed_name"] == "Jon Shipp"
    assert cs["digest"] == client_sig["digest"], (
        "the two parties signed different documents")
    page = c.get(f"/opportunity/{oid}").text
    assert "Countersigned" in page and "signed by both parties" in page
    # Countersigning is the award, so it spins up the project — and the next move is
    # therefore WHO, not a button. It used to say "Start production" and link to the page
    # the operator was already on: a dead Go with no project, no roles and nobody to
    # assign. Production does not begin with a button; it begins with a team.
    assert "Start production" not in page
    assert "Assign the" in page, "the board should be asking who does the work"
    conn = app_mod.db.connect()
    try:
        project = app_mod.db.project_for_opp(conn, oid)
    finally:
        conn.close()
    assert project is not None, "the award created no project"
    assert f"/project/{project['id']}" in page, "the next move must actually go somewhere"


def test_countersigning_is_impossible_before_the_client_signs(client):
    """A countersignature on a document the other party has not accepted is a note to
    self, not a contract."""
    c, app_mod = client
    oid, _token = _deal(app_mod)
    c.post(f"/opportunity/{oid}/countersign",
           data={"typed_name": "Jon Shipp", "consent": "1"}, follow_redirects=False)
    conn = app_mod.db.connect()
    try:
        assert app_mod.db.latest_opportunity_signature(
            conn, oid, DOC_PROPOSAL_COUNTERSIGN) is None
    finally:
        conn.close()


def test_countersigning_is_refused_once_the_document_has_moved(client):
    """The whole reason the digest exists. If the text changed after they signed it,
    countersigning binds US to terms THEY never saw — two parties signed to two different
    documents, which is the failure the old typed-name-in-a-blob could not even detect."""
    c, app_mod = client
    oid, token = _deal(app_mod)
    _sign(c, token)
    conn = app_mod.db.connect()
    try:
        app_mod.db.update_doc_override(
            conn, oid, "understanding", "Actually a six-minute film at twice the fee.")
    finally:
        conn.close()
    page = c.get(f"/opportunity/{oid}").text
    assert "SIGNED — DOCUMENT CHANGED" in page
    assert "Countersigning is blocked" in page
    assert "Countersign</button>" not in page, "the button must not be offered"
    c.post(f"/opportunity/{oid}/countersign",
           data={"typed_name": "Jon Shipp", "consent": "1"}, follow_redirects=False)
    conn = app_mod.db.connect()
    try:
        assert app_mod.db.latest_opportunity_signature(
            conn, oid, DOC_PROPOSAL_COUNTERSIGN) is None, (
            "we countersigned a document the client never agreed to")
    finally:
        conn.close()


# ── the emails carry the document ────────────────────────────────────────────────────
def test_both_emails_carry_the_signed_document(client, monkeypatch):
    """'The email that comes back saying it's signed doesn't give me a copy of the signed
    document.' Both parties get the text, not a receipt for it."""
    from chordential_oia import mailer
    sent = []
    monkeypatch.setenv("CHORDENTIAL_OPERATOR_EMAIL", "jon@chordential.com")
    monkeypatch.setattr(mailer, "send_email",
                        lambda to, subject, body, **kw: sent.append((to, subject, body)))
    c, app_mod = client
    _oid, token = _deal(app_mod)
    _sign(c, token)

    to_operator = [m for m in sent if m[0] == "jon@chordential.com"]
    to_signer = [m for m in sent if m[0] == "nadia@larkspur.example"]
    assert to_operator, "the operator was not told"
    assert to_signer, "the signer got no copy of what she signed (ESIGN retention)"
    for _to, _subject, body in to_operator + to_signer:
        assert "SIGNED COPY" in body
        assert "DISCOVERY SUMMARY & PROPOSAL" in body, "the document itself is missing"
        assert "ACCEPTANCE" in body and "WHAT THIS RESTS ON" in body
        assert "Nadia Okonjo" in body
        # The FULL digest, not a truncated one — a prefix cannot be checked against
        # anything, and the first email shipped `digest[:16]…`.
        assert "…" not in body.split("Document digest")[-1].splitlines()[0]
        assert len(body.split("Document digest (SHA-256): ")[1][:64].strip()) == 64


def test_the_signer_copy_is_not_sent_when_no_address_was_given(client, monkeypatch):
    """No email, no send — never a guess at where a contract should go."""
    from chordential_oia import mailer
    sent = []
    monkeypatch.delenv("CHORDENTIAL_OPERATOR_EMAIL", raising=False)
    monkeypatch.setattr(mailer, "send_email",
                        lambda to, subject, body, **kw: sent.append(to))
    c, app_mod = client
    _oid, token = _deal(app_mod)
    c.post(f"/workspace/{token}/sign",
           data={"typed_name": "Nadia Okonjo", "signer_email": "", "consent": "1"},
           follow_redirects=False)
    assert sent == []


# ── one document, every surface ──────────────────────────────────────────────────────
def test_the_client_and_the_operator_read_the_same_bytes(client):
    """The email said $12,500–$18,000 while the deal page said $14,000–$19,500 — the
    client's copy resolved its estimate WITHOUT the deal's project and the operator's
    with it. A digest is worthless if two surfaces build different text, so both now go
    through `opportunity_ops.agreement_doc_for`."""
    from chordential_oia.signing import document_digest
    from chordential_oia.web import workspace_routes
    from chordential_oia.web.opportunity_ops import agreement_doc_for
    c, app_mod = client
    oid, token = _deal(app_mod)
    _sign(c, token)
    conn = app_mod.db.connect()
    try:
        client_doc = workspace_routes._live_brief_ctx(conn, oid)["doc"]
        _r, _o, _e, operator_doc, _d = agreement_doc_for(conn, oid)
        stored = app_mod.db.latest_opportunity_signature(conn, oid, DOC_PROPOSAL)
    finally:
        conn.close()
    client_text = client_doc.agreement.signable_text()
    assert client_text == operator_doc.agreement.signable_text()
    assert stored["digest"] == document_digest(client_text)


# ── the document reads like a document, and still hashes like the document ───────────
def test_the_signed_copy_is_typeset_not_dumped(client):
    """Reported live: "the signed copy of the document came back as text." It rendered in
    a <pre> block — a contract that looks like a log file is a contract nobody trusts."""
    c, app_mod = client
    oid, token = _deal(app_mod)
    _sign(c, token)
    page = c.get(f"/opportunity/{oid}").text
    assert "<pre" not in page.split('id="agreement"')[1].split("</section>")[0], (
        "the agreement is still a monospace dump")
    assert 'class="sigdoc"' in page
    assert "<h4>SCOPE</h4>" in page and "<h4>ACCEPTANCE</h4>" in page
    assert 'class="k">Fee<' in page, "the fee is a labelled term, not a run of text"


def test_typesetting_never_touches_the_hashed_bytes(client):
    """The load-bearing half. Reformatting the STRING would change the digest and void
    every signature over it, so the transformation has to be presentational only."""
    from chordential_oia.signing import document_digest
    from chordential_oia.web.opportunity_ops import agreement_doc_for
    c, app_mod = client
    oid, token = _deal(app_mod)
    _sign(c, token)
    conn = app_mod.db.connect()
    try:
        before = app_mod.db.latest_opportunity_signature(conn, oid, DOC_PROPOSAL)["digest"]
        _r, _o, _e, doc, _d = agreement_doc_for(conn, oid)
    finally:
        conn.close()
    assert document_digest(doc.agreement.signable_text()) == before
    page = c.get(f"/opportunity/{oid}").text
    assert "SIGNED — DOCUMENT CHANGED" not in page
    assert before in page, "the page shows a digest that is not the stored one"


# ── what a client signs is not the extractor's notes ─────────────────────────────────
def _ci(app_mod, oid, **fields):
    from chordential_oia.web import campaign_intelligence as ci_mod
    conn = app_mod.db.connect()
    try:
        row = app_mod.db.get_opportunity(conn, oid)
        cid = ci_mod.ensure_for_opportunity(conn, row)["id"]
        for key, value in fields.items():
            ci_mod.edit_or_create(conn, cid, "engagement", key, "fact", value,
                                  actor="operator")
    finally:
        conn.close()


def test_the_machines_own_narration_never_becomes_a_contract_term(client):
    """A live signed proposal carried, as its SCOPE line:

        Scope: Deliverables mentioned: three-minute master film, … (needs clarified).

    "Deliverables mentioned:" is the extractor narrating itself. "(needs clarified)" is
    the machine saying it is NOT sure — printed as a settled term in the document where
    an unconfirmed item costs the most.
    """
    c, app_mod = client
    oid, token = _deal(app_mod)
    _ci(app_mod, oid,
        deliverables="Deliverables mentioned: three-minute master film, 30-second social "
                     "cutdown, and a live-event playback version (needs clarified).",
        deadline="Final delivery needed two weeks before the November 3rd launch.")
    from chordential_oia.web.opportunity_ops import agreement_doc_for
    conn = app_mod.db.connect()
    try:
        _r, _o, _e, doc, _d = agreement_doc_for(conn, oid)
    finally:
        conn.close()
    text = doc.agreement.signable_text()
    assert "Deliverables mentioned:" not in text
    assert "needs clarified" not in text
    assert "three-minute master film" in text, "the actual scope survived the cleaning"
    # Removed from the term, RETURNED as a caveat — never silently dropped, because that
    # turns a guess into a fact (ADR-0058).
    assert "not finalised" in text and "WHAT THIS RESTS ON" in text


def test_a_captured_sentence_is_folded_in_without_mangling_it(client):
    """The live document read "Working back from Final delivery needed two weeks before
    the November 3rd launch, i.e. mid-October.." — a mid-sentence capital and a doubled
    period, on a contract line."""
    c, app_mod = client
    oid, _token = _deal(app_mod)
    _ci(app_mod, oid,
        deadline="Final delivery needed two weeks before the November 3rd launch, "
                 "i.e. mid-October.")
    from chordential_oia.web.opportunity_ops import agreement_doc_for
    conn = app_mod.db.connect()
    try:
        _r, _o, _e, doc, _d = agreement_doc_for(conn, oid)
    finally:
        conn.close()
    completion = [ln for ln in doc.agreement.signable_text().splitlines()
                  if ln.startswith("Completion:")][0]
    assert ".." not in completion
    assert "from Final delivery" not in completion, "mid-sentence capital survived"
    assert "from final delivery" in completion
    assert completion.rstrip().endswith(".")
