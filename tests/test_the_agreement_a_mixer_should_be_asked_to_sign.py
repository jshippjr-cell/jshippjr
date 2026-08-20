"""A mixer was being asked to sign a writer's agreement.

Asked live (operator, 2026-08-20): *"do i need to build out agreements for the audio
engineers and editors for them to sign?"* The answer was worse than a gap.

``db.talent_assignment_blockers`` is role-blind — it refuses every assignment without
``agreement_executed_at`` — and the only thing in the product that set that field was the
Composer Agreement. Measured on a mixer's own row before this change: 45 lines calling
them "the writer", a 30% publishing share, and clause 6A landing the duty to collect
releases from performers on someone who engaged none. Not a missing feature. The wrong
instrument, required.

So there are two standing agreements now, and the rule this file holds is that **which
one governs is decided in exactly one place** (``agreements.kind_for``). Two places
deciding is how a creator reads one document and signs the digest of the other.

The sharp edge is the third answer. A creator with no craft recorded gets **neither**
document — not the writer's "just in case", which is precisely the defect being fixed.
Evidence or nothing, applied to a contract.
"""
import importlib

import pytest

from chordential_oia import agreements, service_agreement, signing
from chordential_oia.models import MusicDiscipline
from chordential_oia.talent import Talent


def _t(name, *disciplines):
    return Talent(name=name, email=f"{name.split()[0].lower()}@example.com",
                  rate=90.0, disciplines=list(disciplines))


# ── which document governs ──────────────────────────────────────────────────────────
def test_a_mixer_gets_the_service_agreement():
    who = _t("Rae Okonkwo", MusicDiscipline.MIXING)
    assert agreements.kind_for(who) == agreements.SERVICE
    assert agreements.label_for(who) == "Service Agreement"
    assert agreements.doc_kind_for(who) == signing.DOC_SERVICE_AGREEMENT


def test_a_composer_still_gets_the_composer_agreement():
    who = _t("Ada Cheng", MusicDiscipline.COMPOSITION)
    assert agreements.kind_for(who) == agreements.COMPOSER
    assert agreements.doc_kind_for(who) == signing.DOC_COMPOSER_AGREEMENT


@pytest.mark.parametrize("discipline", [
    MusicDiscipline.COMPOSITION, MusicDiscipline.SONIC_BRANDING,
    MusicDiscipline.ARRANGEMENT,
])
def test_every_authoring_craft_gets_the_writers_agreement(discipline):
    """A sonic-branding mnemonic is the shortest composition the studio sells, and an
    arranger authors the arrangement. Both need publishing; the Service Agreement
    carries none."""
    assert agreements.kind_for(_t("X", discipline)) == agreements.COMPOSER


@pytest.mark.parametrize("discipline", [
    MusicDiscipline.MIXING, MusicDiscipline.SOUND_DESIGN,
    MusicDiscipline.SUPERVISION, MusicDiscipline.LICENSING,
])
def test_every_service_craft_gets_the_service_agreement(discipline):
    assert agreements.kind_for(_t("X", discipline)) == agreements.SERVICE


def test_someone_who_writes_and_mixes_signs_the_writers_agreement():
    """The broader instrument wins. It is the one the Clearance Certificate stands on,
    and it does not stop them being booked to mix — whereas a Service Agreement cannot
    carry a writer's publishing at all."""
    assert agreements.kind_for(
        _t("Sam Vale", MusicDiscipline.MIXING,
           MusicDiscipline.COMPOSITION)) == agreements.COMPOSER


def test_no_craft_on_the_record_is_a_gap_not_a_default():
    """The honesty rule, applied to a contract. Defaulting to the writer's agreement
    because a profile was blank is the original defect."""
    blank = _t("Nobody")
    assert agreements.kind_for(blank) == agreements.UNKNOWN
    assert agreements.build_for(blank) is None
    assert agreements.doc_kind_for(blank) is None
    assert "Add at least one discipline" in agreements.UNKNOWN_REASON


def test_the_disqualified_bucket_is_not_evidence_of_anything():
    assert agreements.kind_for(_t("X", MusicDiscipline.NON_CRAFT)) == agreements.UNKNOWN


def test_a_db_row_and_a_dataclass_read_the_same():
    """The routing runs against both — a sqlite row in the routes, a Talent in tests.
    A disagreement between them is a creator shown one document and filed under the
    other."""
    assert agreements.kind_for({"disciplines": "mixing"}) == agreements.SERVICE
    assert agreements.kind_for({"disciplines": "composition,mixing"}) == agreements.COMPOSER
    assert agreements.kind_for({"disciplines": ""}) == agreements.UNKNOWN
    assert agreements.kind_for({"disciplines": "nonsense"}) == agreements.UNKNOWN


