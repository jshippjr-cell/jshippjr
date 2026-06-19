"""Curated industry source catalog for the discovery crawler.

Replaces the rejected broad Google/Bing sweep with the specific trade boards,
job boards, and communities where producers, directors, creative/production
managers, and game-audio leads actually post music work — and where music
creators are found. Each site carries the executive council's rationale and the
champion who recommended it (see ``docs/discovery-sources-council.md``).

Two tiers:
- ``Established`` — the ratified starter set, active on launch.
- ``Suggested`` — emerging/ToS-sensitive venues the council flagged; the crawler
  presents these and scans nothing until Jon approves the site (per the
  "machine proposes, Jon disposes" rule).

The catalog is code-managed (editorial, expert-curated). Per-site approval *state*
is persisted in the ``discovery_sites`` table so Jon's decisions stick; URL
building lives here so keyword/location can be applied at generation time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from urllib.parse import quote_plus

# A board is one searchable/browsable surface on a site:
#   (applies_to_kind, label, url_template)   -- {q} in the template => keyworded.
Board = Tuple[str, str, str]

STATUS_ESTABLISHED = "Established"
STATUS_SUGGESTED = "Suggested"


@dataclass(frozen=True)
class SourceSite:
    key: str
    name: str
    homepage: str
    kind: str                 # 'opportunity' | 'talent' | 'both'
    category: str
    recommended_by: str       # the exec champion
    rationale: str
    status: str               # STATUS_ESTABLISHED | STATUS_SUGGESTED
    boards: List[Board] = field(default_factory=list)
    # Login/ToS-walled sources are never auto-scraped — they surface in a
    # "manual-assist" list where Jon opens them in his own logged-in browser.
    login_gated: bool = False

    def serves(self, gen_kind: str) -> bool:
        return self.kind == "both" or self.kind == gen_kind


# Default search terms when the caller gives none (board templates with {q}).
_DEFAULT_Q = {"opportunity": "composer music", "talent": "composer"}


# --------------------------------------------------------------------------- #
# Launchpad search terms — learned from real gigs (e.g. r/gameDevClassifieds
# "[PAID] Looking for a Music Composer"). IMPORTANT: Reddit's search is
# keyword-only — complex boolean ((a OR b) (c OR d) -x) returns ZERO results — so
# we offer a few SIMPLE one-click searches per channel instead of one mega-query.
# Each term below is a working search; the user clicks whichever fits and skims
# the newest results. Tune this list as Jon flags real hits/misses.
# --------------------------------------------------------------------------- #
SEARCH_TERMS = ["composer", "music", '"sound design"', '"game audio"', "soundtrack"]

# Simple, FLAT exclusions appended to each search (term -hobby -revshare …).
# Reddit supports flat `-word` / `-"phrase"` exclusions even though it can't do
# nested boolean — this strips the unpaid / rev-share / self-promo noise.
EXCLUDE_TERMS = [
    "hobby", "revshare", '"rev share"', "royalty", "unpaid",
    '"not paying"', '"for hire"', "collab",
]


# --------------------------------------------------------------------------- #
# The catalog
# --------------------------------------------------------------------------- #
CATALOG: List[SourceSite] = [
    # --- Established: demand-side job boards / communities ------------------ #
    SourceSite(
        "productionhub", "ProductionHub", "https://www.productionhub.com",
        "opportunity", "Production job board", "RFP Intelligence Director",
        "Film/video producers post crew + music calls here.", STATUS_ESTABLISHED,
        [("opportunity", "Jobs", "https://www.productionhub.com/jobs/search?keywords={q}")],
        login_gated=True,
    ),
    SourceSite(
        "mandy", "Mandy.com", "https://www.mandy.com",
        "opportunity", "Film/TV crew + jobs", "RFP Intelligence Director",
        "Long-standing film/TV/commercial crew and jobs board.", STATUS_ESTABLISHED,
        [("opportunity", "Jobs", "https://www.mandy.com/job/search?q={q}")],
    ),
    SourceSite(
        "stage32", "Stage 32", "https://www.stage32.com",
        "opportunity", "Film-industry jobs", "Competitive Intelligence Analyst",
        "Film-industry network; directors/producers hire on its jobs board.",
        STATUS_ESTABLISHED,
        [("opportunity", "Jobs", "https://www.stage32.com/jobs/search?q={q}")],
    ),
    SourceSite(
        "taxi", "TAXI A&R", "https://www.taxi.com",
        "opportunity", "Music licensing A&R", "Competitive Intelligence Analyst",
        "Independent A&R — music licensing/placement opportunities (film, ad, library).",
        STATUS_ESTABLISHED,
        [("opportunity", "Listings", "https://www.taxi.com/industry-listings")],
        login_gated=True,
    ),
    SourceSite(
        "vicontrol", "VI-Control · Job Offerings", "https://vi-control.net",
        "both", "Composer community", "RFP Intelligence Director",
        "The composer community; the Job Offerings / For Hire subforum is dense "
        "with real gigs, and its members are talent.", STATUS_ESTABLISHED,
        [
            ("opportunity", "Job Offerings",
             "https://vi-control.net/community/forums/job-offerings-for-hire.30/"),
            ("talent", "Members / for hire",
             "https://vi-control.net/community/forums/job-offerings-for-hire.30/"),
        ],
    ),
    SourceSite(
        "soundlister", "Soundlister", "https://soundlister.com",
        "opportunity", "Film/TV music jobs", "RFP Intelligence Director",
        "Film/TV music industry jobs — composers, supervisors, additional music.",
        STATUS_ESTABLISHED,
        [("opportunity", "Jobs", "https://soundlister.com/jobs/")],
    ),
    SourceSite(
        "filmmusicnetwork", "Film Music Network", "https://www.filmmusic.net",
        "opportunity", "Music-for-media jobs", "Competitive Intelligence Analyst",
        "Music-for-media job listings, US + international.", STATUS_ESTABLISHED,
        [("opportunity", "Jobs", "https://www.filmmusic.net/jobs/")],
    ),
    SourceSite(
        "reddit_forhire", "Reddit · r/forhire", "https://www.reddit.com/r/forhire",
        "opportunity", "Community gig board", "Demand-Gen Manager",
        "“[Hiring] composer/music” posts from indie producers and devs.",
        STATUS_ESTABLISHED,
        [("opportunity", "Search",
          "https://www.reddit.com/r/forhire/search/?q={q}&restrict_sr=1&sort=new")],
        login_gated=True,
    ),
    SourceSite(
        "reddit_gamedev", "Reddit · r/gameDevClassifieds",
        "https://www.reddit.com/r/gameDevClassifieds",
        "opportunity", "Community gig board", "Demand-Gen Manager",
        "Game studios hiring composers and sound designers.", STATUS_ESTABLISHED,
        [("opportunity", "Search",
          "https://www.reddit.com/r/gameDevClassifieds/search/?q={q}&restrict_sr=1&sort=new")],
        login_gated=True,
    ),
    SourceSite(
        "reddit_inat", "Reddit · r/INAT", "https://www.reddit.com/r/INAT",
        "opportunity", "Game-dev team board", "Demand-Gen Manager",
        "“I Need A Team” — game projects posting [PAID] composer/audio roles.",
        STATUS_ESTABLISHED,
        [("opportunity", "Search",
          "https://www.reddit.com/r/INAT/search/?q={q}&restrict_sr=1&sort=new")],
        login_gated=True,
    ),
    SourceSite(
        "reddit_gameaudio", "Reddit · r/gameaudio", "https://www.reddit.com/r/gameaudio",
        "opportunity", "Game-audio community", "RFP Intelligence Director",
        "Game-audio community — composers/sound designers and the studios hiring them.",
        STATUS_ESTABLISHED,
        [("opportunity", "Search",
          "https://www.reddit.com/r/gameaudio/search/?q={q}&restrict_sr=1&sort=new")],
        login_gated=True,
    ),
    SourceSite(
        "gearspace", "Gearspace · Employment", "https://gearspace.com",
        "both", "Pro-audio community", "RFP Intelligence Director",
        "Pro-audio community employment board — mix/score/sound work and people.",
        STATUS_ESTABLISHED,
        [("opportunity", "Employment", "https://gearspace.com/board/employment/")],
    ),
    # --- Established: supply-side (talent) marketplaces --------------------- #
    SourceSite(
        "soundbetter", "SoundBetter", "https://soundbetter.com",
        "talent", "Talent marketplace", "Estimation Director",
        "Marketplace of vetted music creators — supply-side discovery.",
        STATUS_ESTABLISHED,
        [("talent", "Search", "https://soundbetter.com/search?q={q}")],
    ),
    SourceSite(
        "airgigs", "AirGigs", "https://www.airgigs.com",
        "talent", "Talent marketplace", "Estimation Director",
        "Online session/music services marketplace — supply-side discovery.",
        STATUS_ESTABLISHED,
        [("talent", "Services", "https://www.airgigs.com/search?q={q}")],
    ),

    # --- Suggested: await Jon's per-site approval before any scan ----------- #
    SourceSite(
        "linkedin_jobs", "LinkedIn · niche music jobs", "https://www.linkedin.com",
        "opportunity", "Professional network", "Competitive Intelligence Analyst",
        "Agencies/brands post composer/sound roles — narrow query only, not broad "
        "search. Login-gated; treat as a suggestion.", STATUS_SUGGESTED,
        [("opportunity", "Jobs search",
          "https://www.linkedin.com/jobs/search/?keywords={q}")],
        login_gated=True,
    ),
    SourceSite(
        "x_gigs", "X/Twitter · gig hashtags", "https://x.com",
        "opportunity", "Social", "Demand-Gen Manager",
        "Real-time indie gig calls (#composerwanted, #gameaudiojobs). High noise.",
        STATUS_SUGGESTED,
        [("opportunity", "Search", "https://x.com/search?q={q}&f=live")],
        login_gated=True,
    ),
    SourceSite(
        "behance_sound", "Behance · Sound/Music", "https://www.behance.net",
        "talent", "Portfolio network", "Estimation Director",
        "Portfolio discovery of sound/music creators (talent-side).",
        STATUS_SUGGESTED,
        [("talent", "Projects", "https://www.behance.net/search/projects?search={q}")],
    ),
    SourceSite(
        "craigslist_creative", "Craigslist · creative gigs",
        "https://craigslist.org",
        "opportunity", "Classifieds", "Demand-Gen Manager",
        "Local/indie music gigs; noisy and per-market.", STATUS_SUGGESTED,
        [("opportunity", "Creative gigs", "https://www.craigslist.org/search/crg?query={q}")],
    ),
]

_BY_KEY = {s.key: s for s in CATALOG}


def get_site(key: str) -> Optional[SourceSite]:
    return _BY_KEY.get(key)


def site_targets(
    site: SourceSite,
    gen_kind: str,
    keyword: Optional[str] = None,
    location: Optional[str] = None,
) -> List[dict]:
    """Build crawl-target dicts for a site for a given generation kind.

    Returns one dict per relevant board. Boards with ``{q}`` are keyworded with
    ``keyword`` (falling back to a sensible default) plus any ``location``;
    fixed board URLs are used as-is. No network — pure URL construction.
    """
    q = (keyword or _DEFAULT_Q.get(gen_kind, "")).strip()
    loc = (location or "").strip()
    terms = f"{q} {loc}".strip() if loc else q
    out: List[dict] = []
    for board_kind, label, tmpl in site.boards:
        if board_kind != gen_kind and board_kind != "both":
            continue
        if "{q}" in tmpl:
            url = tmpl.format(q=quote_plus(terms or q or "music"))
            query = terms or q
        else:
            url = tmpl
            query = "(listing)"
        out.append({
            "kind": gen_kind,
            "label": f"{site.name} — {label}" + (f" · {loc}" if loc else ""),
            "query": query,
            "url": url,
            "source_key": site.key,
            "rationale": site.rationale,
        })
    return out
