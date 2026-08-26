"""The price is what the work costs and what the use is worth — not what they said.

Reported live: *"I have no idea how I am pricing the product. The proposal generated a
price based on what the client told me their budget was, which is a name-your-price on
my service."*

Measured on the Larkspur film before this module existed: cost to deliver $4,062–$8,435,
and the quote was $6,000 to a client who said $6,000 and $90,000 to a client who said
$90,000. Two real engines — a cost model and a set of market priors — sat underneath and
reached nobody.

These tests pin the two properties that make a price a price: it never falls below what
the work costs, and it moves with the LICENCE rather than with what the buyer admitted
to having.
"""
import pytest

from chordential_oia.estimation import build_estimate
from chordential_oia.models import (
    BuyerType, MusicDiscipline, MusicRequirement, Opportunity,
)
from chordential_oia.pricing import (
    ABOVE_BAND, BELOW_FLOOR, IN_BAND, MIN_MARGIN, NO_BUDGET, LicenceTerms,
    build_quote, derivation, licence_from_ci,
)

FILM = ("Three-minute charity film with a 90-second wordless middle section, "
        "plus a 30-second social cut.")


def _estimate(desc=FILM):
    opp = Opportunity(client="The Larkspur Trust", need="Winter appeal film",
                      description=desc, buyer_type=BuyerType.BRAND,
                      music_requirement=MusicRequirement.ORIGINAL)
    return build_estimate(opp, [], MusicDiscipline.COMPOSITION)


# ── the budget is a check, never the answer ──────────────────────────────────────────
@pytest.mark.parametrize("said", ["$6,000 for music", "$90,000 appeal budget",
                                  "$250,000", "we have about 40k"])
def test_what_the_client_said_never_sets_the_price(said):
    """The whole bug in one assertion. Four buyers, one job, one price."""
    est = _estimate()
    quotes = [build_quote(est, LicenceTerms(), budget_band=b)
              for b in (said, "")]
    assert quotes[0].total == quotes[1].total, (
        "the stated budget changed the quote — that is name-your-price")


def test_a_budget_below_the_floor_is_flagged_not_quoted():
    q = build_quote(_estimate(), LicenceTerms(), budget_band="$6,000 for music")
    assert q.budget_verdict == BELOW_FLOOR
    assert q.total >= q.floor, "we must never quote below what the work costs"
    assert "$6,000" in q.budget_note and f"${q.floor:,}" in q.budget_note, (
        "the operator needs both numbers to decide, not an adjective")
    assert "Reduce the scope" in q.budget_note or "decline" in q.budget_note


def test_a_generous_budget_does_not_become_the_price():
    """Money currently left on the table: a client who names a big number gets quoted
    that number, so the work is priced by their generosity rather than by its worth."""
    q = build_quote(_estimate(), LicenceTerms(), budget_band="$250,000")
    assert q.budget_verdict == ABOVE_BAND
    assert q.total < 100_000, "we quoted their number back at them"
    assert "Quote the work, not their number" in q.budget_note


def test_a_budget_inside_the_band_says_so_plainly():
    est = _estimate()
    mid = build_quote(est, LicenceTerms()).total
    q = build_quote(est, LicenceTerms(), budget_band=f"${mid:,}")
    assert q.budget_verdict == IN_BAND
    assert q.stated_budget == mid


def test_no_budget_is_not_a_failure():
    q = build_quote(_estimate(), LicenceTerms())
    assert q.budget_verdict == NO_BUDGET
    assert q.total > 0 and "No budget stated" in q.budget_note


@pytest.mark.parametrize("text,expected", [
    ("a 90 second middle section", None),      # a runtime is not a budget
    ("two cues", None),                        # nor is a count
    ("6k for music", 6_000),
    ("$1.2m campaign", 1_200_000),
])
def test_only_money_is_read_as_money(text, expected):
    """The live failure this guards: a production budget and a spot length both look
    like integers, and reading either as the fee is how $900,000 landed in a budget
    slot once already."""
    q = build_quote(_estimate(), LicenceTerms(), budget_band=text)
    assert q.stated_budget == expected


