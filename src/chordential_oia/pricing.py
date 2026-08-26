"""What the work costs, and what the use of it costs. Two fees, not one.

Reported live, and the most expensive gap in the system: *"I have no idea how I am
pricing the product. The proposal generated a price based on what the client told me
their budget was, which is a name-your-price on my service."*

That was exactly right. ``capabilities.quote_band`` had three tiers and the second one
was the client's disclosed budget, which fires on essentially every deal that has had a
discovery call — because discovering the budget is what a discovery call does. So the
same charity film quoted $6,000 to a client who said $6,000 and $90,000 to a client who
said $90,000, against a cost to deliver of $4,062–$8,435. Underneath sat a real cost
engine and a set of researched market priors, and neither reached the buyer. They were
decorative.

**The shape of the fix is specific to music.** Production cost is nearly flat with
respect to usage; value is not. A ninety-second cue costs the same to write whether it
runs on one charity's YouTube or across national television for three years. Pricing it
by cost alone gives the licence away; pricing it by the client's budget gives the whole
thing away. So a quote here has two parts:

* the **creative fee** — what it costs to make, marked up to target margin. That is
  :mod:`chordential_oia.estimation`, which already pays the players and the room
  separately from the desk, and which this module does not second-guess.
* the **licence fee** — what it costs to *use*: media × territory × term × exclusivity.
  Every one of those is a question the call prep sheet already asks out loud, and whose
  own rationale already promises this ("Territory is priced"; "Term drives the fee more
  than almost anything else, and 'perpetual' assumed is a fee given away"). Until now
  the answers were notes.

The client's budget is demoted from *the answer* to *the check*, with three verdicts a
human can act on: below the floor (scope down or decline, said out loud rather than
discovered at invoice), inside the band, or above it (quote the value — do not anchor
to a generous number just because it was said aloud).

Two refusals are load-bearing. This never returns a number below the cost floor, and it
never treats an assumed licence input as a stated one: every factor carries whether the
brief SAID it (ADR-0058), because a term nobody confirmed is a fee we chose to give
away, and the surface that shows the price has to be able to say which ones those are.

The factor tables are **priors, not measurements** — the same standing they have in
``estimation`` — and they say so in :data:`PRIOR_NOTE`. They are meant to be ratified by
the operator and calibrated against actuals, not trusted because they are written down.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .estimation import BAND_SPREAD, TARGET_MARGIN, Estimate

# The margin below which we do not go, whatever the client said. Lower than the target:
# the target is what we aim for, this is the line that turns a negotiation into a walk.
MIN_MARGIN = 0.25

PRIOR_NOTE = (
    "Licence factors are expert priors, ratified by the operator and NOT calibrated on "
    "Chordential actuals."
)

# ── The licence factor tables ────────────────────────────────────────────────────────
#
# Multiplicative, against a baseline job: broadcast, national, three years, non-exclusive
# — every factor 1.0. The baseline is deliberately a normal advertising licence rather
# than the cheapest possible one, so the common case needs no adjustment and the
# adjustments read as what they are.

MEDIA_FACTORS: Dict[str, float] = {
    "social": 0.55,          # organic social only
    "digital": 0.70,         # online video, paid digital, the brand's own channels
    "broadcast": 1.00,       # TV / radio — the baseline
    "all_media": 1.30,       # broadcast + digital + OOH + in-store
    "all_media_cinema": 1.55,   # everything, including theatrical
}
MEDIA_LABELS: Dict[str, str] = {
    "social": "organic social",
    "digital": "all digital",
    "broadcast": "broadcast",
    "all_media": "all media",
    "all_media_cinema": "all media including cinema",
}

TERRITORY_FACTORS: Dict[str, float] = {
    "local": 0.75,           # one country / one region
    "national": 1.00,
    "global": 2.00,
}
TERRITORY_LABELS: Dict[str, str] = {
    "local": "one territory", "national": "national", "global": "worldwide",
}

# Term, in years. `None` is perpetuity. Perpetual is 1.9 rather than something enormous
# because in practice a campaign's music stops being used long before the licence
# expires — what perpetuity really buys the client is never having to come back, and
# that is worth roughly a doubling, not an infinity.
TERM_FACTORS: Dict[Optional[int], float] = {
    1: 0.65, 2: 0.85, 3: 1.00, 5: 1.30, 10: 1.60, None: 1.90,
}

# Calibrated against the market rather than guessed (see docs/market-pricing-research.md).
# The 2026 sync rate cards put limited exclusivity at +50% and full exclusivity at +150%
# or more, with a second source giving a 2×–5× range. The first pass here had them at
# +40% and +85%, which underpriced the single term clients most often assume is free —
# and which the call prep sheet already warns is "a real cost to us".
EXCLUSIVITY_FACTORS: Dict[str, float] = {
    "none": 1.00,
    "category": 1.50,        # nobody in their competitive set — market: +50%
    "full": 2.50,            # nobody at all; the piece leaves our catalogue — market: +150%
}
EXCLUSIVITY_LABELS: Dict[str, str] = {
    "none": "non-exclusive", "category": "category-exclusive", "full": "fully exclusive",
}

# The licence fee at baseline, as a share of the creative fee. A normal national
# broadcast campaign therefore pays half as much again for the right to use the music as
# it does to have it made — which is the ratio the market already runs at, and the ratio
# this business currently collects none of.
BASE_LICENCE_SHARE = 0.50

# Four factors multiplied together compound fast, and the market does not. Normalised to
# a common baseline, the published sync card puts "perpetual, worldwide, all media" at
# 2.5× a one-year North American licence; unchecked, these tables reach 7.6×. Each factor
# is individually defensible and their product is not, because a buyer refusing to pay is
# a fact no rate card overrides. The cap is set above the market's top so bespoke work —
# where a buyout transfers a real asset rather than renting a catalogue track — keeps
# headroom, and it is a documented ceiling rather than a quiet fudge of the factors.
LICENCE_FACTOR_CAP = 4.0

# What the market charges, for the prep sheet and for anyone re-reading these numbers in
# a year. Sourced August 2026; see docs/market-pricing-research.md for the full working.
# Swell is the closest comparator — a music house with a PUBLISHED rate card — and the
# entry package is the number a buyer will have in their head.
MARKET_BENCHMARKS = [
    ("Swell Music + Sound", "Original score · 1 demo · 5 revisions · stems", 10_000, 10_000),
    ("Swell Music + Sound", "Original score · 5 demos", 15_000, 15_000),
    ("Swell Music + Sound", "Custom library track · unlimited use", 5_000, 5_000),
    ("Synchro Music (UK)", "Bespoke ad music · simple, digital only", 3_800, 3_800),
    ("Synchro Music (UK)", "Bespoke ad music · mid-scale commission", 10_000, 19_000),
    ("Synchro Music (UK)", "Flagship TV campaign · full buyout", 38_000, 38_000),
    ("Industry guides", "Custom composition for a :30 spot", 2_000, 25_000),
]

# Verdicts on the client's stated budget.
BELOW_FLOOR = "below_floor"
IN_BAND = "in_band"
ABOVE_BAND = "above_band"
NO_BUDGET = "unknown"


@dataclass
class LicenceTerms:
    """How the music may be used — and, for each input, whether the brief SAID so.

    The evidence flags are the point (ADR-0058). An assumed three-year national licence
    priced as if it were stated is a fee we decided to give away without telling anyone,
    and the surface showing the number has to be able to name which parts of it are a
    guess. Defaults are the baseline job, so an unscoped deal prices as an ordinary
    campaign rather than as the cheapest or the most expensive thing imaginable.
    """
    media: str = "broadcast"
    territory: str = "national"
    term_years: Optional[int] = 3
    exclusivity: str = "none"
    media_stated: bool = False
    territory_stated: bool = False
    term_stated: bool = False
    exclusivity_stated: bool = False

    @property
    def factor(self) -> float:
        raw = (MEDIA_FACTORS.get(self.media, 1.0)
               * TERRITORY_FACTORS.get(self.territory, 1.0)
               * TERM_FACTORS.get(self.term_years, 1.0)
               * EXCLUSIVITY_FACTORS.get(self.exclusivity, 1.0))
        return min(raw, LICENCE_FACTOR_CAP)

    @property
    def capped(self) -> bool:
        """True when the four factors compounded past what the market will pay. Worth
        surfacing: it means the licence being asked for is at the ceiling, which is a
        negotiation position rather than an arithmetic result."""
        return (MEDIA_FACTORS.get(self.media, 1.0)
                * TERRITORY_FACTORS.get(self.territory, 1.0)
                * TERM_FACTORS.get(self.term_years, 1.0)
                * EXCLUSIVITY_FACTORS.get(self.exclusivity, 1.0)) > LICENCE_FACTOR_CAP

    @property
    def term_label(self) -> str:
        if self.term_years is None:
            return "in perpetuity"
        return f"{self.term_years} year" + ("s" if self.term_years != 1 else "")

    @property
    def summary(self) -> str:
        """The licence in one line, for the proposal. Reads as a licence, not as a row
        of settings: "worldwide, all media, 3 years, non-exclusive"."""
        return ", ".join([
            TERRITORY_LABELS.get(self.territory, self.territory),
            MEDIA_LABELS.get(self.media, self.media),
            self.term_label,
            EXCLUSIVITY_LABELS.get(self.exclusivity, self.exclusivity),
        ])

    @property
    def assumed(self) -> List[str]:
        """Which of the four we had to guess, in the client's words."""
        return [name for name, stated in (
            ("media", self.media_stated),
            ("territory", self.territory_stated),
            ("licence term", self.term_stated),
            ("exclusivity", self.exclusivity_stated),
        ) if not stated]


