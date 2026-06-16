"""Talent Matcher — rank approved creators against an opportunity's need.

Deterministic (no LLM, no audio AI): matches on **profile and credits** exactly as
the CEO directed. The engine ranks and *explains*; it never assigns — assignment is
Jon's explicit decision in a later stage (see `docs/product-roadmap.md`).

Scoring blends three signals: craft/discipline fit (does the creator do this kind
of work?), credits relevance (do their past credits overlap the brief?), and
profile completeness (a light tiebreaker). Only **matchable** creators — those Jon
has approved and who have at least one discipline — are recommended.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Optional

from .models import MusicDiscipline
from .talent import Talent, profile_completeness

# Words too generic to signal craft overlap between a brief and a creator's credits.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "for", "to", "of", "in", "on", "with", "by",
    "at", "from", "as", "is", "are", "be", "this", "that", "we", "you", "your",
    "our", "music", "original", "need", "needs", "looking", "seeking", "project",
    "work", "spot", "video", "content", "brand", "company", "creative",
}


def _tokens(text: str) -> set:
    cleaned = "".join(c.lower() if c.isalnum() else " " for c in (text or ""))
    return {w for w in cleaned.split() if len(w) > 3 and w not in _STOPWORDS}


@dataclass
class TalentMatch:
    talent: Talent
    score: int                      # 0-100 fit
    reasons: List[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.talent.name


def match_talent(
    primary: MusicDiscipline,
    secondaries: Iterable[MusicDiscipline],
    need_text: str,
    talents: Iterable[Talent],
) -> List[TalentMatch]:
    """Return matchable creators ranked by fit, each with explained reasons.

    Creators with no craft overlap (neither the primary nor a secondary discipline)
    are excluded — a match has to make craft sense.
    """
    secondaries = set(secondaries or [])
    brief_tokens = _tokens(need_text)
    matches: List[TalentMatch] = []

    for t in talents:
        if not t.matchable:
            continue

        reasons: List[str] = []
        if primary in t.disciplines:
            disc_score = 1.0
            reasons.append(f"Matches the primary discipline ({primary.label})")
        else:
            hit = secondaries & set(t.disciplines)
            if hit:
                disc_score = 0.6
                reasons.append(
                    "Covers a secondary discipline ("
                    + ", ".join(sorted(d.label for d in hit)) + ")"
                )
            else:
                continue  # no craft fit — not a match

        overlap = brief_tokens & _tokens(t.credits)
        credit_score = min(1.0, len(overlap) / 3.0) if brief_tokens else 0.0
        if overlap:
            reasons.append("Credits overlap the brief: " + ", ".join(sorted(overlap)))

        completeness = profile_completeness(t) / 100.0
        if completeness >= 1.0:
            reasons.append("Complete profile")

        score = round(100 * (0.6 * disc_score + 0.3 * credit_score + 0.1 * completeness))
        matches.append(TalentMatch(talent=t, score=score, reasons=reasons))

    # Highest fit first; stable tiebreak by name so ordering is deterministic.
    matches.sort(key=lambda m: (-m.score, m.talent.name))
    return matches
