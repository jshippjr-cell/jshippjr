"""The qualification layer — the Head of Production's gate.

Runs *before* Rank is trusted (see ``docs/qualification-spec.md``). Where the
:mod:`scoring` engine answers "how attractive and winnable is this?", this module
answers "is this real, original, *Chordential-shaped* music craft at all — and how
well does it fit?" It can **hard-reject** junk the scorer would otherwise rank.

Pipeline per opportunity:

* **Stage 0 — hard disqualifiers** (deterministic, cheap): cover bands, karaoke,
  DJs, playlists, lessons, gear, finished-music-needs-distribution, and
  ``MusicRequirement.NONE``. Short-circuits to a ``Pass`` verdict; no LLM spend.
* **Stage 1 — discipline classification**: which music craft (composition / sonic
  branding / sound design / arrangement / supervision / licensing / non-craft).
* **Stage 2 — qualification rubric**: five weighted scorers → the 0-100
  ``alignment_pct`` (the "87% aligned" number) plus a generated ``fit_summary``.

Weights are versioned, editable config (``QUALIFICATION_WEIGHTS``), mirroring the
scoring engine so the Head of Production can retune the gate without code changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

from .models import (
    BuyerType,
    Confidence,
    MusicDiscipline,
    MusicRequirement,
    Opportunity,
    QualificationAction,
    QualificationResult,
    ScoreBreakdown,
)

# A qualification scorer returns (normalized [0,1], human-readable note).
QScorer = Callable[["_QContext"], Tuple[float, str]]

# Alignment >= this and high confidence -> real-time alert (Pursue).
# Starts conservative (precision-biased, Decision #3) and is only lowered as the
# classifier's human-agreement rate proves out.
ALERT_FLOOR = 70.0
# Qualified work scoring at/above this (but not alertable) goes to the review queue.
REVIEW_FLOOR = 50.0
# Budget that clears Chordential's A-tier economics.
BUDGET_FLOOR = 5_000.0


# --------------------------------------------------------------------------- #
# Stage 0 — hard disqualifiers (the junk gate)
# --------------------------------------------------------------------------- #
# Each phrase maps to the reason surfaced on the verdict. Matched as spaced
# tokens against the normalized text so "dj" doesn't fire inside "adjust".
_HARD_DISQUALIFIERS: Dict[str, str] = {
    "cover band": "Cover band — not original craft",
    "tribute band": "Tribute act — not original craft",
    "tribute act": "Tribute act — not original craft",
    "wedding band": "Wedding/party band — not original craft",
    "party band": "Wedding/party band — not original craft",
    "wedding singer": "Wedding performer — not original craft",
    "karaoke": "Karaoke service — not original craft",
    "sing-along": "Karaoke/sing-along — not original craft",
    "dj": "DJ booking — performance, not creation",
    "disc jockey": "DJ booking — performance, not creation",
    "playlist": "Playlist curation — not original craft",
    "spotify playlist": "Playlist curation — not original craft",
    "music lessons": "Music lessons/teaching — not Chordential-shaped",
    "music lesson": "Music lessons/teaching — not Chordential-shaped",
    "music teacher": "Music teaching — not Chordential-shaped",
    "music tutor": "Music tutoring — not Chordential-shaped",
    "guitar lessons": "Music lessons — not Chordential-shaped",
    "piano lessons": "Music lessons — not Chordential-shaped",
    "vocal coach": "Vocal coaching — not Chordential-shaped",
    "instrument rental": "Gear/equipment — not music creation",
    "equipment rental": "Gear/equipment — not music creation",
    "gear for sale": "Gear/equipment — not music creation",
    "music distribution": "Distribution only — no creation",
    "playlist pitching": "Playlist pitching — not original craft",
}

# Soft flags: do not auto-fail, but cap alignment and force a human look.
_SOFT_FLAG_KEYWORDS: Dict[str, str] = {
    "background music": "Reads as background/library music, not original craft",
    "royalty-free": "Royalty-free/library request — verify original need",
    "stock music": "Stock-music request — verify original need",
    "library music": "Library-music request — verify original need",
}

# --------------------------------------------------------------------------- #
# Stage 1 — discipline keyword sets
# --------------------------------------------------------------------------- #
_SONIC_BRANDING_KW = (
    "sonic brand", "sonic branding", "sonic logo", "sonic identity",
    "audio brand", "audio identity", "mnemonic", "sound logo", "audio logo",
)
_SOUND_DESIGN_KW = (
    "sound design", "sound designer", "sfx", "sound effects", "foley",
    "ambience", "soundscape",
)
_SUPERVISION_KW = (
    "music supervis", "music supervisor", "sync placement", "song placement",
    "needle drop", "clear a track", "license a song",
)
_ARRANGEMENT_KW = (
    "arrange", "arranger", "arrangement", "orchestrat", "transcrib", "re-score",
)
_COMPOSITION_KW = (
    "compose", "composer", "original score", "original music", "custom music",
    "custom score", "original composition", "write music", "underscore", "jingle",
    "theme music",
)
_LICENSING_KW = ("license", "licensed", "pre-existing", "existing track", "catalog")

# Clearance-risk markers (lower the "clearable" score).
_CLEARANCE_RISK_KW = (
    "master rights", "sample clearance", "clear samples", "existing song",
    "cover of", "famous song", "hit song", "well-known song", "needle drop",
)

# Specificity markers that signal a real, concrete brief.
_BRIEF_SPECIFIC_KW = (
    ":15", ":30", ":60", "spot", "campaign", "trailer", "score", "film", "series",
    "episode", "ad", "commercial", "video", "broadcast", "cutdown", "deliverable",
    "seconds", "minute",
)


def _text(opp: Opportunity) -> str:
    return f"{opp.need} {opp.description} {' '.join(opp.tags)}".lower()


def _spaced(text: str) -> str:
    """Pad with spaces so token lookups match on word boundaries."""
    return f" {text} "


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@dataclass
class _QContext:
    """Resolved inputs shared by the Stage 2 scorers (computed once per opp)."""

    opp: Opportunity
    text: str
    discipline: MusicDiscipline
    secondary: List[MusicDiscipline]


# --------------------------------------------------------------------------- #
# Stage 0
# --------------------------------------------------------------------------- #
def hard_disqualifiers(opp: Opportunity) -> List[str]:
    """Return the list of hard-fail reasons (empty if it clears the gate)."""
    reasons: List[str] = []
    spaced = _spaced(_text(opp))
    for phrase, reason in _HARD_DISQUALIFIERS.items():
        if f" {phrase} " in spaced or f" {phrase}," in spaced or f" {phrase}." in spaced:
            if reason not in reasons:
                reasons.append(reason)
    if opp.music_requirement is MusicRequirement.NONE:
        reasons.append("No music need stated")
    return reasons


def soft_flags(opp: Opportunity) -> List[str]:
    """Non-fatal concerns that cap alignment and force review."""
    flags: List[str] = []
    text = _text(opp)
    for phrase, note in _SOFT_FLAG_KEYWORDS.items():
        if phrase in text and note not in flags:
            flags.append(note)
    return flags


# --------------------------------------------------------------------------- #
# Stage 1 — discipline classification
# --------------------------------------------------------------------------- #
def classify_discipline(opp: Opportunity) -> Tuple[MusicDiscipline, List[MusicDiscipline]]:
    """Classify the primary discipline (+ any secondary tags).

    Explicit signals win: ``sonic_branding`` flag and ``MusicRequirement`` are
    honored before falling back to keyword inference (mirrors the scorer's
    resolver pattern). Specific disciplines outrank generic composition so a
    sonic-branding job is labeled as such, not as plain composition.
    """
    if opp.music_requirement is MusicRequirement.NONE:
        return MusicDiscipline.NON_CRAFT, []

    text = _text(opp)
    detected: List[MusicDiscipline] = []

    if opp.sonic_branding is True or any(k in text for k in _SONIC_BRANDING_KW):
        detected.append(MusicDiscipline.SONIC_BRANDING)
    if any(k in text for k in _SOUND_DESIGN_KW):
        detected.append(MusicDiscipline.SOUND_DESIGN)
    if any(k in text for k in _SUPERVISION_KW):
        detected.append(MusicDiscipline.SUPERVISION)
    if any(k in text for k in _ARRANGEMENT_KW):
        detected.append(MusicDiscipline.ARRANGEMENT)
    if opp.music_requirement is MusicRequirement.ORIGINAL or any(
        k in text for k in _COMPOSITION_KW
    ):
        detected.append(MusicDiscipline.COMPOSITION)
    if opp.music_requirement is MusicRequirement.LICENSED or any(
        k in text for k in _LICENSING_KW
    ):
        detected.append(MusicDiscipline.LICENSING)

    if not detected:
        # Music implied but no discipline signal — treat as (weak) composition,
        # to be confirmed by a human; the low confidence will route it to review.
        return MusicDiscipline.COMPOSITION, []

    # Primary by specificity priority (most specific / highest-craft first).
    priority = [
        MusicDiscipline.SONIC_BRANDING,
        MusicDiscipline.SOUND_DESIGN,
        MusicDiscipline.SUPERVISION,
        MusicDiscipline.ARRANGEMENT,
        MusicDiscipline.COMPOSITION,
        MusicDiscipline.LICENSING,
    ]
    primary = next(d for d in priority if d in detected)
    secondary = [d for d in detected if d is not primary]
    return primary, secondary


# --------------------------------------------------------------------------- #
# Stage 2 — the five rubric scorers (Head of Production's gate questions)
# --------------------------------------------------------------------------- #
def score_real_brief(ctx: _QContext) -> Tuple[float, str]:
    """#1 — Is there a concrete creative deliverable, or just 'need music'?"""
    opp = ctx.opp
    signals = 0
    if len(opp.description.strip()) >= 25:
        signals += 1
    if any(k in ctx.text for k in _BRIEF_SPECIFIC_KW):
        signals += 1
    if opp.tags:
        signals += 1
    if len(opp.need.split()) >= 3:
        signals += 1
    norm = _clamp(signals / 4.0)
    if norm >= 0.75:
        return norm, "Concrete brief (format/deliverable described)"
    if norm <= 0.25:
        return norm, "Vague brief — no clear deliverable"
    return norm, "Partial brief — some detail, some gaps"