# ── Reading the licence off what discovery actually captured ─────────────────────────

_GLOBAL = re.compile(r"world ?wide|global|all territor|every ?where|internationa|"
                     r"all market|multi[- ]?territor", re.I)
_LOCAL = re.compile(r"\b(uk|us|usa|domestic|one (?:country|territory)|local|regional|"
                    r"single (?:country|market)|city|state)\b", re.I)
# A CONTINENT IS A TERRITORY ANSWER. "North America to start" matched none of these and
# fell through to an ASSUMED national licence — on a transcript where the client had just
# answered the question. The named regions clients actually say are the answer; they are
# read as national because that is what a multi-country region prices as against a
# baseline built for one national campaign.
_NATIONAL = re.compile(r"\bnational(?:ly|wide)?\b|north america|latin america|\bemea\b|"
                       r"\bapac\b|\banz\b|europe(?!an union)|\bdach\b|nordics|"
                       r"united states|canada|\bmena\b", re.I)

_PERPETUAL = re.compile(r"perpetu|forever|in ?definite|buy ?out|unlimited time|"
                        r"no expir|permanent", re.I)
# WORDS ARE NUMBERS. A client says "twelve months from first air"; the transcript writes
# it out; `(\d+)` sees nothing and the licence quietly reverts to an assumed three years.
# Term is the second-largest lever on the sheet — one year is ×0.65 and perpetuity ×1.90 —
# so a term that fails to parse is not a rounding error, it is the fee.
_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "eighteen": 18,
    "twenty": 20, "twentyfour": 24, "twenty-four": 24, "a": 1, "an": 1,
}
_NUM = r"(\d+|" + "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True)) + r")"
_YEARS = re.compile(_NUM + r"[\s-]*year", re.I)
_MONTHS = re.compile(_NUM + r"[\s-]*month", re.I)