# ── what the document actually says ─────────────────────────────────────────────────
def test_it_conveys_no_publishing_and_says_so_out_loud():
    """Silence on publishing is how a mixer with a real writing contribution ends up
    unclaimed on a cue sheet. The clause is positive, not absent."""
    text = service_agreement.build_agreement(_t("Rae Okonkwo")).signable_text()
    assert "5. NO PUBLISHING" in text
    assert "conveys no share of the composition" in text
    for word in ("publisher's share", "writer's share"):
        assert word in text, "it does not even name what it is not granting"
    assert "30%" not in text and "publishing share" not in text.split("5. NO")[0]


def test_it_leaves_the_door_open_when_they_did_write_something():
    """The honest handling of the real edge: a sound designer who invents original
    material HAS authored something. They raise it, and it is settled as authorship or
    it is not used — never quietly absorbed."""
    text = service_agreement.build_agreement(_t("Rae")).signable_text()
    assert "The exception is real and it is the contractor's to raise" in text
    assert "settles it as authorship" in text
    assert "Raising this is never a breach" in text


def test_it_grants_only_what_the_contractor_actually_made():
    """A grant of something the grantor does not hold pollutes a chain of title rather
    than completing one. This is the clause that keeps the Clearance Certificate true."""
    text = service_agreement.build_agreement(_t("Rae")).signable_text()
    assert "does not purport to grant the underlying composition" in text
    assert "the mixes, masters, edits, cutdowns, verticals" in text


def test_the_production_chain_is_a_clause_not_only_a_router():
    """ADR-0075 lives in the software. It is a promise the studio makes to a client
    about what was delivered, so it belongs in the document the person doing it signed."""
    text = service_agreement.build_agreement(_t("Rae")).signable_text()
    assert "A mix is made from the composer's approved stems." in text
    assert "made from the mix engineer's approved master" in text
    assert "never from an earlier mix" in text


def test_the_ai_warranty_forbids_generating_and_permits_the_toolchain():
    """Inverted from the writer's. A contractor's tools are full of separation and
    assistive mastering, all legitimate; what is forbidden is GENERATING material. A
    warranty that reads as banning their day job is one they sign without believing."""
    text = service_agreement.build_agreement(_t("Rae")).signable_text()
    assert "not generated any musical material" in text
    assert "source separation and stem extraction" in text
    assert "PROCESSING what a human made and GENERATING what nobody did" in text


def test_it_is_paid_whether_or_not_the_client_paid():
    from chordential_oia import composer_agreement
    text = service_agreement.build_agreement(_t("Rae")).signable_text()
    assert (f"within {composer_agreement.PAYMENT_BACKSTOP_DAYS} days of the client "
            f"accepting delivery, whether or not the client has paid") in text


def test_the_shared_terms_are_imported_not_restated():
    """Two agreements with two copies of a 120-day backstop is one agreement with a
    backstop and another with whatever it drifted to."""
    from chordential_oia import composer_agreement
    for name in ("PAYMENT_BACKSTOP_DAYS", "INVOICE_WITHIN_DAYS",
                 "ACCEPTANCE_WINDOW_DAYS", "KILL_FEE_BEFORE_DELIVERY",
                 "LIABILITY_FLOOR", "LIABILITY_FEE_MULTIPLE"):
        assert getattr(service_agreement, name) is getattr(composer_agreement, name), (
            f"{name} was re-declared in service_agreement instead of imported")
    src = (importlib.import_module("chordential_oia.service_agreement")
           .__file__)
    body = open(src, encoding="utf-8").read()
    assert "PAYMENT_BACKSTOP_DAYS = " not in body


def test_it_never_calls_a_mixer_the_writer():
    text = service_agreement.build_agreement(_t("Rae Okonkwo")).signable_text()
    body = text.split("5. NO PUBLISHING")[0] + text.split("or the material is not used.")[1]
    assert "the writer" not in body.lower().replace("from the writer", ""), (
        "the service agreement still addresses them as the writer somewhere")


def test_the_two_documents_name_the_same_court():
    from chordential_oia import composer_agreement
    a = composer_agreement.build_agreement(_t("Ada"))
    b = service_agreement.build_agreement(_t("Rae"))
    assert (a.law, a.court) == (b.law, b.court)


def test_it_is_not_signable_without_a_stated_forum():
    agr = service_agreement.build_agreement(_t("Rae"), law="", court="")
    assert not service_agreement.is_signable(agr)
    assert "governing law" in service_agreement.blocked_reason(agr)


def test_the_text_is_stable_so_a_signature_survives_the_night():
    """ADR-0059: the digest covers the exact text. A document that changed because a day
    passed would report every signature as superseded by morning."""
    a = service_agreement.build_agreement(_t("Rae")).signable_text()
    b = service_agreement.build_agreement(_t("Rae")).signable_text()
    assert a == b
    assert signing.document_digest(a) == signing.document_digest(b)


def test_the_signature_kinds_are_registered():
    assert signing.DOC_SERVICE_AGREEMENT in signing.DOC_KINDS
    assert signing.DOC_SERVICE_COUNTERSIGN in signing.DOC_KINDS
    assert signing.DOC_LABELS[signing.DOC_SERVICE_AGREEMENT] == "Service Agreement"