def score_craft_fit(ctx: _QContext) -> Tuple[float, str]:
    """#2 — Original / Chordential-shaped craft? (weighted heaviest)."""
    d = ctx.discipline
    return d.fit_weight, f"{d.label} ({'core' if d.fit_weight >= 1.0 else 'adjacent'} craft)"


def score_budget_signal(ctx: _QContext) -> Tuple[float, str]:
    """#3 — Is there money, and does it clear the floor?"""
    mid = ctx.opp.budget_midpoint
    if mid is None:
        return 0.4, "Budget undisclosed (neutral — confirm before pursuit)"
    if mid >= BUDGET_FLOOR:
        return 1.0, f"Budget ~${mid:,.0f} clears the ${BUDGET_FLOOR:,.0f} floor"
    return _clamp(0.3 + 0.6 * (mid / BUDGET_FLOOR)), f"Budget ~${mid:,.0f} below floor"


def score_clearable(ctx: _QContext) -> Tuple[float, str]:
    """#4 — Are the rights / licensing realistic?"""
    if any(k in ctx.text for k in _CLEARANCE_RISK_KW):
        return 0.35, "Third-party / master-rights clearance risk"
    if ctx.discipline is MusicDiscipline.LICENSING:
        return 0.55, "Licensing — clearance effort but workable"
    if ctx.discipline in (
        MusicDiscipline.COMPOSITION,
        MusicDiscipline.SONIC_BRANDING,
        MusicDiscipline.SOUND_DESIGN,
        MusicDiscipline.ARRANGEMENT,
    ):
        return 0.95, "Original work — clean to clear"
    return 0.7, "No clearance red flags"


