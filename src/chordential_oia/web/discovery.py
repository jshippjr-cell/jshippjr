"""Human-gated discovery crawler — "the machine proposes, Jon disposes".

Two halves:

1. **Propose** (deterministic, no network): from disciplines / roles / keywords,
   build candidate places to look — specific search URLs on public providers —
   and store them as ``Proposed`` :data:`crawl_targets`. This mirrors the
   deterministic LinkedIn people-search deep-link the outreach layer already
   builds (``outreach._linkedin_research_url``); it only suggests *where* to go.

2. **Fetch** (gated): :func:`run_target` fetches a target **only if Jon has
   Approved it** AND the scrape flag is on (Render). Talent results become
   Pending creators; opportunity results become inbound leads — both land in a
   review queue and still require Jon's qualification. Nothing is auto-pursued.

Serves both the supply side (talent) and the demand side (opportunities), so the
existing RFP scanner gains the same gated-crawl capability.
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import List, Optional
from urllib.parse import quote_plus

from ..models import MusicDiscipline
from ..talent_sources.scraped import ScrapedTalentSource, _fetch_url, scrape_enabled
from . import db

# Public search providers we build deep-links into. Each is a (key, label,
# url_template) — the template takes a pre-encoded query string. These point a
# human (and, once approved, the fetcher) at a public results page.
_TALENT_PROVIDERS = [
    ("linkedin", "LinkedIn people search",
     "https://www.linkedin.com/search/results/people/?keywords={q}"),
    ("google", "Google portfolio search",
     "https://www.google.com/search?q={q}"),
]
_OPPORTUNITY_PROVIDERS = [
    ("google", "Google RFP search",
     "https://www.google.com/search?q={q}"),
    ("bing", "Bing RFP search",
     "https://www.bing.com/search?q={q}"),
]

# Default discovery terms when the caller doesn't specify any.
_DEFAULT_TALENT_DISCIPLINES = [
    MusicDiscipline.COMPOSITION,
    MusicDiscipline.SONIC_BRANDING,
    MusicDiscipline.SOUND_DESIGN,
]
_DEFAULT_OPPORTUNITY_KEYWORDS = [
    "original music RFP",
    "sonic branding brief",
    "video score request for proposal",
]


def _discipline_query(d: MusicDiscipline) -> str:
    """Search keywords for finding a creator in a discipline."""
    return {
        MusicDiscipline.COMPOSITION: "film composer original music portfolio",
        MusicDiscipline.SONIC_BRANDING: "sonic branding sound logo composer",
        MusicDiscipline.SOUND_DESIGN: "sound designer reel portfolio",
        MusicDiscipline.ARRANGEMENT: "arranger orchestrator portfolio",
        MusicDiscipline.SUPERVISION: "music supervisor sync portfolio",
        MusicDiscipline.LICENSING: "music supervisor licensing portfolio",
    }.get(d, f"{d.label} portfolio")


def propose_talent_targets(
    disciplines: Optional[List[MusicDiscipline]] = None,
    location: Optional[str] = None,
) -> List[dict]:
    """Deterministically propose where to look for creators. No network."""
    disciplines = disciplines or _DEFAULT_TALENT_DISCIPLINES
    loc = (location or "").strip()
    out: List[dict] = []
    for d in disciplines:
        terms = _discipline_query(d)
        if loc:
            terms = f"{terms} {loc}"
        for key, label, tmpl in _TALENT_PROVIDERS:
            out.append({
                "kind": "talent",
                "label": f"{label} — {d.label}" + (f" · {loc}" if loc else ""),
                "query": terms,
                "url": tmpl.format(q=quote_plus(terms)),
                "source_key": key,
                "rationale": f"Find {d.label} creators via {label.split(' ')[0]}.",
            })
    return out


def propose_opportunity_targets(
    keywords: Optional[List[str]] = None,
    location: Optional[str] = None,
) -> List[dict]:
    """Deterministically propose where to look for opportunities. No network."""
    keywords = keywords or _DEFAULT_OPPORTUNITY_KEYWORDS
    loc = (location or "").strip()
    out: List[dict] = []
    for kw in keywords:
        terms = f"{kw} {loc}".strip() if loc else kw
        for key, label, tmpl in _OPPORTUNITY_PROVIDERS:
            out.append({
                "kind": "opportunity",
                "label": f"{label} — “{kw}”" + (f" · {loc}" if loc else ""),
                "query": terms,
                "url": tmpl.format(q=quote_plus(terms)),
                "source_key": key,
                "rationale": f"Surface RFPs/briefs matching “{kw}”.",
            })
    return out


def generate_targets(
    conn,
    kind: str,
    terms: Optional[List[str]] = None,
    location: Optional[str] = None,
) -> int:
    """Generate proposals for a kind and store the new ones (deduped). Returns
    how many NEW targets were proposed. Purely deterministic — no fetching."""
    if kind == "talent":
        disciplines = None
        if terms:
            disciplines = [
                MusicDiscipline(t) for t in terms
                if t in {m.value for m in MusicDiscipline}
            ] or None
        proposals = propose_talent_targets(disciplines, location)
    elif kind == "opportunity":
        proposals = propose_opportunity_targets(terms or None, location)
    else:
        raise ValueError(f"Unknown crawl kind {kind!r}")

    added = 0
    for p in proposals:
        new_id = db.insert_crawl_target(
            conn, p["kind"], p["label"], p["query"], p["url"],
            p["source_key"], p["rationale"],
        )
        if new_id is not None:
            added += 1
    return added


# --------------------------------------------------------------------------- #
# Opportunity listing parser (pure) — parallel to scraped.parse_talent_html
# --------------------------------------------------------------------------- #
class _OppListingParser(HTMLParser):
    """Extract opportunity records from a documented listing structure::

        <li class="opportunity" data-company="Acme" data-need="Brand spot music"
            data-url="https://.../rfp" data-description="..."></li>
    """

    def __init__(self) -> None:
        super().__init__()
        self.records: List[dict] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "opportunity" not in (a.get("class") or "").split():
            return
        company = (a.get("data-company") or "").strip()
        need = (a.get("data-need") or "").strip()
        if not (company or need):
            return
        self.records.append({
            "company": company or "(unknown)",
            "need": need or "Music opportunity",
            "url": (a.get("data-url") or "").strip() or None,
            "description": (a.get("data-description") or "").strip(),
        })


def parse_opportunity_html(html: str) -> List[dict]:
    """Pure parser: structured listing HTML → opportunity-lead dicts. No network."""
    parser = _OppListingParser()
    try:
        parser.feed(html or "")
    except Exception:
        pass
    return parser.records


# --------------------------------------------------------------------------- #
# Gated fetch — runs ONLY on an Approved target
# --------------------------------------------------------------------------- #
def run_target(conn, target) -> int:
    """Fetch one Approved target and ingest its results into a review queue.

    Enforces the gate: a target that isn't Approved is never fetched. Talent
    results become Pending creators (reel-review gate); opportunity results
    become inbound leads (promotion gate). Returns the number of records ingested.
    Fails soft and marks the target Fetched with its count.
    """
    if target["status"] != "Approved":
        raise ValueError("Only an Approved target can be fetched.")

    ingested = 0
    if target["kind"] == "talent":
        for t in ScrapedTalentSource(target["url"]).fetch():
            if not db.talent_exists(conn, t.name, t.email):
                db.insert_talent(conn, t)
                ingested += 1
    elif target["kind"] == "opportunity":
        if scrape_enabled():
            try:
                html = _fetch_url(target["url"])
            except Exception:
                html = ""
            for rec in parse_opportunity_html(html):
                db.insert_inbound_lead(
                    conn,
                    contact_name="(discovered)",
                    company=rec["company"],
                    project_type=rec["need"],
                    description=rec["description"],
                    source="crawl",
                )
                ingested += 1

    db.mark_crawl_target_fetched(conn, target["id"], ingested)
    return ingested