def _count(match) -> Optional[int]:
    """The number a term match found, whether it was written in digits or in words."""
    raw = (match.group(1) or "").strip().lower()
    if raw.isdigit():
        return int(raw)
    return _NUMBER_WORDS.get(raw)

_EXCL_FULL = re.compile(r"full(?:y)? exclusiv|total(?:ly)? exclusiv|exclusive to us|"
                        r"complete(?:ly)? exclusiv", re.I)
_EXCL_CATEGORY = re.compile(r"categor|competit|sector|industry|our space|"
                            r"another (?:charity|brand|company)", re.I)
_EXCL_NONE = re.compile(r"non[- ]?exclusiv|no exclusiv|not exclusiv|don'?t need exclusiv",
                        re.I)

_CINEMA = re.compile(r"cinema|theatrical|in ?theat|big screen", re.I)
_ALL_MEDIA = re.compile(r"all media|every ?where|any media|full media|"
                        r"broadcast and digital|tv and (?:digital|online)", re.I)
_BROADCAST = re.compile(r"broadcast|\btv\b|televis|linear|radio|ott|ctv", re.I)
_SOCIAL_ONLY = re.compile(r"organic social|social only|just social|social media only", re.I)
_DIGITAL = re.compile(r"digital|online|youtube|web|paid (?:media|social)|instagram|"
                      r"tiktok|meta\b|streaming", re.I)


