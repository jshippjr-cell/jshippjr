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
from . import crawl_adapters
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


def seed_active_targets(conn, site_row) -> int:
    """When a source is switched On, queue a default **Approved** target for it
    (its main board/search) so "On" means "fetching" — no separate approve step.
    Approving the *source* is the human gate; the deterministic default search
    needs no extra click. Login-gated sources are skipped (manual-assist only).

    Idempotent: an existing target for the same URL is left as-is, so a default
    Jon dismissed is never resurrected. Returns how many new targets were added."""
    if site_row["login_gated"]:
        return 0
    site_kind = site_row["kind"]
    kinds = ["talent", "opportunity"] if site_kind == "both" else [site_kind]
    site = catalog.get_site(site_row["key"])
    added = 0
    for k in kinds:
        if site is not None:
            target_dicts = catalog.site_targets(site, k)
        else:  # a Jon-added custom source — build from its stored board_url
            t = _custom_site_target(site_row, k, None, None)
            target_dicts = [t] if t else []
        for t in target_dicts:
            tid = db.insert_crawl_target(
                conn, t["kind"], t["label"], t["query"], t["url"],
                t["source_key"], t["rationale"],
            )
            if tid is not None:
                db.update_crawl_target_status(conn, tid, "Approved")
                added += 1
    return added


def seed_all_active(conn) -> int:
    """Backfill a default Approved target for every already-active, non-gated
    source that lacks one — so existing On sources start fetching without being
    toggled. Idempotent (dedupes on URL)."""
    added = 0
    for s in db.list_discovery_sites(conn):
        if s["status"] in db.ACTIVE_SITE_STATES and not s["login_gated"]:
            added += seed_active_targets(conn, s)
    return added


def reddit_search_url(subreddit: str, term: str = "composer") -> str:
    """A FLAT Reddit search: one positive term + simple ``-exclusions`` (no nested
    boolean, which Reddit can't parse), newest first, restricted to the sub. Keeps
    the paid gigs, strips the [Hobby]/[RevShare]/for-hire noise."""
    excl = " ".join("-" + t for t in catalog.EXCLUDE_TERMS)
    q = f"{term} {excl}".strip()
    return (
        f"https://www.reddit.com/r/{subreddit}/search/"
        f"?q={quote_plus(q)}&restrict_sr=1&sort=new"
    )


def _subreddit_of(site_row) -> Optional[str]:
    home = site_row["homepage"] or ""
    if "reddit.com/r/" in home:
        sub = home.rstrip("/").split("/r/")[-1]
        return sub or None
    return None


def manual_assist_searches(site_row) -> List[dict]:
    """One-click searches for a manual-assist source. Reddit sources get several
    simple term searches (composer / music / sound design …); everything else
    gets a single best-search link."""
    sub = _subreddit_of(site_row)
    if sub:
        labels = [t.strip('"') for t in catalog.SEARCH_TERMS]
        return [
            {"label": lbl, "url": reddit_search_url(sub, term)}
            for lbl, term in zip(labels, catalog.SEARCH_TERMS)
        ]
    return [{"label": "Open search", "url": manual_assist_url(site_row)}]


def manual_assist_url(site_row) -> str:
    """The best single direct-search URL for a manual-assist source."""
    sub = _subreddit_of(site_row)
    if sub:
        return reddit_search_url(sub)
    site = catalog.get_site(site_row["key"])
    if site is not None:
        for k in ("opportunity", "talent"):
            targets = catalog.site_targets(site, k)
            if targets:
                return targets[0]["url"]
    if site_row["board_url"]:
        kind = site_row["kind"] if site_row["kind"] != "both" else "opportunity"
        t = _custom_site_target(site_row, kind, None, None)
        if t:
            return t["url"]
    return home or "#"


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
    outcome = None
    if target["kind"] == "talent":
        for t in ScrapedTalentSource(target["url"]).fetch():
            if not db.talent_exists(conn, t.name, t.email):
                db.insert_talent(conn, t)
                ingested += 1
        outcome = "ok" if ingested else "empty"
    elif target["kind"] == "opportunity":
        res = crawl_adapters.fetch_opportunity_records(target)
        for rec in res["records"]:
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
        outcome = res["outcome"]
        # Auto-detect a login wall → move the source to manual-assist (never
        # auto-fetched again) so Jon knows it needs his own signed-in browser.
        if outcome == "login" and target["source_key"]:
            db.set_site_login_gated(conn, target["source_key"], True)

    db.mark_crawl_target_fetched(conn, target["id"], ingested, outcome)
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