def score_on_craft_buyer(ctx: _QContext) -> Tuple[float, str]:
    """#5 — Is the buyer type consistent with real music spend?"""
    return {
        BuyerType.AGENCY: (1.0, "Agency buyer — real creative spend"),
        BuyerType.BRAND: (1.0, "Brand buyer — real creative spend"),
        BuyerType.PRODUCTION_COMPANY: (0.9, "Production-company buyer"),
        BuyerType.GOVERNMENT: (0.5, "Government buyer — procurement-heavy"),
        BuyerType.EDUCATIONAL: (0.5, "Educational buyer — procurement-heavy"),
        BuyerType.UNKNOWN: (0.4, "Buyer type unknown"),
    }[ctx.opp.buyer_type]


# Default rubric weights (sum to 100). Editable via config (see from_config).
QUALIFICATION_WEIGHTS: Dict[str, float] = {
    "Real Brief": 25,
    "Craft Fit": 30,
    "Budget Signal": 20,
    "Clearable": 15,
    "On-Craft Buyer": 10,
}

_QSCORERS: Dict[str, QScorer] = {
    "Real Brief": score_real_brief,
    "Craft Fit": score_craft_fit,
    "Budget Signal": score_budget_signal,
    "Clearable": score_clearable,
    "On-Craft Buyer": score_on_craft_buyer,
}

