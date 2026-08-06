"""A signature is a binding between a person, an intent, and an exact document.

What the product called a sign-off, before this::

    {"asset": "Master v3 FINAL", "approver": "Dana Whitfield, Aurora",
     "date": "2026-08-06"}

Reproduced on seeded data: a client signs off, the operator then changes the licence
from perpetual / worldwide / exclusive to **one year, US only, non-exclusive**, and the
approval record is byte-for-byte identical. It survives a change to the very terms it
was a sign-off on, because it never referred to them. Nothing said WHAT was signed and
nothing but a typed string said WHO signed.

`test_a_signature_notices_the_document_changing_under_it` is the whole point. The rest
guard the ways a signature can quietly become decoration: an unverifiable signer, a
consent nobody gave, an editable record, a digest that drifts on its own.
"""

import importlib

import pytest

from chordential_oia import signing
from chordential_oia.web import db as db_mod

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

DOC = "CLEARANCE CERTIFICATE\nTerm: perpetual\nTerritory: worldwide"


# --------------------------------------------------------------------------- #
# The engine
# --------------------------------------------------------------------------- #
def test_a_signature_notices_the_document_changing_under_it():
    """The defect, closed. The old record could not tell these two apart."""
    sig = signing.build_signature(
        doc_kind=signing.DOC_CLEARANCE, project_id=1, document_text=DOC,
        signer_name="Dana Whitfield", typed_name="Dana Whitfield")
    assert signing.verify(sig.digest, DOC) == signing.VALID
    changed = DOC.replace("perpetual", "1 year").replace("worldwide", "US only")
    assert signing.verify(sig.digest, changed) == signing.SUPERSEDED


def test_a_superseded_signature_says_so_in_words():
    """A state nobody renders is a state nobody acts on."""
    sig = signing.build_signature(
        doc_kind=signing.DOC_CLEARANCE, project_id=1, document_text=DOC,
        signer_name="Dana Whitfield", typed_name="Dana Whitfield")
    note = signing.verdict_note(signing.SUPERSEDED, sig.__dict__)
    assert "HAS CHANGED" in note and "Dana Whitfield" in note


def test_line_endings_do_not_count_as_tampering():
    """A document that round-trips through a browser must not read as tampered
    because a CRLF appeared. Nothing else is normalised — a changed word is a
    changed document."""
    sig = signing.build_signature(
        doc_kind=signing.DOC_CLEARANCE, project_id=1, document_text=DOC,
        signer_name="D", typed_name="D")
    assert signing.verify(sig.digest, DOC.replace("\n", "\r\n")) == signing.VALID
    assert signing.verify(sig.digest, DOC + "   \n") == signing.VALID
    assert signing.verify(sig.digest, DOC + "\nExclusivity: none") == signing.SUPERSEDED


def test_it_refuses_to_sign_nothing():
    """Both refusals produce a record that would LOOK like a signature and mean
    nothing, which is worse than having none."""
    with pytest.raises(ValueError):
        signing.build_signature(doc_kind=signing.DOC_CLEARANCE, project_id=1,
                                document_text="   ", signer_name="D", typed_name="D")
    with pytest.raises(ValueError):
        signing.build_signature(doc_kind=signing.DOC_CLEARANCE, project_id=1,
                                document_text=DOC, signer_name="D", typed_name="  ")


def test_the_consent_is_stored_verbatim_not_by_reference():
    """A consent you have to look up elsewhere to interpret is a consent you cannot
    produce in a dispute two years later."""
    sig = signing.build_signature(
        doc_kind=signing.DOC_CLEARANCE, project_id=1, document_text=DOC,
        signer_name="D", typed_name="D")
    assert "legally binding" in sig.consent_text
    assert sig.consent_text == signing.CONSENT_TEXT


def test_the_signers_address_is_fingerprinted_not_stored():
    """Enough to show two signatures came from one place; not enough to turn the
    delivery database into a log of clients' home addresses."""
    sig = signing.build_signature(
        doc_kind=signing.DOC_CLEARANCE, project_id=1, document_text=DOC,
        signer_name="D", typed_name="D", ip="203.0.113.42")
    assert "203.0.113.42" not in sig.to_json()
    assert len(sig.ip_fingerprint) == 12
    same = signing.build_signature(
        doc_kind=signing.DOC_CLEARANCE, project_id=1, document_text=DOC,
        signer_name="D", typed_name="D", ip="203.0.113.42")
    assert same.ip_fingerprint == sig.ip_fingerprint


def test_the_typed_mark_is_kept_beside_the_real_name_not_instead_of_it():
    """A mismatch between who they are and what they typed is a fact a dispute would
    care about. Collapsing the two destroys it."""
    sig = signing.build_signature(
        doc_kind=signing.DOC_CLEARANCE, project_id=1, document_text=DOC,
        signer_name="Dana Whitfield", signer_email="Dana@Aurora.com",
        typed_name="D. Whitfield")
    assert sig.signer_name == "Dana Whitfield" and sig.typed_name == "D. Whitfield"
    assert sig.signer_email == "dana@aurora.com", "the email was not normalised"


