"""Estimation engine — the Phase-1 expert model as a first-class intelligence layer.

Estimation is a pillar of the moat (see ``docs/company-strategy.md``: the hybrid
3-phase estimator). Phase 1 applies the ratified industry role-hour priors and
complexity multipliers to the team shape the qualification layer produces. This
module is the canonical home for that model — the dashboard's estimate page is a
thin consumer of it (``chordential_oia.web.estimate`` re-exports from here).

Phase 1 is deliberately *uncalibrated*: every estimate carries a wide confidence
**band** that is honest about the uncertainty. Phases 2/3 (market benchmarks,
Chordential actuals) narrow the band as real data accrues — they are out of scope
until that data exists.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import compensation
from .compensation import WriterFee
from .models import MusicDiscipline, Opportunity

# Which team-shape roles author the work, for splitting the writer fee. Mirrors
# `delivery.WRITER_ROLES` — a mixer is not a writer and does not share the fee.
_WRITER_ROLE_NAMES = frozenset({
    "composer", "co-composer", "arranger", "orchestrator", "topline", "topliner",
    "songwriter", "lyricist",
})

# Base role hours for ONE campaign cue carried end to end — brief and spotting,
# demo directions, the revision rounds, the final, stems and the deliverable
# versions. They were previously demo-scale (8 composer hours is one demo, not a
# national campaign), which is a large part of why the engine priced a national
# :30 at roughly a third of the market band the public planning tool quotes.
# Rates are blended placeholders pending AFM / SAG-AFTRA / market data.
ROLE_HOURS: Dict[str, float] = {
    "Composer": 20.0,
    "Arranger": 8.0,
    "Orchestrator": 16.0,
    "Music Editor": 5.0,
    "Mixer": 8.0,
    "Mix Engineer": 10.0,
    "Mastering": 2.0,
    "Project Manager": 6.0,
    "Sound Designer": 10.0,
    "Music Supervisor": 6.0,
}
# Scored media — film, television, documentary, games — is not bought by the format
# of a spot. It is bought by the MINUTE OF FINISHED SCORE, and the cue count on top of
# that, because each cue costs a spotting conversation and a revision pass whether it
# runs twenty seconds or three minutes.
#
# Before this existed the engine was blind to the amount of music. Measured on the
# engine as it stood: one cue and sixty cues priced identically ($57,446); two minutes
# of score and ninety minutes priced identically ($57,446). Nothing but the FORMAT
# WORDS in the brief — "orchestra", "national", the cutdown list — moved the number.
# The consequence was not a rounding error: **a :60 commercial with two cutdowns, 90
# seconds of music, quoted at 1.33× a 28-cue, 45-minute orchestral feature score.** The
# product sells a film/TV engagement it could not price.
#
# Hours per FINISHED MINUTE of score. Phase-1 expert priors on the same footing as
# ROLE_HOURS and the rates below — blended placeholders pending AFM / market data, and
# NOT yet operator-ratified the way PUBLIC_BANDS are. They are deliberately linear:
# thematic reuse genuinely makes the ninetieth minute cheaper than the first, but a
# decline curve invented here would be a number with nothing behind it, so the
# economy of scale is named in the assumptions and left for calibration instead.
MINUTE_HOURS: Dict[str, float] = {
    "Composer": 6.0,
    "Arranger": 2.0,
    "Orchestrator": 3.0,
    "Music Editor": 1.5,
    "Mixer": 1.0,
    "Mix Engineer": 1.2,
    "Mastering": 0.2,
    "Project Manager": 0.8,
    "Sound Designer": 1.5,
    "Music Supervisor": 0.5,
}

# Hours per CUE, independent of how long the cue runs. This is the part a per-minute
# rate alone gets wrong: 45 minutes across 8 cues and 45 minutes across 40 cues are
# not the same job, and the difference is forty spotting notes and forty approvals.
CUE_HOURS: Dict[str, float] = {
    "Composer": 1.5,
    "Music Editor": 0.5,
    "Mix Engineer": 0.3,
    "Mixer": 0.3,
    "Project Manager": 0.4,
    "Music Supervisor": 0.2,
}

ROLE_RATES: Dict[str, float] = {
    "Composer": 150.0,
    "Arranger": 100.0,
    "Orchestrator": 90.0,
    "Music Editor": 75.0,
    "Mixer": 110.0,
    "Mix Engineer": 125.0,
    "Mastering": 120.0,
    "Project Manager": 85.0,
    "Sound Designer": 100.0,
    "Music Supervisor": 95.0,
}

# Target gross margin applied to suggested price (lean: protect margin).
TARGET_MARGIN = 0.40

# Phase-1 confidence band: ±this fraction around the point estimate. Wide on
# purpose (uncalibrated). Phase 3 calibration shrinks it from real variance.
BAND_SPREAD = 0.35


@dataclass
class RoleLine:
    role: str
    hours: float
    rate: float
    # When an assigned talent's rate is a day/flat rate, the line cost is not
    # simply hours × rate. ``cost_override`` carries the computed cost in that
    # case; left None, the line falls back to the hourly hours × rate.
    cost_override: Optional[float] = None
    # The rate unit, so the line displays correctly on the client proposal —
    # a day/flat rate must NOT render as "Nh × $rate/h" (reads as $rate/hour).
    unit: str = "hourly"

    @property
    def cost(self) -> float:
        if self.cost_override is not None:
            return self.cost_override
        return self.hours * self.rate

    @property
    def _days(self) -> int:
        return max(1, math.ceil(self.hours / 8.0))

    @property
    def qty_label(self) -> str:
        """Quantity column on the proposal (hours, days, or a flat marker)."""
        if self.unit == "day":
            return f"{self._days}d"
        if self.unit == "project":
            return "flat"
        return f"{self.hours:g}h"

    @property
    def rate_label(self) -> str:
        """Rate column, unit-correct so the client never sees a $/h day rate."""
        if self.unit == "day":
            return f"${self.rate:,.0f}/day"
        if self.unit == "project":
            return "flat fee"
        return f"${self.rate:,.0f}/h"

    @property
    def breakdown(self) -> str:
        """One-line scope row for the plain-text proposal."""
        if self.unit == "day":
            return f"{self._days}d × ${self.rate:,.0f}/day = ${self.cost:,.0f}"
        if self.unit == "project":
            return f"flat fee = ${self.cost:,.0f}"
        return f"{self.hours:g}h × ${self.rate:,.0f}/h = ${self.cost:,.0f}"


@dataclass
class Multiplier:
    name: str
    setting: str
    factor: float
    # Where the factor lands. The estimate page showed four factors above a
    # "Compounded multiplier" that was not their product, because one of them
    # was applied elsewhere and nothing said so. "desk" factors compound into
    # multiplier_total; "price" factors are fees applied after margin.
    applies: str = "desk"


@dataclass
class Estimate:
    discipline: MusicDiscipline
    lines: List[RoleLine]
    multipliers: List[Multiplier]
    base_cost: float
    multiplier_total: float
    revision_uplift: float
    estimated_cost: float
    suggested_price: float
    expected_margin_pct: float
    disclosed_budget: Optional[str]
    budget_delta_note: str
    # Phase-1 confidence band around the point cost estimate.
    cost_low: float = 0.0
    cost_high: float = 0.0
    # Players + room. Kept separate from the desk lines because it is the part a
    # client most often asks to see itemised, and the part that used to be missing.
    session_cost: float = 0.0
    session_label: str = ""
    band_spread_pct: float = BAND_SPREAD * 100.0
    assumptions: List[str] = field(default_factory=list)
    # How much music, and whether the brief said so or we assumed it. None on the
    # campaign path, which is priced per cue and has no minutes to report.
    scope: Optional["Scope"] = None
    # The recording session as explicit scope — who plays, on how many dates, and
    # whether the brief said so. None on the campaign path, where a cue is one session.
    session: Optional["Session"] = None
    session_dates: int = 0
    # What the writer(s) are paid for this job (ADR-0061). Carried ON the estimate so
    # the price quoted to a client and the fee promised to a composer are the same
    # arithmetic — before this, the `Composer` line was a flat $3,000 whatever the job.
    writer_fee: Optional["WriterFee"] = None

    @property
    def cost_range(self) -> str:
        return f"${self.cost_low:,.0f} to ${self.cost_high:,.0f}"


# What it costs to actually record the music, by instrumentation. None of this
# existed before: "full orchestra" was a ×4 on desk hours — including the project
# manager's — which multiplied the wrong thing and never paid a single player.
# Figures are session-scale placeholders (players at scale + the room), to be
# replaced with AFM rate-card data alongside ROLE_RATES.
SESSION_PACKAGES: Dict[str, dict] = {
    "simple": {"label": "Piano / simple (assumed)", "players": 1, "player_fee": 600.0,
               "studio": 600.0, "extras": 0.0, "complexity": 1.0},
    "hybrid": {"label": "Hybrid / small ensemble", "players": 4, "player_fee": 650.0,
               "studio": 1800.0, "extras": 0.0, "complexity": 1.25},
    "orchestral": {"label": "Full orchestra", "players": 30, "player_fee": 650.0,
                   "studio": 3500.0, "extras": 2700.0, "complexity": 1.6},
}

# Usage/licensing is a RIGHTS FEE on the price, not a cost of making the music —
# a wider licence does not make the session longer. These factors are the same
# ones the public planning band quotes (see PUBLIC_USAGE), so the internal number
# and the number a visitor is shown can no longer drift apart.
USAGE_FACTORS: Dict[str, float] = {"local": 0.75, "national": 1.0, "global": 2.0}

# The public planning band (the /commission estimator). These are the researched,
# operator-ratified market priors — the engine is calibrated toward them, not the
# other way round. They lived as hardcoded JavaScript inside the template, which
# is how the site came to quote $9,000-18,000 for a job the engine costed at
# $4,847. One definition, rendered into the page; a test asserts they still agree.
PUBLIC_BANDS: Dict[str, tuple] = {
    "anthem": (16000, 28000),
    "spot": (9000, 18000),
    "title": (12000, 22000),
    "social": (4500, 9000),
}
PUBLIC_LENGTHS: Dict[str, float] = {"15": 0.8, "30": 1.0, "60": 1.25, "120": 1.6}
PUBLIC_USAGE: Dict[str, float] = {
    "social": USAGE_FACTORS["local"],
    "national": USAGE_FACTORS["national"],
    "global": USAGE_FACTORS["global"],
}


def public_band(kind: str, length: str, usage: str) -> tuple:
    """The band the public estimator shows, computed from the shared priors."""
    low, high = PUBLIC_BANDS[kind]
    factor = PUBLIC_LENGTHS[length] * PUBLIC_USAGE[usage]
    return round(low * factor), round(high * factor)


# The length a brief STATES, longest first. "anthem" is deliberately absent: it is a
# genre convention that usually means :60, which is good enough to price against but
# not good enough to stamp on a filename (ADR-0037).
_STATED_LENGTHS = (
    (120, (":120", "2-minute", "two minute", "long form")),
    (60, (":60", "60-second", "60 second")),
    (30, (":30", "30-second", "30 second")),
    (15, (":15", ":06", "15-second", "15 second")),
)


def stated_length(text: str) -> Optional[int]:
    """The spot length in seconds the brief actually STATES, or ``None``.

    Longest mention wins, same as ``_infer_duration`` — a brief listing its cutdown
    suite is a :60 job, not a :15 one. Unlike ``_infer_duration`` this NEVER falls
    back to an assumption: pricing must put a number on an unstated brief, but a
    *filename* asserting ``_30_`` on a deliverable nobody measured is a claim we
    cannot back. Callers that name files omit the token when this returns None.
    """
    low = (text or "").lower()
    for seconds, keys in _STATED_LENGTHS:
        if any(k in low for k in keys):
            return seconds
    return None


# Scored formats and what one typically carries when the brief does not say. These are
# floors chosen deliberately low: an assumed scope that quotes HIGH loses the job on a
# number nobody asked for, and an estimate is a starting point for the spotting session,
# not a substitute for it. Series minutes/cues are PER EPISODE.
SCORED_FORMATS = (
    ("series", ("series", "episodic", "episode", "season", "showrunner"),
     {"label": "Episodic series", "minutes": 8.0, "cues": 6, "per_episode": True}),
    ("documentary", ("documentary", "docuseries", "doc feature"),
     {"label": "Documentary", "minutes": 30.0, "cues": 20, "per_episode": False}),
    ("short", ("short film", "short-form film", "student film"),
     {"label": "Short film", "minutes": 8.0, "cues": 6, "per_episode": False}),
    ("game", ("video game", "game score", "gameplay", "interactive score"),
     {"label": "Game", "minutes": 20.0, "cues": 15, "per_episode": False}),
    ("feature", ("feature film", "feature-length", "motion picture", "narrative feature",
                 "original score for a film", "film score"),
     {"label": "Feature film", "minutes": 40.0, "cues": 25, "per_episode": False}),
)

_NUM = r"(\d+(?:\.\d+)?)"
_RANGE = r"(?:\s*(?:-|–|—|to)\s*" + _NUM + r")?"
_MINUTES_RE = re.compile(_NUM + _RANGE + r"\s*(?:minutes?|mins?)\b")
_CUES_RE = re.compile(_NUM + _RANGE + r"\s*cues?\b")
_EPISODES_RE = re.compile(_NUM + r"\s*(?:x\s*)?(?:-\s*)?episodes?\b")
_PER_EPISODE = ("per episode", "an episode", "/episode", "per ep", "each episode")


def _first_quantity(rx: re.Pattern, text: str) -> Optional[float]:
    """The quantity the brief states, taking the MIDPOINT of a stated range.

    "20-30 cues" is 25, not 30. Quoting the top of every range someone writes down
    biases every estimate high, and the confidence band already covers the spread.
    """
    m = rx.search(text)
    if m is None:
        return None
    low = float(m.group(1))
    high = float(m.group(2)) if m.lastindex and m.lastindex >= 2 and m.group(2) else None
    return (low + high) / 2.0 if high else low


@dataclass
class Scope:
    """How much music, and where the number came from.

    ``minutes_stated`` / ``cues_stated`` exist because of the honesty rule: an assumed
    forty minutes must never be presented as a measured forty minutes. Every surface
    that shows a scored estimate says which it is.
    """
    kind: str                      # "campaign" | "scored"
    fmt: str = ""                  # feature | series | documentary | short | game
    label: str = ""
    minutes: float = 0.0
    cues: int = 0
    episodes: int = 0
    minutes_stated: bool = False
    cues_stated: bool = False

    @property
    def is_scored(self) -> bool:
        return self.kind == "scored"

    @property
    def summary(self) -> str:
        if not self.is_scored:
            return "Campaign cue"
        ep = f"{self.episodes} episodes · " if self.episodes else ""
        m = f"{self.minutes:g} min of score" + ("" if self.minutes_stated else " (assumed)")
        c = f"{self.cues} cues" + ("" if self.cues_stated else " (assumed)")
        return f"{self.label} · {ep}{m} across {c}"


# A format word alone is not enough. "Episode" turns up in podcast briefs, "series"
# in campaign briefs ("the series of six spots"), and misreading either would swap a
# campaign onto a model that prices in tens of minutes. BOTH a format and a scoring
# signal have to be present, which costs a few briefs a manual reclassification and
# buys the guarantee that no campaign is ever quoted as a feature.
_SCORING_SIGNALS = ("score", "scoring", "cue", "underscore", "spotting", "composer")


def infer_scope(text: str) -> Scope:
    """Read the amount of music out of a brief.

    A brief is scored media when it says so twice — a format and a scoring signal.
    Nothing is inferred from a minutes figure alone: a campaign brief saying "2 minute
    edit" is still a campaign, so the FORMAT decides the model and the numbers only
    fill it in.
    """
    low = (text or "").lower()
    if not any(s in low for s in _SCORING_SIGNALS):
        return Scope(kind="campaign")
    hit = next((f for f in SCORED_FORMATS if any(k in low for k in f[1])), None)
    if hit is None:
        return Scope(kind="campaign")
    fmt, _keys, spec = hit

    episodes = _first_quantity(_EPISODES_RE, low)
    episodes = int(episodes) if episodes else 0

    stated_minutes = _first_quantity(_MINUTES_RE, low)
    minutes_stated = stated_minutes is not None
    if minutes_stated and episodes and any(k in low for k in _PER_EPISODE):
        stated_minutes = stated_minutes * episodes          # "6 minutes per episode" × 10
    minutes = stated_minutes if minutes_stated else (
        spec["minutes"] * episodes if spec["per_episode"] and episodes else spec["minutes"])

    stated_cues = _first_quantity(_CUES_RE, low)
    cues_stated = stated_cues is not None
    if cues_stated and episodes and any(k in low for k in _PER_EPISODE):
        stated_cues = stated_cues * episodes
    cues = stated_cues if cues_stated else (
        spec["cues"] * episodes if spec["per_episode"] and episodes else spec["cues"])

    return Scope(kind="scored", fmt=fmt, label=spec["label"],
                 minutes=float(minutes), cues=int(round(cues)), episodes=episodes,
                 minutes_stated=minutes_stated, cues_stated=cues_stated)


def _infer_duration(text: str) -> Multiplier:
    """Longest mention wins.

    This used to test ``:15`` first, so a brief reading ":60 anthem with :30 and
    :15 cutdowns" was classified as a :15 spot and priced at HALF the bare :30 —
    enumerating the deliverables made the job cheaper. Real campaign briefs
    always list their cutdown suite, so the bug fired on the biggest jobs.
    """
    if any(k in text for k in (":120", "2-minute", "two minute", "long form")):
        return Multiplier("Duration", ":120 / long form", 1.6)
    if any(k in text for k in (":60", "60-second", "60 second", "anthem")):
        return Multiplier("Duration", ":60 / anthem", 1.25)
    if any(k in text for k in (":30", "30-second", "30 second")):
        return Multiplier("Duration", ":30 spot", 1.0)
    if any(k in text for k in (":15", ":06", "15-second", "15 second")):
        return Multiplier("Duration", ":15 spot", 0.8)
    return Multiplier("Duration", ":30 spot (assumed)", 1.0)


def _cutdown_count(text: str) -> int:
    """Cutdowns are additive scope — each is a conform, a mix and a master, not a
    reason to reclassify the whole job as its shortest deliverable."""
    return sum(1 for k in (":60", ":30", ":15", ":06") if k in text)


def _infer_instrumentation(text: str) -> tuple:
    """Returns (Multiplier for writing complexity, session package key).

    Writing for an orchestra genuinely takes longer at the desk — but only a
    little longer, and the players are a separate line. The old flat ×4 was
    standing in for a recording budget that was never actually priced.
    """
    if "full orchestra" in text or "orchestral" in text or "orchestra" in text:
        key = "orchestral"
    elif any(k in text for k in ("hybrid", "ensemble", "strings", "band", "live players")):
        key = "hybrid"
    else:
        key = "simple"
    pkg = SESSION_PACKAGES[key]
    return Multiplier("Instrumentation", pkg["label"], pkg["complexity"]), key


def _session_cost(key: str, duration_factor: float) -> float:
    """Players + room, scaled by how much music is being recorded."""
    pkg = SESSION_PACKAGES[key]
    players = pkg["players"] * pkg["player_fee"]
    return (players + pkg["studio"] + pkg["extras"]) * duration_factor


# Finished minutes a date yields. A campaign cue is one session whatever happens; a
# 45-minute score is a booking schedule, and pretending otherwise is what let a feature
# cost the same session line as a :30. An orchestra covers less ground per hour than a
# quartet — more players to fix, more takes to comp.
MINUTES_PER_SESSION: Dict[str, float] = {"simple": 30.0, "hybrid": 20.0, "orchestral": 12.0}

# ORCHESTRAL WRITING IS NOT THE SAME PURCHASE AS HIRING AN ORCHESTRA, and conflating
# them is why an indie feature carried a studio's budget: the single word "orchestra"
# in a brief bought both the orchestration hours AND thirty players on every date. It
# should only ever have bought the first. Instrumentation stays a DESK factor — writing
# for an orchestra genuinely takes longer — and the players are now explicit scope with
# their own evidence, defaults and assumed-flags, exactly like the minutes.
#
# A sampled orchestral score is a real and common way this work is delivered. It has
# the full orchestration cost and NO session cost, and until now the engine could not
# express it at all.
_ENSEMBLE_WORDS = {"solo": 1, "duo": 2, "trio": 3, "quartet": 4, "quintet": 5,
                   "sextet": 6, "septet": 7, "octet": 8, "nonet": 9}
_PLAYERS_RE = re.compile(_NUM + r"\s*(?:-|–|—)?\s*(?:piece|players?|musicians?)\b")
_DATES_RE = re.compile(
    _NUM + r"\s*(?:recording|session|tracking|studio)?\s*(?:dates?|sessions?|days?)\b")
# Said outright: no players are being booked.
_SAMPLED = ("sampled", "samples", "virtual instrument", "in the box", "no live",
            "programmed", "midi mock", "library instrument", "synth only")
# Said outright: players ARE being booked.
_LIVE = ("live player", "live orchestra", "live strings", "live ensemble", "live band",
         "session player", "session musician", "recording session", "scoring stage",
         "tracking date", "musicians", "-piece", " piece orchestra")


@dataclass
class Session:
    """Who is actually being paid to play, and on how many dates.

    Every field carries whether the brief said so. The session is routinely half the
    cost of a scored engagement, so an assumed thirty players is a bigger guess than
    anything else in the estimate and has to read as a guess.
    """
    live: bool = True
    players: int = 0
    dates: int = 0
    player_fee: float = 0.0
    room_cost: float = 0.0
    players_stated: bool = False
    dates_stated: bool = False
    live_stated: bool = False
    label: str = ""

    @property
    def cost(self) -> float:
        if not self.live:
            return 0.0
        return (self.players * self.player_fee + self.room_cost) * self.dates

    @property
    def summary(self) -> str:
        if not self.live:
            return ("Sampled / programmed · no players booked"
                    + ("" if self.live_stated else " (assumed)"))
        p = f"{self.players} players" + ("" if self.players_stated else " (assumed)")
        d = f"{self.dates} date{'s' if self.dates != 1 else ''}" + (
            "" if self.dates_stated else " (assumed)")
        return f"{p} × {d}"


def _stated_players(text: str) -> Optional[int]:
    """A player count the brief actually gives — "30-piece", "12 musicians", or a
    named chamber ensemble. Never inferred from the style word."""
    n = _first_quantity(_PLAYERS_RE, text)
    if n:
        return int(n)
    for word, count in _ENSEMBLE_WORDS.items():
        if word in text:
            return count
    return None


def infer_session(text: str, key: str, minutes: float) -> Session:
    """The recording session as its own scope, not a side effect of a style word."""
    pkg = SESSION_PACKAGES[key]
    sampled = any(k in text for k in _SAMPLED)
    live_said = any(k in text for k in _LIVE)
    live = not sampled
    players = _stated_players(text)
    dates = _first_quantity(_DATES_RE, text)
    return Session(
        live=live,
        players=players if players is not None else pkg["players"],
        dates=int(dates) if dates else max(1, math.ceil(minutes / MINUTES_PER_SESSION[key])),
        player_fee=pkg["player_fee"],
        room_cost=pkg["studio"] + pkg["extras"],
        players_stated=players is not None,
        dates_stated=bool(dates),
        # Naming a player count or booking a date IS saying the players are live — a
        # brief reading "string quartet over 2 recording dates" has answered the
        # question, and asking the operator to confirm it again is noise that teaches
        # them to stop reading the warnings that matter.
        live_stated=bool(sampled or live_said or players is not None or dates),
        label=pkg["label"],
    )


def _infer_usage(text: str) -> Multiplier:
    if any(k in text for k in ("global", "worldwide", "international")):
        return Multiplier("Usage / licence", "Global", USAGE_FACTORS["global"], applies="price")
    if any(k in text for k in ("national", "nationwide", "broadcast")):
        return Multiplier("Usage / licence", "National", USAGE_FACTORS["national"], applies="price")
    return Multiplier("Usage / licence", "Local / social (assumed)", USAGE_FACTORS["local"],
                      applies="price")


def _revisions(text: str) -> Multiplier:
    if "3 rounds" in text or "three rounds" in text:
        return Multiplier("Revisions", "3 rounds (+30%)", 1.30)
    if "1 round" in text or "one round" in text:
        return Multiplier("Revisions", "1 round (baseline)", 1.0)
    return Multiplier("Revisions", "2 rounds assumed (+15%)", 1.15)


def _override_line(role: str, hours: float, override: dict) -> RoleLine:
    """Build a role line whose rate/cost come from an assigned talent's rate.

    ``override`` = {"rate": float, "unit": "hourly"|"day"|"project"}. Conversions:
      hourly  → cost = hours × rate (line behaves like a normal hourly line)
      day     → days = max(1, ceil(hours/8)); cost = days × rate
      project → flat: cost = rate (replaces the line cost regardless of hours)
    """
    rate = float(override["rate"])
    unit = (override.get("unit") or "hourly").lower()
    if unit == "day":
        days = max(1, math.ceil(hours / 8.0))
        return RoleLine(role, hours, rate, cost_override=days * rate, unit="day")
    if unit == "project":
        return RoleLine(role, hours, rate, cost_override=rate, unit="project")
    # hourly (default): plain hours × rate, no explicit override needed.
    return RoleLine(role, hours, rate, unit="hourly")


def build_estimate(
    opp: Opportunity,
    team_shape: List[str],
    discipline: MusicDiscipline,
    rate_overrides: Optional[Dict[str, dict]] = None,
) -> Estimate:
    """Produce a Phase-1 expert estimate (point + confidence band) for an opp.

    ``rate_overrides`` maps {role_name: {"rate": float, "unit": ...}}. When a
    role is present, its line rate/cost are computed from that assigned-talent
    rate instead of the global default — this is how an assigned creator's real
    cost flows into the project proposal. Absent (the default), the estimate is
    identical to the pre-feature behaviour.
    """
    text = f"{opp.need} {opp.description} {' '.join(opp.tags)}".lower()

    roles = list(team_shape) if team_shape else ["Composer", "Mixer"]
    if "Project Manager" not in roles:
        roles = roles + ["Project Manager"]

    scope = infer_scope(text)
    instrumentation, session_key = _infer_instrumentation(text)
    usage = _infer_usage(text)
    revisions = _revisions(text)

    overrides = rate_overrides or {}
    lines = []
    for role in roles:
        # Scored media is bought by the minute plus the cue; a campaign cue is the
        # per-cue prior. Same role lines, a different unit of scope.
        if scope.is_scored:
            hours = (MINUTE_HOURS.get(role, 1.0) * scope.minutes
                     + CUE_HOURS.get(role, 0.0) * scope.cues)
        else:
            hours = ROLE_HOURS.get(role, 4.0)
        if role in overrides and overrides[role] and overrides[role].get("rate") is not None:
            lines.append(_override_line(role, hours, overrides[role]))
        else:
            lines.append(RoleLine(role, hours, ROLE_RATES.get(role, 100.0)))
    base_cost = sum(line.cost for line in lines)

    session_dates = 0
    session = None
    if scope.is_scored:
        # Duration and cutdowns are spot-shaped ideas: there is no ":30" on a feature,
        # and the "cutdown suite" is the deliverable list of a campaign. The scope has
        # already priced the amount of music, so applying a duration factor on top
        # would count the same thing twice.
        multipliers = [instrumentation, usage, revisions]
        multiplier_total = instrumentation.factor * revisions.factor
        session = infer_session(text, session_key, scope.minutes)
        session_cost, session_dates = session.cost, session.dates
    else:
        duration = _infer_duration(text)
        cutdowns = _cutdown_count(text)
        # Each additional deliverable length is a conform + mix + master pass.
        cutdown_factor = 1.0 + 0.12 * max(0, cutdowns - 1)
        multipliers = [duration, instrumentation, usage, revisions]
        if cutdowns > 1:
            multipliers.append(
                Multiplier("Cutdowns", f"{cutdowns} lengths (+{(cutdown_factor - 1) * 100:.0f}%)",
                           cutdown_factor))
        multiplier_total = (duration.factor * instrumentation.factor
                            * cutdown_factor * revisions.factor)
        session_cost = _session_cost(session_key, duration.factor)

    # Desk work scales with how much music and how complex it is; the revision
    # budget scales the desk only — you do not re-book the orchestra to change a
    # note. Every factor shown in `multipliers` is applied here except usage,
    # which is a fee on the price rather than a cost of production.
    desk_cost = base_cost * multiplier_total
    revision_uplift = base_cost * (multiplier_total / revisions.factor) * (revisions.factor - 1.0)
    estimated_cost = desk_cost + session_cost

    # Usage is a rights fee, applied to the price. Rolling it into cost (as a
    # 1.2× on a national licence) implied a wider licence cost more to produce
    # and quietly inflated the margin calculation.
    suggested_price = (estimated_cost / (1.0 - TARGET_MARGIN)) * usage.factor
    expected_margin_pct = TARGET_MARGIN * 100.0

    cost_low = estimated_cost * (1.0 - BAND_SPREAD)
    cost_high = estimated_cost * (1.0 + BAND_SPREAD)

    disclosed = opp.budget_display() if opp.budget_disclosed else None
    delta_note = "No disclosed budget to compare against."
    mid = opp.budget_midpoint
    if mid is not None:
        if suggested_price <= mid:
            delta_note = (
                f"Suggested price ${suggested_price:,.0f} fits within the disclosed "
                f"budget (~${mid:,.0f}), with healthy room."
            )
        else:
            delta_note = (
                f"Suggested price ${suggested_price:,.0f} exceeds the disclosed "
                f"midpoint (~${mid:,.0f}); scope down or justify the premium."
            )

    return Estimate(
        discipline=discipline,
        lines=lines,
        multipliers=multipliers,
        base_cost=base_cost,
        multiplier_total=multiplier_total,
        revision_uplift=revision_uplift,
        estimated_cost=estimated_cost,
        suggested_price=suggested_price,
        expected_margin_pct=expected_margin_pct,
        disclosed_budget=disclosed,
        budget_delta_note=delta_note,
        cost_low=cost_low,
        cost_high=cost_high,
        session_cost=session_cost,
        session_label=SESSION_PACKAGES[session_key]["label"],
        band_spread_pct=BAND_SPREAD * 100.0,
        scope=scope if scope.is_scored else None,
        # The writer's fee follows the PRICE, so it is computed from the number the
        # client is actually quoted, net of the session money that passes through to
        # players and the room (ADR-0061).
        writer_fee=compensation.writer_fee(
            suggested_price, session_cost,
            writers=max(1, sum(1 for r in roles if r.lower() in _WRITER_ROLE_NAMES)),
            # The uplift is for ORCHESTRATING — scoring out the parts — which is a
            # second job whether those parts are played by people or by samples.
            # `live_session` only decides what the fee is called; claiming a composer
            # produced a session that never happened is a false reason for a real fee.
            orchestrates=(scope.is_scored and session_key == "orchestral"),
            live_session=bool(session is not None and session.live)),
        session=session,
        session_dates=session_dates,
        assumptions=_assumptions(scope, session, session_key),
    )


def _assumptions(scope: Scope, session: Optional[Session], session_key: str) -> List[str]:
    """What this estimate is standing on, said out loud.

    The scored lines are not decoration. An assumed forty minutes of score is a
    guess about the single biggest driver of the number, and a client reading a
    quote is entitled to know which figures came out of their brief.
    """
    common = [
        "Phase 1: expert priors only; NOT calibrated on Chordential actuals.",
        "Session line pays players and the room; usage is a rights fee on the price, not a cost.",
        "Rates are assumed blended $/hr; replace with AFM / SAG-AFTRA / market data (Phase 2).",
        f"Target gross margin {TARGET_MARGIN:.0%} applied to suggested price.",
        f"Confidence band ±{BAND_SPREAD:.0%} (uncalibrated), narrowing as actuals accrue.",
    ]
    if not scope.is_scored:
        return common[:1] + [
            "Role hours cover one campaign cue end to end (brief, demos, revisions, stems, versions).",
        ] + common[1:] + [
            "Unstated duration/instrumentation/revisions default to the documented baseline.",
        ]
    guessed = [w for w, ok in (
        ("minutes of score", scope.minutes_stated),
        ("cue count", scope.cues_stated),
        ("player count", session is None or session.players_stated or not session.live),
        ("number of recording dates", session is None or session.dates_stated
         or not session.live),
        ("whether players are live or sampled", session is None or session.live_stated),
    ) if not ok]
    out = common[:1] + [
        f"Scope: {scope.summary}.",
        "Priced per finished minute of score plus a per-cue allowance for spotting, "
        "revisions and delivery, not by spot length.",
        f"Writing style is {SESSION_PACKAGES[session_key]['label'].lower()}; the "
        "players are costed separately, so a sampled orchestral score carries the "
        "orchestration hours and no session.",
    ]
    if session is not None:
        out.append(
            f"Recording: {session.summary}."
            + (f" Dates assume {MINUTES_PER_SESSION[session_key]:g} finished minutes "
               f"per date." if session.live and not session.dates_stated else ""))
    out += common[1:]
    if guessed:
        out.append(
            "ASSUMED, not stated in the brief: " + "; ".join(guessed)
            + ". Confirm at spotting before this becomes an offer.")
    out.append(
        "Per-minute hours are LINEAR: thematic reuse should make a long score cheaper "
        "per minute, and that discount is not modelled yet.")
    return out


class EstimationEngine:
    """Phase-1 expert estimator. Mirrors the QualificationEngine/ScoringEngine shape.

    Derives the team from the qualification discipline when one isn't supplied,
    so callers can estimate straight off a qualification result.
    """

    def estimate(
        self,
        opp: Opportunity,
        team_shape: Optional[List[str]] = None,
        discipline: Optional[MusicDiscipline] = None,
        rate_overrides: Optional[Dict[str, dict]] = None,
    ) -> Estimate:
        discipline = discipline or MusicDiscipline.COMPOSITION
        team_shape = team_shape or discipline.team_shape
        return build_estimate(opp, team_shape, discipline, rate_overrides)
