"""Tests for the email-alert intake parser."""

from pathlib import Path

from chordential_oia.intake import (
    detect_provider,
    parse_alert_email,
    parse_email_path,
)
from chordential_oia.models import BuyerType, MusicRequirement
from chordential_oia.qualification import QualificationEngine, QualificationAction

SAMPLES = Path(__file__).resolve().parent.parent / "samples"

_MANDY = """From: alerts@mandy.com
Subject: New jobs matching "composer"

------------------------------------------------------------
Title: Composer for Original Score - National Ad Campaign
Company: Northbeam Creative (agency)
Location: Miami, FL
Budget: $8,000 - $15,000

Agency needs original campaign music with cutdowns. Original composition required.
------------------------------------------------------------
Title: Wedding Cover Band Wanted for Reception
Company: Private Client
Location: Orlando, FL
Budget: $2,000

Looking for a cover band to play popular hits live at a reception.
------------------------------------------------------------
Unsubscribe | Manage alerts
"""


def test_parses_two_postings():
    opps = parse_alert_email(_MANDY)
    assert len(opps) == 2


def test_provider_detection_and_provenance():
    assert detect_provider(_MANDY) == "Mandy Network"
    opps = parse_alert_email(_MANDY)
    assert all(o.source == "Mandy Network" for o in opps)


def test_extracts_fields_from_first_posting():
    first = parse_alert_email(_MANDY)[0]
    assert "Composer" in first.need
    assert first.client == "Northbeam Creative (agency)"
    assert first.buyer_type is BuyerType.AGENCY
    assert first.music_requirement is MusicRequirement.ORIGINAL
    assert first.budget_min == 8_000 and first.budget_max == 15_000
    assert first.location == "Miami, FL"


def test_email_headers_and_footer_stripped():
    # The "From:" header and "Unsubscribe" footer must not become postings.
    needs = [o.need.lower() for o in parse_alert_email(_MANDY)]
    assert not any("unsubscribe" in n for n in needs)
    assert not any(n.startswith("from") for n in needs)


def test_money_parsing_variants():
    raw = """----
Title: Sonic logo for launch
Company: Brandco
Rate: $20k
----"""
    opp = parse_alert_email(raw)[0]
    assert opp.budget_min == 20_000


def test_end_to_end_alert_to_qualification():
    # The whole point: an alert email -> qualified verdicts.
    opps = parse_alert_email(_MANDY)
    eng = QualificationEngine()
    results = {o.need: eng.qualify(o) for o in opps}
    # The agency original-score job qualifies and is pursued.
    agency = next(r for n, r in results.items() if "Composer" in n)
    assert agency.qualified is True
    assert agency.recommended_action is QualificationAction.PURSUE
    # The cover band is hard-disqualified.
    band = next(r for n, r in results.items() if "Cover Band" in n)
    assert band.qualified is False
    assert band.recommended_action is QualificationAction.PASS


def test_sample_files_parse():
    for name in ("mandy_alert.txt", "productionhub_alert.txt"):
        opps = parse_email_path(str(SAMPLES / name))
        assert len(opps) == 2


def test_parse_directory():
    opps = parse_email_path(str(SAMPLES))
    # 2 sample files x 2 postings each.
    assert len(opps) >= 4