def _first_text(fields: Dict[str, str], *keys: str) -> str:
    for key in keys:
        value = str((fields or {}).get(key) or "").strip()
        if value:
            return value
    return ""


def licence_from_ci(fields: Optional[Dict[str, str]] = None) -> LicenceTerms:
    """Read the licence out of Campaign Intelligence, and record what was NOT said.

    Deliberately conservative: a phrase has to actually name the thing to count as
    stated. Reading "we'll use it on our socials" as a decision about exclusivity would
    manufacture evidence, which is worse than the guess it replaces — the guess at least
    announces itself in ``assumed``.
    """
    f = {k: str(v or "") for k, v in (fields or {}).items()}
    terms = LicenceTerms()

    territory = _first_text(f, "territory", "usage_territory", "rights_territory",
                            "territories", "markets", "geography")
    if territory:
        if _GLOBAL.search(territory):
            terms.territory, terms.territory_stated = "global", True
        elif _NATIONAL.search(territory):
            terms.territory, terms.territory_stated = "national", True
        elif _LOCAL.search(territory):
            terms.territory, terms.territory_stated = "local", True

    # "term" IS ON THIS LIST NOW, and it is the whole reason this function was reading
    # nothing on real calls. The extraction engine's Rights & Licensing worker is
    # instructed to emit exactly `usage_rights, territory, term, media, …` — and this
    # looked for `license_term`, `licence_term`, `usage_term`, `rights_term`, never the
    # bare `term` it was being handed. The lever arrived under a name nothing read, so
    # every call priced at an assumed three years however clearly the client answered.
    term = _first_text(f, "license_term", "licence_term", "term", "usage_term",
                       "rights_term", "licence_period", "license_period", "usage_rights",
                       "buyout", "media_term")
    if term:
        if _PERPETUAL.search(term):
            terms.term_years, terms.term_stated = None, True
        else:
            years = _YEARS.search(term)
            months = _MONTHS.search(term)
            n_years = _count(years) if years else None
            n_months = _count(months) if months else None
            if n_years:
                terms.term_years, terms.term_stated = max(1, n_years), True
            elif n_months:
                # Rounded UP to whole years: a licence sold for eighteen months and
                # priced as one year is four months given away.
                terms.term_years, terms.term_stated = max(1, -(-n_months // 12)), True

    excl = _first_text(f, "exclusivity", "rights_exclusivity", "exclusive",
                       "category_exclusivity")
    if excl:
        if _EXCL_NONE.search(excl):
            terms.exclusivity, terms.exclusivity_stated = "none", True
        elif _EXCL_FULL.search(excl):
            terms.exclusivity, terms.exclusivity_stated = "full", True
        elif _EXCL_CATEGORY.search(excl):
            terms.exclusivity, terms.exclusivity_stated = "category", True

    media = _first_text(f, "media", "usage_media", "channels", "rollout", "placements",
                        "media_plan", "deliverables")
    if media:
        if _CINEMA.search(media):
            terms.media, terms.media_stated = "all_media_cinema", True
        elif _ALL_MEDIA.search(media):
            terms.media, terms.media_stated = "all_media", True
        elif _BROADCAST.search(media):
            terms.media, terms.media_stated = "broadcast", True
        elif _SOCIAL_ONLY.search(media):
            terms.media, terms.media_stated = "social", True
        elif _DIGITAL.search(media):
            terms.media, terms.media_stated = "digital", True
    return terms


# ── The quote ────────────────────────────────────────────────────────────────────────

def _money(value: float) -> int:
    """Round to something a human would say out loud. $100s under $10k, $500s above —
    a quote of $8,137 reads as arithmetic that escaped, not as a price."""
    if value < 10_000:
        return int(round(value / 100.0)) * 100
    return int(round(value / 500.0)) * 500


@dataclass
class Quote:
    """One priced offer, itemised, with the evidence and the floor it stands on."""
    creative_fee: int
    licence_fee: int
    total: int
    low: int
    high: int
    floor: int                      # cost at MIN_MARGIN — never quote below this
    floored: bool                   # the floor bound: value came in under cost
    licence: LicenceTerms = field(default_factory=LicenceTerms)
    creative_basis: str = ""
    licence_basis: str = ""
    budget_verdict: str = NO_BUDGET
    budget_note: str = ""
    stated_budget: Optional[int] = None
    assumptions: List[str] = field(default_factory=list)
    # An operator typed this price. Surfaces say so rather than presenting a human's
    # decision as the engine's arithmetic.
    overridden: bool = False

    @property
    def band(self) -> Tuple[int, int]:
        return self.low, self.high

    def rescaled_to(self, low: int, high: int) -> "Quote":
        """The same quote at an operator-set price (the machine proposes, Jon disposes).

        The two lines are rescaled to keep their ratio, so a document showing an
        overridden total still ADDS UP. Leaving the itemisation at its computed values
        beside a different total would put visibly wrong arithmetic in front of a buyer,
        which costs more than the override was worth.

        The floor and the verdict are deliberately carried over untouched: they describe
        what the work costs and what the client said, and neither of those changed
        because we chose a different number. ``floored`` is RE-derived, because an
        override below cost is exactly the case worth still being told about.
        """
        low, high = int(low), int(high)
        total = int(round((low + high) / 2))
        share = (self.licence_fee / self.total) if self.total else BASE_LICENCE_SHARE
        licence = _money(total * share)
        return Quote(
            creative_fee=total - licence, licence_fee=licence, total=total,
            low=low, high=high, floor=self.floor, floored=total < self.floor,
            licence=self.licence, creative_basis=self.creative_basis,
            licence_basis=self.licence_basis, budget_verdict=self.budget_verdict,
            budget_note=self.budget_note, stated_budget=self.stated_budget,
            assumptions=list(self.assumptions), overridden=True,
        )


def _budget_ints(text: str) -> List[int]:
    """Every money figure in a phrase, as ints. Bare thousands ("6k", "$90k") count."""
    out: List[int] = []
    for raw, suffix in re.findall(r"\$?\s*([\d][\d,\.]*)\s*([kKmM]?)", text or ""):
        cleaned = raw.replace(",", "").rstrip(".")
        if not cleaned or cleaned.count(".") > 1:
            continue
        try:
            value = float(cleaned)
        except ValueError:
            continue
        if suffix.lower() == "k":
            value *= 1_000
        elif suffix.lower() == "m":
            value *= 1_000_000
        # Below $100 is a runtime, a count or a percentage, not a budget.
        if value >= 100:
            out.append(int(value))
    return out


def build_quote(estimate: Estimate, licence: Optional[LicenceTerms] = None, *,
                budget_band: str = "", spread: float = BAND_SPREAD / 2.0) -> Quote:
    """Price one job: creative fee + licence fee, floored at cost.

    ``estimate`` supplies the cost of MAKING it. Its own ``suggested_price`` is not used:
    that figure already folds a usage multiplier into the creative number, and using it
    here would charge for the licence twice. The cost is the input; the pricing happens
    in this module and nowhere else.

    ``budget_band`` is the client's stated figure. It never sets the price — it produces
    a verdict.
    """
    licence = licence or LicenceTerms()
    cost = float(getattr(estimate, "estimated_cost", 0.0) or 0.0)
    cost_high = float(getattr(estimate, "cost_high", 0.0) or cost)

    creative = cost / (1.0 - TARGET_MARGIN) if cost else 0.0
    licence_fee = creative * BASE_LICENCE_SHARE * licence.factor
    total = creative + licence_fee

    # The floor is built on the HIGH end of the cost band, not the midpoint. A floor that
    # only holds when the job goes well is not a floor.
    floor = cost_high / (1.0 - MIN_MARGIN) if cost_high else 0.0
    floored = total < floor
    if floored:
        # Keep the split legible rather than silently inflating one line: the licence
        # keeps its computed share of the raised total.
        share = licence_fee / total if total else BASE_LICENCE_SHARE
        total = floor
        licence_fee = total * share
        creative = total - licence_fee

    quote = Quote(
        creative_fee=_money(creative),
        licence_fee=_money(licence_fee),
        total=_money(total),
        low=_money(total * (1.0 - spread)),
        high=_money(total * (1.0 + spread)),
        floor=_money(floor),
        floored=floored,
        licence=licence,
        creative_basis=_creative_basis(estimate),
        licence_basis=licence.summary,
    )
    # The itemised lines are rounded independently, so they can miss the rounded total by
    # a hundred. The client reads a document where the two lines add up, so the creative
    # fee absorbs it — never the licence fee, which is the line with a term attached.
    drift = quote.total - (quote.creative_fee + quote.licence_fee)
    if drift:
        quote.creative_fee += drift

    assumed = licence.assumed
    if assumed:
        quote.assumptions.append(
            "The licence assumes " + licence.summary + " — "
            + ", ".join(assumed) + " " + ("was" if len(assumed) == 1 else "were")
            + " not stated in the brief. Confirm before this becomes an offer.")
    if floored:
        quote.assumptions.append(
            "Priced at our minimum for this scope; the licence as described does not "
            "on its own carry the cost of making it.")
    _judge_budget(quote, budget_band)
    return quote


def _creative_basis(estimate: Estimate) -> str:
    """What the creative fee is FOR, in one line the client can check against."""
    scope = getattr(estimate, "scope", None)
    session = getattr(estimate, "session", None)
    bits: List[str] = []
    if scope is not None and getattr(scope, "summary", ""):
        bits.append(str(scope.summary))
    elif getattr(estimate, "discipline", None) is not None:
        bits.append(getattr(estimate.discipline, "label", "original music"))
    label = str(getattr(estimate, "session_label", "") or "")
    if label:
        # "Piano / simple (assumed)" is an internal label; the parenthetical is the
        # evidence flag, which is reported in `assumptions`, not inside a fee line.
        bits.append(label.replace(" (assumed)", "").strip().lower())
    if session is not None and getattr(session, "live", False):
        dates = int(getattr(estimate, "session_dates", 0) or 0)
        if dates:
            bits.append(f"{dates} recording date" + ("s" if dates != 1 else ""))
    return ", ".join(b for b in bits if b)


def _judge_budget(quote: Quote, budget_band: str) -> None:
    """Set the verdict on what the client said. Never changes the price."""
    nums = _budget_ints(budget_band or "")
    if not nums:
        quote.budget_note = "No budget stated. The quote stands on scope and licence."
        return
    stated = max(nums)
    quote.stated_budget = stated
    if stated < quote.floor:
        quote.budget_verdict = BELOW_FLOOR
        quote.budget_note = (
            f"They said ${stated:,}. Our floor for this scope is ${quote.floor:,} — "
            f"below it we are paying to do the work. Reduce the scope (sampled rather "
            f"than live, fewer cues, a shorter licence) or decline.")
    elif stated > quote.high:
        quote.budget_verdict = ABOVE_BAND
        quote.budget_note = (
            f"They said ${stated:,}, above our ${quote.low:,}–${quote.high:,} for this "
            f"scope. Quote the work, not their number — or offer the wider licence "
            f"that would justify theirs.")
    else:
        quote.budget_verdict = IN_BAND
        quote.budget_note = (
            f"They said ${stated:,}, inside our ${quote.low:,}–${quote.high:,}.")


def derivation(quote: Quote) -> List[Tuple[str, str, str]]:
    """The quote as rows a surface can print: (label, detail, amount).

    This is the procurement-grade claim made good — a buyer can see WHY the number is
    the number, and which lever moves it.
    """
    return [
        ("Creative fee", quote.creative_basis or "original music, written and delivered",
         f"${quote.creative_fee:,}"),
        ("Licence", quote.licence_basis, f"${quote.licence_fee:,}"),
        ("Total", "", f"${quote.total:,}"),
    ]


def reference_estimate(cost: float, *, spread: float = BAND_SPREAD) -> Estimate:
    """An Estimate carrying nothing but the cost of MAKING the work.

    For the pricing reference page, which prices a job of a chosen size rather than a real
    deal. :func:`build_quote` reads exactly two things off an estimate — ``estimated_cost``
    and ``cost_high`` — and this exists so the page does not have to know that: a surface
    that hand-built a stand-in Estimate would be encoding an internal fact about this
    module, and would keep working while quietly diverging the day build_quote read a
    third field.

    Nothing else on it is meaningful and none of it is shown. In particular
    ``suggested_price`` is left at zero rather than computed: it folds usage into the
    creative number and `build_quote` deliberately ignores it (ADR-0065), so a plausible
    figure there would be a number nobody should read.
    """
    from .models import MusicDiscipline
    cost = max(0.0, float(cost or 0.0))
    return Estimate(
        discipline=MusicDiscipline.COMPOSITION, lines=[], multipliers=[],
        base_cost=cost, multiplier_total=1.0, revision_uplift=0.0,
        estimated_cost=cost, suggested_price=0.0, expected_margin_pct=0.0,
        disclosed_budget=None, budget_delta_note="",
        cost_low=cost * (1.0 - spread), cost_high=cost * (1.0 + spread),
    )


# ── The price guide, for the call ────────────────────────────────────────────────────

def price_guide(estimate: Estimate, licence: Optional[LicenceTerms] = None) -> dict:
    """What each licence answer is WORTH, priced against this specific deal.

    The prep sheet already asks the four licence questions and already tells the operator
    they matter — "Territory is priced", "Term drives the fee more than almost anything
    else". What it could not say was *how much*, so the questions read as diligence rather
    than as money, and they are the ones that get dropped when a call runs long.

    This prices every option against THIS job, so the sheet can say the thing that
    actually changes behaviour on a call: asking about exclusivity is worth $7,700 here.
    Everything is derived from the same `build_quote` the proposal uses — one derivation,
    two reporters — so the guide cannot quote a number the proposal would not honour.
    """
    licence = licence or LicenceTerms()
    here = build_quote(estimate, licence)
    rows = []
    for label, field, options, labels in (
        ("Media", "media", list(MEDIA_FACTORS), MEDIA_LABELS),
        ("Territory", "territory", list(TERRITORY_FACTORS), TERRITORY_LABELS),
        ("Licence term", "term_years", [1, 2, 3, 5, 10, None], None),
        ("Exclusivity", "exclusivity", list(EXCLUSIVITY_FACTORS), EXCLUSIVITY_LABELS),
    ):
        priced = []
        for option in options:
            trial = LicenceTerms(**{**licence.__dict__, field: option})
            quote = build_quote(estimate, trial)
            priced.append({
                "label": (trial.term_label if labels is None
                          else labels.get(option, str(option))),
                "total": quote.total,
                "delta": quote.total - here.total,
                "current": option == getattr(licence, field),
            })
        spread = max(p["total"] for p in priced) - min(p["total"] for p in priced)
        rows.append({"question": label, "field": field, "options": priced,
                     "spread": spread, "stated": getattr(licence, f"{field.split('_')[0]}_stated",
                                                         False)})
    # Loudest first: the question worth the most money is the one that must survive a
    # call that overruns, and it is not always the one the operator expects.
    rows.sort(key=lambda r: r["spread"], reverse=True)
    return {"quote": here, "rows": rows,
            "benchmarks": MARKET_BENCHMARKS, "prior_note": PRIOR_NOTE}
