"""Human-gated discovery crawler — "the machine proposes, Jon disposes".

Three halves now:

1. **Curated sites** (``discovery_sources``): the crawler combs a council-vetted
   catalog of industry venues (ProductionHub, TAXI, VI-Control, Mandy, Stage 32,
   Soundlister, Reddit gig subs, SoundBetter, AirGigs, …) — never a broad
   Google/Bing sweep. Established sites are active; Suggested sites are presented
   and scanned only after Jon approves the site.

2. **Propose** (deterministic, no network): from the *active* sites, build
   candidate search/board URLs as ``Proposed`` crawl targets.

3. **Fetch** (gated): :func:`run_target` fetches a target only if Jon Approved it
   AND the scrape flag is on. Talent results become Pending creators; opportunity
   results become inbound leads — both land in a review queue for qualification.

Serves both the supply side (talent) and the demand side (opportunities).
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import List, Optional
from urllib.parse import quote_plus

from ..talent_sources.scraped import ScrapedTalentSource, _fetch_url, scrape_enabled
from . import db
from . import discovery_sources as catalog


# --------------------------------------------------------------------------- #
# Catalog sync — keep the discovery_sites table aligned with the code catalog
# --------------------------------------------------------------------------- #
def sync_catalog(conn) -> int:
    """Insert any catalog sites not yet in the DB (never overwrites Jon's
    approve/reject decisions). Returns how many new sites were added."""
    before = db.discovery_site_counts(conn)["total"]
    for site in catalog.CATALOG:
        db.upsert_discovery_site(
            conn, site.key, site.name, site.homepage, site.kind, site.category,
            site.recommended_by, site.rationale, site.status,
            login_gated=site.login_gated,
        )
    return db.discovery_site_counts(conn)["total"] - before


# --------------------------------------------------------------------------- #
# Propose targets from the ACTIVE curated sites only
# --------------------------------------------------------------------------- #
def propose_targets(
    active_keys: List[str],
    kind: str,
    keyword: Optional[str] = None,
    location: Optional[str] = None,
) -> List[dict]:
    """Deterministically build target dicts from the given active site keys. No
    network. Skips keys not in the catalog or not serving this kind."""
    out: List[dict] = []
    for key in active_keys:
        site = catalog.get_site(key)
        if site is None or not site.serves(kind):
            continue
        out.extend(catalog.site_targets(site, kind, keyword, location))
    return out


def _custom_site_target(site_row, kind: str, keyword: Optional[str], location: Optional[str]):
    """Build one target dict from a Jon-added custom site's stored board_url."""
    url = site_row["board_url"]
    if not url:
        return None
    q = (keyword or "").strip()
    loc = (location or "").strip()
    terms = f"{q} {loc}".strip()
    if "{q}" in url:
        url = url.format(q=quote_plus(terms or q or "music"))
    return {
        "kind": kind,
        "label": f"{site_row['name']}" + (f" · {loc}" if loc else ""),
        "query": terms or "(listing)",
        "url": url,
        "source_key": site_row["key"],
        "rationale": site_row["rationale"] or "Added by Jon.",
    }


def generate_targets(
    conn,
    kind: str,
    keyword: Optional[str] = None,
    location: Optional[str] = None,
) -> int:
    """Propose targets for a kind from the active sites (curated catalog +
    Jon-added custom sites) and store the new ones (deduped on kind+url).
    Purely deterministic — no fetching."""
    if kind not in db.CRAWL_KINDS:
        raise ValueError(f"Unknown crawl kind {kind!r}")
    added = 0
    for key in db.active_discovery_site_keys(conn, kind):
        site = catalog.get_site(key)
        if site is not None:
            proposals = catalog.site_targets(site, kind, keyword, location)
        else:
            # A custom site Jon added — build from its stored board_url.
            row = db.get_discovery_site_by_key(conn, key)
            t = _custom_site_target(row, kind, keyword, location) if row else None
            proposals = [t] if t else []
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
    become inbound leads (promotion gate). Returns the number ingested. Fails
    soft and marks the target Fetched with its count.
    """
    if target["status"] != "Approved":
        raise ValueError("Only an Approved target can be fetched.")
    return _do_fetch(conn, target)


def _do_fetch(conn, target) -> int:
    """Fetch + ingest one target into the review queue. Talent → Pending creators;
    opportunities → inbound leads (deduped so recurring re-scans don't pile up).
    No gate check here — callers enforce the approved-lineage gate."""
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
                if db.inbound_lead_exists(conn, rec["company"], rec["need"], "crawl"):
                    continue
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


def refetch_target(conn, target) -> int:
    """Re-scan an already-approved-and-fetched target (the recurring auto-fetch).
    The gate holds: callers only pass approved-lineage targets on active sources."""
    return _do_fetch(conn, target)


def fetch_or_refetch(conn, target) -> int:
    """Dispatch for the background auto-fetcher: fetch a new Approved target, or
    re-scan one already Fetched."""
    if target["status"] == "Approved":
        return run_target(conn, target)
    return refetch_target(conn, target)