# Thresholds (mirror scoring.py conventions).
_REASON_THRESHOLD = 0.75
_GAP_THRESHOLD = 0.45


class QualificationEngine:
    """Qualifies, classifies, and aligns opportunities before they are ranked."""

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        alert_floor: float = ALERT_FLOOR,
        review_floor: float = REVIEW_FLOOR,
    ) -> None:
        self.weights = weights or QUALIFICATION_WEIGHTS
        for name in self.weights:
            if name not in _QSCORERS:
                raise ValueError(f"No qualification scorer registered for {name!r}")
        self.alert_floor = alert_floor
        self.review_floor = review_floor

    @classmethod
    def from_config(cls, path: str, **kwargs) -> "QualificationEngine":
        with open(path, "r", encoding="utf-8") as handle:
            weights = json.load(handle)
        return cls(weights=weights, **kwargs)

    @property
    def total_weight(self) -> float:
        return sum(self.weights.values())

    def qualify(self, opp: Opportunity, human_confirmed: bool = False) -> QualificationResult:
        # --- Stage 0: hard gate ---
        disqualifiers = hard_disqualifiers(opp)
        if disqualifiers:
            return QualificationResult(
                qualified=False,
                discipline=MusicDiscipline.NON_CRAFT,
                alignment_pct=0.0,
                fit_summary=f"Disqualified — {disqualifiers[0]}. → Pass.",
                recommended_action=QualificationAction.PASS,
                confidence=Confidence.HIGH,
                needs_human_review=False,
                disqualifiers=disqualifiers,
                team_shape=[],
            )

        # --- Stage 1: discipline ---
        discipline, secondary = classify_discipline(opp)
        ctx = _QContext(opp=opp, text=_text(opp), discipline=discipline, secondary=secondary)

        # --- Stage 2: rubric ---
        breakdown: List[ScoreBreakdown] = []
        reasons: List[str] = []
        gaps: List[str] = []
        for name, weight in self.weights.items():
            normalized, note = _QSCORERS[name](ctx)
            normalized = _clamp(normalized)
            breakdown.append(ScoreBreakdown(name, float(weight), normalized, note))
            if normalized >= _REASON_THRESHOLD:
                reasons.append(note)
            elif normalized <= _GAP_THRESHOLD:
                gaps.append(note)

        raw = sum(b.points for b in breakdown)
        alignment = round(raw * 100.0 / (self.total_weight or 1.0), 1)

        # Soft flags cap alignment and force review.
        flags = soft_flags(opp)
        if flags:
            alignment = min(alignment, 60.0)
            gaps.extend(flags)

        confidence = self._confidence(opp, discipline, ctx)
        needs_review = (
            confidence is Confidence.LOW or bool(flags) or self.review_floor <= alignment < self.alert_floor
        )
        action = self._route(alignment, confidence, needs_review, human_confirmed)

        return QualificationResult(
            qualified=True,
            discipline=discipline,
            alignment_pct=alignment,
            fit_summary=self._summary(opp, discipline, alignment, action, reasons, gaps),
            recommended_action=action,
            confidence=confidence,
            needs_human_review=needs_review,
            fit_reasons=reasons or ["Meets baseline craft fit"],
            disqualifiers=[],
            gaps=gaps or ["No major gaps"],
            secondary_disciplines=secondary,
            team_shape=discipline.team_shape,
            breakdown=breakdown,
        )

    def qualify_batch(self, opps: List[Opportunity]) -> List[QualificationResult]:
        return [self.qualify(o) for o in opps]

    # ------------------------------------------------------------------ #
    def _confidence(
        self, opp: Opportunity, discipline: MusicDiscipline, ctx: _QContext
    ) -> Confidence:
        """High when the deciding signals were explicit, Low when inferred."""
        explicit = 0
        if opp.music_requirement is not MusicRequirement.IMPLIED:
            explicit += 1
        if opp.buyer_type is not BuyerType.UNKNOWN:
            explicit += 1
        if opp.budget_disclosed:
            explicit += 1
        if opp.commercial_campaign is not None or opp.sonic_branding is not None:
            explicit += 1
        # Discipline inferred from a bare implied need is the weakest case.
        if opp.music_requirement is MusicRequirement.IMPLIED and not ctx.secondary:
            explicit = min(explicit, 1)
        if explicit >= 3:
            return Confidence.HIGH
        if explicit == 2:
            return Confidence.MEDIUM
        return Confidence.LOW

    def _route(
        self,
        alignment: float,
        confidence: Confidence,
        needs_review: bool,
        human_confirmed: bool,
    ) -> QualificationAction:
        """Precision-biased routing (Decision #3 / spec §8)."""
        if alignment >= self.alert_floor and (
            confidence is Confidence.HIGH or human_confirmed
        ):
            return QualificationAction.PURSUE
        if alignment >= self.review_floor or needs_review:
            return QualificationAction.REVIEW
        return QualificationAction.WATCH

    @staticmethod
    def _summary(
        opp: Opportunity,
        discipline: MusicDiscipline,
        alignment: float,
        action: QualificationAction,
        reasons: List[str],
        gaps: List[str],
    ) -> str:
        buyer = opp.buyer_type.value.replace("_", " ")
        article = "an" if buyer[:1] in "aeiou" else "a"
        budget = opp.budget_display().replace("Estimated ", "")
        budget_phrase = "budget undisclosed" if budget == "Unknown" else f"budget {budget}"
        tail = (reasons[0] if reasons else (gaps[0] if gaps else "baseline fit"))
        return (
            f"{alignment:.0f}% aligned — {discipline.label} for {article} {buyer} buyer; "
            f"{budget_phrase}. {tail}. → {action.value}."
        )


# --------------------------------------------------------------------------- #
# Moat capture (spec §9 / Decision #1) — every human override is a training label
# --------------------------------------------------------------------------- #
def record_label(
    opp: Opportunity,
    predicted: QualificationResult,
    corrected_qualified: bool,
    corrected_discipline: MusicDiscipline,
    reason: str,
    path: str,
) -> dict:
    """Append a labeled qualification example (predicted vs corrected) as JSONL.

    This is the proprietary data the gate compounds on: the human's confirm or
    override is the training signal that lets qualification accuracy improve over
    time. Returns the record written.
    """
    record = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "client": opp.client,
        "need": opp.need,
        "source": opp.source,
        "predicted": {
            "qualified": predicted.qualified,
            "discipline": predicted.discipline.value,
            "alignment_pct": predicted.alignment_pct,
            "action": predicted.recommended_action.value,
            "confidence": predicted.confidence.value,
        },
        "corrected": {
            "qualified": corrected_qualified,
            "discipline": corrected_discipline.value,
        },
        "agreement": (
            predicted.qualified == corrected_qualified
            and predicted.discipline is corrected_discipline
        ),
        "reason": reason,
    }
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    return record