# --------------------------------------------------------------------------- #
# The certificate's signable text
# --------------------------------------------------------------------------- #
def test_the_certified_date_is_not_part_of_the_document():
    """The date is stamped at render time. If it were in the digest, every signature
    would report itself superseded by tomorrow."""
    from chordential_oia.delivery import build_clearance_certificate
    proj = {"client": "Aurora", "need": "Winter campaign"}
    a = build_clearance_certificate(proj, [], {}, certified_date="2026-01-01",
                                    certified_version="v3 FINAL")
    b = build_clearance_certificate(proj, [], {}, certified_date="2027-09-09",
                                    certified_version="v3 FINAL")
    assert signing.document_digest(a.signable_text()) == \
        signing.document_digest(b.signable_text())


def test_every_operative_term_is_inside_the_document():
    """If a term is not in the signed text, changing it is undetectable — which is
    exactly the old bug, one level down."""
    from chordential_oia.delivery import build_clearance_certificate
    cert = build_clearance_certificate(
        {"client": "Aurora", "need": "Winter campaign"}, [],
        {"term": "perpetual", "territory": "worldwide", "exclusivity": "exclusive"},
        certified_version="v3 FINAL")
    text = cert.signable_text()
    for term in ("perpetual", "worldwide", "exclusive", "Aurora", "Winter campaign",
                 "v3 FINAL"):
        assert term in text, term


# --------------------------------------------------------------------------- #
# Storage — append-only evidence
# --------------------------------------------------------------------------- #
@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "sig.db"))
    importlib.reload(db_mod)
    c = db_mod.connect()
    db_mod.init_db(c)
    yield c
    c.close()


def _sig(pid=1, text=DOC):
    return signing.build_signature(
        doc_kind=signing.DOC_CLEARANCE, project_id=pid, document_text=text,
        signer_name="Dana Whitfield", signer_email="dana@aurora.com",
        typed_name="Dana Whitfield", certified_version="v3 FINAL",
        terms_snapshot={"term": "perpetual"})


def test_a_signature_round_trips(conn):
    sid = db_mod.record_signature(conn, _sig())
    row = db_mod.latest_signature(conn, 1, signing.DOC_CLEARANCE)
    assert row["id"] == sid
    assert row["signer_name"] == "Dana Whitfield"
    assert signing.verify(row["digest"], DOC) == signing.VALID


def test_voiding_keeps_the_row(conn):
    """That a document was signed and the signature later withdrawn, by whom and why,
    is itself the record. Deleting it is the easy implementation and the wrong one."""
    sid = db_mod.record_signature(conn, _sig())
    assert db_mod.void_signature(conn, sid, by="Jon Shipp", reason="terms reissued")
    assert db_mod.latest_signature(conn, 1, signing.DOC_CLEARANCE) is None
    kept = db_mod.list_signatures(conn, 1)
    assert len(kept) == 1 and kept[0]["voided_by"] == "Jon Shipp"
    assert kept[0]["void_reason"] == "terms reissued"


def test_a_signature_cannot_be_voided_twice_with_a_different_story(conn):
    """Otherwise the audit trail is rewritable by voiding again."""
    sid = db_mod.record_signature(conn, _sig())
    assert db_mod.void_signature(conn, sid, by="Jon", reason="first reason")
    assert not db_mod.void_signature(conn, sid, by="Someone", reason="different reason")
    assert db_mod.list_signatures(conn, 1)[0]["void_reason"] == "first reason"


def test_re_signing_after_a_change_supersedes_without_erasing(conn):
    """The history is the value: both signatures stay, and the one in force is the
    newest un-voided one."""
    db_mod.record_signature(conn, _sig())
    changed = DOC.replace("perpetual", "1 year")
    db_mod.record_signature(conn, _sig(text=changed))
    assert len(db_mod.list_signatures(conn, 1)) == 2
    assert signing.verify(
        db_mod.latest_signature(conn, 1, signing.DOC_CLEARANCE)["digest"],
        changed) == signing.VALID


# --------------------------------------------------------------------------- #
# The provider seam
# --------------------------------------------------------------------------- #
def test_the_default_provider_signs_here_and_is_not_a_stub():
    from chordential_oia.signing_providers import get_signature_provider
    p = get_signature_provider()
    assert p.name == "inhouse" and p.remote is False
    assert p.request_signature(project_id=1, doc_kind=signing.DOC_CLEARANCE,
                               document_text=DOC, signer_name="D",
                               signer_email="") is None


def test_an_unknown_provider_fails_loudly_rather_than_signing_it_ourselves(monkeypatch):
    """Falling back would sign documents in-house under a configuration that asked
    for a third-party witness — the one direction a signature must never fail."""
    import chordential_oia.signing_providers as sp
    monkeypatch.setenv(sp.PROVIDER_ENV, "docusign")
    with pytest.raises(RuntimeError, match="not an available signature provider"):
        sp.get_signature_provider()