# ── the licence is the lever ─────────────────────────────────────────────────────────
def test_the_licence_moves_the_price_and_the_creative_fee_does_not():
    """The property that makes this model right for music: a ninety-second cue costs the
    same to write whether it runs once on YouTube or for ever on national television."""
    est = _estimate()
    small = build_quote(est, LicenceTerms(media="digital", territory="local",
                                          term_years=1, exclusivity="none"))
    large = build_quote(est, LicenceTerms(media="all_media_cinema", territory="global",
                                          term_years=None, exclusivity="full"))
    assert abs(large.creative_fee - small.creative_fee) < small.creative_fee * 0.35, (
        "the creative fee should barely move — the work is identical")
    assert large.licence_fee > small.licence_fee * 5, (
        "the licence is where the value is; if it barely moves it is not priced")
    assert large.total > small.total


@pytest.mark.parametrize("field,cheap,dear", [
    ("media", "social", "all_media_cinema"),
    ("territory", "local", "global"),
    ("exclusivity", "none", "full"),
])
def test_every_licence_input_is_priced(field, cheap, dear):
    """Each one is a question the prep sheet already asks out loud, and whose own
    rationale already promises it is priced. Until now the answers were notes."""
    est = _estimate()
    lo = build_quote(est, LicenceTerms(**{field: cheap}))
    hi = build_quote(est, LicenceTerms(**{field: dear}))
    assert hi.licence_fee > lo.licence_fee, f"{field} does not move the fee"


def test_a_longer_term_costs_more_and_perpetual_costs_most():
    est = _estimate()
    fees = [build_quote(est, LicenceTerms(term_years=t)).licence_fee
            for t in (1, 3, 5, 10)]
    assert fees == sorted(fees) and fees[0] < fees[-1]
    assert build_quote(est, LicenceTerms(term_years=None)).licence_fee > fees[-1], (
        "'perpetual' assumed is a fee given away — the prep sheet says so in as many words")


# ── the floor holds ──────────────────────────────────────────────────────────────────
def test_the_floor_is_built_on_the_high_end_of_the_cost_band():
    """A floor that only holds when the job goes well is not a floor."""
    est = _estimate()
    q = build_quote(est, LicenceTerms())
    assert q.floor >= est.cost_high / (1.0 - MIN_MARGIN) - 500


def test_the_cheapest_possible_licence_still_pays_for_the_work():
    est = _estimate()
    q = build_quote(est, LicenceTerms(media="social", territory="local",
                                      term_years=1, exclusivity="none"))
    assert q.total >= q.floor
    if q.floored:
        assert any("minimum for this scope" in a for a in q.assumptions), (
            "when the floor binds, the document has to say why")


def test_the_usage_multiplier_is_not_applied_twice():
    """`estimate.suggested_price` already folds a usage factor into the CREATIVE number —
    measured on this film it is 0.75, so the estimator's price sits 25% below plain
    cost-plus. Reaching for it here would charge for usage once inside the fee and again
    in the licence line: a double-count nobody notices until a client adds it up.

    So the creative fee is cost at target margin and nothing else, and the licence is the
    only place usage is priced."""
    from chordential_oia.estimation import TARGET_MARGIN
    est = _estimate()
    q = build_quote(est, LicenceTerms())
    expected = est.estimated_cost / (1.0 - TARGET_MARGIN)
    # 5%, because the creative line also absorbs the rounding drift between the two
    # itemised lines and the total. The error being guarded is 25%, so the tolerance is
    # nowhere near wide enough to swallow it.
    assert abs(q.creative_fee - expected) / expected < 0.05, (
        f"creative fee ${q.creative_fee:,} is not cost at target margin (${expected:,.0f})")
    # Guard the trap directly: on this deal the estimator's own price differs by a
    # quarter, so if a later refactor reached for it the fee would silently drop.
    assert abs(est.suggested_price - expected) / expected > 0.10, (
        "fixture no longer exercises the double-count — pick a deal whose usage factor "
        "is not 1.0, or this test proves nothing")
    assert q.creative_fee != int(est.suggested_price)


