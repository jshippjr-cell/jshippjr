"""One rights basis, stated consistently everywhere.

The launch review found the package asserting three mutually exclusive positions at
once: a licence typed "Full buyout / work-made-for-hire", a cue sheet filing
Chordential as 100% publisher, and a category-exclusivity clause. Under
work-made-for-hire the *client* is the author and owns the publishing, so we could
not also collect a publisher share; and you cannot grant exclusivity on something
you no longer own. The licence also had no `media` field at all, while the sales
copy promised "all campaign media" — the certificate could not record the scope
being sold.

Ratified (ADR-0032): the client buys the **recording** outright plus a perpetual
sync licence across every campaign medium; the **composition's publishing stays
with Chordential**, which is what makes the cue sheet coherent.
"""

import pytest

from chordential_oia.capabilities import _RIGHTS_SUMMARY
from chordential_oia.delivery import (
    DEFAULT_LICENSE, PUBLISHER, build_clearance_certificate, build_cue_sheet,
    merge_license, rights_certificate_text,
)

PROJECT = {"need": "Original :30 brand spot", "client": "Vance Athletic", "description": ""}
CREW = [{"role": "Composer", "talent_name": "Maya Chen", "talent_pro": "ASCAP"}]


def test_the_licence_does_not_claim_work_made_for_hire():
    """WFH assigns authorship — and with it the publishing — to the client. We
    retain the publishing, so claiming WFH contradicts the cue sheet we file."""
    kind = DEFAULT_LICENSE["type"].lower()
    assert "work-made-for-hire" not in kind
    assert "work made for hire" not in kind
    assert "full buyout" not in kind, (
        "an unqualified 'full buyout' reads as including the publishing")


def test_the_licence_states_where_the_publishing_sits():
    """The contradiction survived because publishing was never stated. It is the
    one term that decides whether the cue sheet is coherent."""
    assert "publishing" in DEFAULT_LICENSE
    assert "retained" in DEFAULT_LICENSE["publishing"].lower()


def test_the_licence_has_a_media_dimension():
    """Media is one of the canonical licence dimensions and the sales copy already
    promised it; the grant had nowhere to record it."""
    assert DEFAULT_LICENSE.get("media"), "no media scope on the grant"
    for medium in ("broadcast", "digital", "social"):
        assert medium in DEFAULT_LICENSE["media"].lower()


def test_retained_publishing_and_the_cue_sheet_agree():
    """The two halves that used to contradict each other, checked together."""
    assert "retained" in DEFAULT_LICENSE["publishing"].lower()
    row = build_cue_sheet(PROJECT, CREW)[0]
    assert row.publisher == PUBLISHER, (
        "the licence retains publishing but the cue sheet files someone else")
    assert row.publisher_share == "100%"


def test_exclusivity_is_coherent_with_the_basis():
    """Exclusivity only means something while we still hold rights to grant. It is
    meaningful under a retained-publishing licence — and was not under a buyout."""
    assert DEFAULT_LICENSE["exclusivity"]
    assert "retained" in DEFAULT_LICENSE["publishing"].lower()


def test_the_certificate_prints_publishing_and_media():
    cert = build_clearance_certificate(
        PROJECT, CREW, {}, license_confirmed={"by": "Jon", "date": "2026-08-04"})
    text = rights_certificate_text(cert)
    grant = text.split("GRANT OF RIGHTS")[1].split("CLEARANCE")[0]
    assert "Publishing:" in grant
    assert "Media:" in grant
    for label in ("Type:", "Territory:", "Term:", "Exclusivity:"):
        assert label in grant


def test_a_per_deal_override_still_wins():
    """Nothing here removes the operator's ability to sell a different structure —
    it changes the default, and the default has to be internally consistent."""
    merged = merge_license({"media": "Broadcast only", "term": "1 year"})
    assert merged["media"] == "Broadcast only"
    assert merged["term"] == "1 year"
    assert merged["publishing"] == DEFAULT_LICENSE["publishing"]


def test_the_sales_copy_promises_what_the_certificate_delivers():
    """The review's finding was that the sale and the paperwork disagreed. The
    marketing may not promise the publishing it does not convey."""
    joined = " ".join(_RIGHTS_SUMMARY).lower()
    assert "work-made-for-hire" not in joined
    assert "publishing retained" in joined, (
        "the sale must say the publishing stays with us")
    assert "media" in joined
    # "no PRO surprises" sat beside a cue sheet we file with a PRO.
    assert "pro surprises" not in joined


def test_the_client_portal_shows_the_whole_grant():
    """The portal is where a buyer's business-affairs reviewer actually reads the
    terms. Publishing and Media were the two the grant left unstated — and leaving
    publishing unstated is precisely how the contradiction survived."""
    from pathlib import Path
    from chordential_oia.web import app as app_mod

    # The certificate moved into a PARTIAL (2026-08-30) so the room and the portal render
    # ONE copy — *"move the reviewer clearance signature into the room too"* (operator).
    # The guard is unchanged in substance: every term of the grant is on the page a buyer
    # reads. It is now on both of them, which is what the partial is for.
    tpl = Path(app_mod.__file__).parent / "templates"
    card = (tpl / "_clearance_card.html").read_text()
    for term in ("cert.license.type", "cert.license.publishing", "cert.license.media",
                 "cert.license.territory", "cert.license.term",
                 "cert.license.exclusivity"):
        assert term in card, f"the certificate does not show {term}"
    for surface in ("delivery_portal.html", "creator_portal.html"):
        assert "_clearance_card.html" in (tpl / surface).read_text(), (
            f"{surface} stopped rendering the grant")