# --------------------------------------------------------------------------- #
# The routes
# --------------------------------------------------------------------------- #
@pytest.fixture()
def app_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "r.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    monkeypatch.delenv("CHORDENTIAL_ADMIN_TOKEN", raising=False)
    importlib.reload(db_mod)
    from chordential_oia.web import app as mod
    importlib.reload(mod)
    with TestClient(mod.app):        # boot once: creates the schema and seeds
        pass
    return mod


def _signable_project(conn):
    """A project whose licence is confirmed (signing a draft is refused) with one
    verified reviewer on the roster."""
    pid = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
    db_mod.update_delivery(conn, pid, "license_confirmed",
                           {"by": "Jon Shipp", "date": "2026-08-01"})
    db_mod.update_delivery(conn, pid, "reviewers", [
        {"token": "rev-token-abc", "name": "Dana Whitfield",
         "email": "dana@aurora.com", "role": "Business affairs"}])
    return pid


def test_a_verified_reviewer_can_sign_and_it_binds(app_mod):
    conn = db_mod.connect()
    pid = _signable_project(conn)
    conn.close()
    with TestClient(app_mod.app) as c:
        # Sign with a DIFFERENT typed mark from the roster name on purpose: if the
        # record came back saying "Someone Else", the signer identity was taken from
        # the form, which is the thing that makes a signature worthless.
        r = c.post(f"/project/{pid}/delivery/sign",
                   data={"typed_name": "Someone Else", "consent": "1",
                         "r": "rev-token-abc"}, follow_redirects=False)
        assert r.status_code == 303, r.text[:300]
    conn = db_mod.connect()
    row = db_mod.latest_signature(conn, pid, signing.DOC_CLEARANCE)
    conn.close()
    assert row is not None
    assert row["signer_name"] == "Dana Whitfield", "identity came from the form, not the roster"
    assert row["signer_email"] == "dana@aurora.com"
    assert row["typed_name"] == "Someone Else", "the mark they actually made was lost"
    assert row["digest"]


def test_the_generic_share_link_can_read_but_not_sign(app_mod):
    """The product already draws this line for Approve (ADR-0020). Signing is the
    stronger act, so it cannot be the weaker gate — a signature whose signer is
    whatever name the browser typed proves nothing."""
    conn = db_mod.connect()
    pid = _signable_project(conn)
    conn.close()
    with TestClient(app_mod.app) as c:
        r = c.post(f"/project/{pid}/delivery/sign",
                   data={"typed_name": "Anyone At All", "consent": "1", "r": ""},
                   follow_redirects=False)
        assert r.status_code == 403


def test_consent_must_be_given_not_assumed(app_mod):
    """A pre-ticked box is not agreement, so the form ships it unticked and the route
    refuses without it."""
    conn = db_mod.connect()
    pid = _signable_project(conn)
    conn.close()
    with TestClient(app_mod.app) as c:
        r = c.post(f"/project/{pid}/delivery/sign",
                   data={"typed_name": "Dana Whitfield", "r": "rev-token-abc"},
                   follow_redirects=False)
        assert r.status_code == 400


def test_the_console_reports_a_signature_that_stopped_matching(app_mod):
    """End to end, and the reason the whole thing exists: the operator changes a term
    after the client signed, and both surfaces say so."""
    conn = db_mod.connect()
    pid = _signable_project(conn)
    conn.close()
    with TestClient(app_mod.app) as c:
        c.post(f"/project/{pid}/delivery/sign",
               data={"typed_name": "Dana Whitfield", "consent": "1",
                     "r": "rev-token-abc"}, follow_redirects=False)
        assert "Certificate signed" in c.get(f"/project/{pid}/delivery").text

        conn = db_mod.connect()
        db_mod.update_delivery(conn, pid, "license",
                               {"term": "1 year", "territory": "US only",
                                "exclusivity": "Non-exclusive"})
        conn.close()

        console = c.get(f"/project/{pid}/delivery").text
        assert "The signed certificate has changed" in console

        conn = db_mod.connect()
        tok = db_mod.ensure_project_share_token(conn, pid)
        conn.close()
        portal = c.get(f"/project/{pid}/delivery-portal?k={tok}&r=rev-token-abc").text
        assert "Signature no longer matches" in portal


def test_signing_is_reachable_without_the_admin_gate(tmp_path, monkeypatch):
    """The client is not an admin. The route's own check (a verified ?r= token) is
    the control, and it is stricter than the gate would be."""
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "g.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "the-passphrase")
    importlib.reload(db_mod)
    from chordential_oia.web import app as mod
    importlib.reload(mod)
    with TestClient(mod.app) as c:
        conn = db_mod.connect()
        pid = _signable_project(conn)
        conn.close()
        r = c.post(f"/project/{pid}/delivery/sign",
                   data={"typed_name": "Dana Whitfield", "consent": "1",
                         "r": "rev-token-abc"}, follow_redirects=False)
        assert r.status_code == 303, "the admin gate blocked the client from signing"


def test_voiding_a_signature_is_owner_only():
    """Withdrawing a client's signature is irreversible and legal."""
    from chordential_oia.web import roles
    assert roles.required_for(
        "POST", "/project/7/delivery/signature/3/void") == roles.OWNER