# ── evidence travels with the number (ADR-0058) ──────────────────────────────────────
def test_an_assumed_licence_says_so_on_the_document():
    q = build_quote(_estimate(), LicenceTerms())          # nothing stated
    assert q.assumptions, "a licence nobody confirmed must not read as a fact"
    note = q.assumptions[0]
    for word in ("media", "territory", "licence term", "exclusivity"):
        assert word in note
    assert "not stated in the brief" in note


def test_a_fully_stated_licence_claims_no_assumption():
    licence = licence_from_ci({
        "territory": "worldwide", "license_term": "3 years",
        "exclusivity": "non-exclusive", "media": "broadcast and digital"})
    assert licence.assumed == []
    assert not build_quote(_estimate(), licence).assumptions


@pytest.mark.parametrize("text,years", [
    ("3 years from delivery", 3), ("perpetual", None), ("forever, ideally", None),
    ("18 months", 2), ("one year", 1), ("twelve months", 1), ("a 5-year licence", 5),
    # …and a number that is not a term is still not a term.
    ("banana years", 3), ("an extra year of revisions", 3),
])
def test_the_term_is_read_from_what_they_actually_said(text, years):
    """"18 months" rounds UP: a licence sold for eighteen months and priced as one year
    is four months given away.

    A REVERSAL, RECORDED. This test used to assert that "one year" reads as the default
    three, on the reasoning that "a digit is required, so the default stands and is
    reported as assumed rather than guessed at confidently". That defended the regex
    rather than the decision: there is nothing less certain about "one year" than about
    "1 year", and on a real transcript the words are the normal case — people say numbers
    out loud and the recogniser writes them out. The effect was that the licence term, a
    lever running ×0.65 to ×1.90, silently defaulted on most calls that answered it.

    The caution behind the old rule was right, and it lives in the last two rows: the
    number has to be a term. "banana years" once read as one year, because the group
    matched the `a` inside the word."""
    licence = licence_from_ci({"license_term": text})
    assert licence.term_years == years


def test_only_a_phrase_that_names_the_thing_counts_as_stated():
    """Reading "we'll put it on our socials" as a decision about exclusivity would
    manufacture evidence — worse than the guess it replaces, because the guess at least
    announces itself."""
    licence = licence_from_ci({"media": "our socials and the website"})
    assert licence.media_stated and licence.media == "digital"
    assert not licence.exclusivity_stated and not licence.term_stated


# ── the document adds up ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("licence", [
    LicenceTerms(), LicenceTerms(territory="global", term_years=None),
    LicenceTerms(media="social", territory="local", term_years=1),
    LicenceTerms(media="all_media", exclusivity="full", term_years=10),
])
def test_the_two_lines_add_up_to_the_total(licence):
    """Each line is rounded on its own, so they can miss the total by a hundred. A client
    reads a document where the numbers add up, or they stop reading the document."""
    q = build_quote(_estimate(), licence)
    assert q.creative_fee + q.licence_fee == q.total


def test_the_derivation_is_printable():
    """The procurement-grade claim, made good: a buyer can see WHY the number is the
    number, and which lever moves it."""
    rows = derivation(build_quote(_estimate(), licence_from_ci(
        {"territory": "UK only", "license_term": "3 years"})))
    labels = [r[0] for r in rows]
    assert labels == ["Creative fee", "Licence", "Total"]
    assert "one territory" in rows[1][1] and "3 years" in rows[1][1]
    assert all(r[2].startswith("$") for r in rows)


def test_prices_are_said_out_loud_not_computed_to_the_dollar():
    q = build_quote(_estimate(), LicenceTerms())
    for value in (q.creative_fee, q.licence_fee, q.total, q.floor):
        assert value % 100 == 0, f"${value:,} reads as arithmetic that escaped"
