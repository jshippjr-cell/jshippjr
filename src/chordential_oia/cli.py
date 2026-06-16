"""Command-line entry point for the Opportunity Intelligence Agent.

Examples
--------
    chordential-oia                      # ranked report from the sample source
    chordential-oia --breakdown          # include per-criterion tables
    chordential-oia --source sample      # choose source(s)
    chordential-oia --min-score 45       # hide long-shots below a cutoff
    chordential-oia --json               # machine-readable output
    chordential-oia --weights w.json     # custom criterion weights
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List

from .formatting import render_ranked_report
from .models import Opportunity, ScoredOpportunity
from .scoring import DEFAULT_WEIGHTS, ScoringEngine
from .sources import AVAILABLE_SOURCES


def _collect(source_keys: List[str], limit: int) -> List[Opportunity]:
    opportunities: List[Opportunity] = []
    for key in source_keys:
        source_cls = AVAILABLE_SOURCES.get(key)
        if source_cls is None:
            available = ", ".join(sorted(AVAILABLE_SOURCES))
            raise SystemExit(f"Unknown source {key!r}. Available: {available}")
        opportunities.extend(source_cls().fetch(limit=limit))
    return opportunities


def _to_dict(scored: ScoredOpportunity) -> dict:
    opp = scored.opportunity
    return {
        "client": opp.client,
        "need": opp.need,
        "score": scored.score,
        "tier": scored.tier.value,
        "win_probability": scored.win_probability.value,
        "buyer_type": opp.buyer_type.value,
        "budget": opp.budget_display(),
        "decision_maker": scored.decision_maker,
        "reasons": scored.reasons,
        "risks": scored.risks,
        "source": opp.source,
        "source_tier": opp.source_tier,
        "url": opp.url,
        "breakdown": [
            {
                "criterion": b.name,
                "weight": b.weight,
                "signal": round(b.normalized, 3),
                "points": round(b.points, 2),
                "note": b.note,
            }
            for b in scored.breakdown
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chordential-oia",
        description="Find and rank opportunities Chordential can win.",
    )
    parser.add_argument(
        "--source",
        action="append",
        dest="sources",
        metavar="KEY",
        help="Source key to pull from (repeatable). Default: all available.",
    )
    parser.add_argument(
        "--limit", type=int, default=50, help="Max opportunities per source."
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.0,
        help="Hide opportunities scoring below this value.",
    )
    parser.add_argument(
        "--weights",
        metavar="PATH",
        help="JSON file of {criterion: weight} overriding the defaults.",
    )
    parser.add_argument(
        "--breakdown",
        action="store_true",
        help="Show the per-criterion weighted breakdown for each opportunity.",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit JSON instead of a text report."
    )
    parser.add_argument(
        "--list-sources", action="store_true", help="List available sources and exit."
    )
    return parser


def main(argv: List[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_sources:
        for key, cls in sorted(
            AVAILABLE_SOURCES.items(),
            key=lambda kv: (getattr(kv[1](), "source_tier", None) or 9, kv[0]),
        ):
            inst = cls()
            tier = getattr(inst, "source_tier", None)
            access = getattr(inst, "access", "")
            tier_tag = f"T{tier}" if tier else "—"
            print(f"{key:<16} {tier_tag:<3} {inst.name:<22} [{inst.category}] {access}")
        return 0

    source_keys = args.sources or list(AVAILABLE_SOURCES)
    opportunities = _collect(source_keys, args.limit)

    engine = (
        ScoringEngine.from_config(args.weights)
        if args.weights
        else ScoringEngine(DEFAULT_WEIGHTS)
    )
    ranked = engine.rank(opportunities)
    if args.min_score > 0:
        ranked = [s for s in ranked if s.score >= args.min_score]

    if args.json:
        print(json.dumps([_to_dict(s) for s in ranked], indent=2))
    else:
        print(render_ranked_report(ranked, show_breakdown=args.breakdown))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
