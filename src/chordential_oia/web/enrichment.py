"""Company Enrichment Engine — turn one Master-Company-Database agency row into a
normalized Agency Profile by reading the agency's own website the way a person
would.

Design (per the spec):
  * one agency at a time          — enrich_agency(conn, agency_id)
  * start at the homepage          — fetch website, read its navigation
  * discover relevant pages        — classify links to CONCEPTS by meaning, not by
                                     hardcoded paths, so /services, /capabilities and
                                     /what-we-do all resolve to the same concept
  * modular micro-agents           — one extractor per concept (About, Services,
                                     Portfolio, Awards, Industries, Offices,
                                     Leadership, Careers, News, Contact). Each writes
                                     its slice of the SAME AgencyProfile; make one
                                     smarter and nothing else changes.
  * factual extraction only        — no inference, no scoring, no AI generation. A
                                     field that can't be found is left EMPTY, never
                                     guessed (the honesty rule).
  * resumable                      — the profile + the per-agent checkpoint are
                                     committed after every micro-agent, so an
                                     interruption resumes mid-pipeline.

Network is gated by CHORDENTIAL_ENABLE_SCRAPE exactly like the directory crawlers,
so tests and the sandbox never hit the wire (pass your own ``fetch`` to drive it
offline). The engine is deterministic: same site in, same profile out.
"""

from __future__ import annotations

import html as _html
import re
import time
import urllib.request
from dataclasses import dataclass, field, asdict
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

from ..talent_sources.scraped import scrape_enabled
from . import db

_UA = "ChordentialEnrichmentBot/1.0 (+https://chordential.com)"

# A fetch seam: given a URL, return (html, ok). Injected in tests; the default
# only touches the network when scraping is enabled.
Fetch = Callable[[str], Tuple[str, bool]]


# --------------------------------------------------------------------------- #
# Small HTML helpers (deterministic; no parser dependency, like the crawlers)
# --------------------------------------------------------------------------- #
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_SCRIPT_STYLE = re.compile(r"<(script|style|noscript)\b[^>]*>.*?</\1>", re.S | re.I)


def _text(fragment: str) -> str:
    """Strip tags, unescape entities, collapse whitespace."""
    return _WS.sub(" ", _html.unescape(_TAG.sub("", fragment or ""))).strip()


def _strip_chrome(html: str) -> str:
    """Drop script/style/noscript so their contents never leak into extraction."""
    return _SCRIPT_STYLE.sub(" ", html or "")


def _meta(html: str, *keys: str) -> str:
    """First matching <meta name=|property=> content (e.g. og:description)."""
    for key in keys:
        m = re.search(
            r'<meta[^>]+(?:name|property)=["\']' + re.escape(key) +
            r'["\'][^>]*content=["\'](.*?)["\']', html, re.S | re.I)
        if not m:
            m = re.search(
                r'<meta[^>]+content=["\'](.*?)["\'][^>]*(?:name|property)=["\']' +
                re.escape(key) + r'["\']', html, re.S | re.I)
        if m and _text(m.group(1)):
            return _text(m.group(1))
    return ""


def _title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    return _text(m.group(1)) if m else ""


def _host(url: str) -> str:
    h = urlsplit(url).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def _anchors(html: str) -> List[Tuple[str, str]]:
    """(href, anchor-text) for every <a> on the page."""
    out = []
    for m in re.finditer(r'<a\b[^>]*href=["\'](.*?)["\'][^>]*>(.*?)</a>', html, re.S | re.I):
        out.append((_html.unescape(m.group(1)).strip(), _text(m.group(2))))
    return out


def _headed_block(html: str, *keywords: str) -> str:
    """The HTML between a heading whose text matches one of ``keywords`` and the
    next heading of the same-or-higher level. Lets a concept agent scope its
    extraction to 'the Services section' without hardcoding markup."""
    text = _strip_chrome(html)
    for m in re.finditer(r"<h([1-3])\b[^>]*>(.*?)</h\1>", text, re.S | re.I):
        head = _text(m.group(2)).lower()
        if any(k in head for k in keywords):
            level = m.group(1)
            rest = text[m.end():]
            nxt = re.search(rf"<h[1-{level}]\b", rest, re.I)
            return rest[: nxt.start()] if nxt else rest
    return ""


def _list_items(fragment: str, *, limit: int = 40, maxlen: int = 80) -> List[str]:
    """Short, distinct <li>/<h3>/<h4> texts from a fragment — the shape services,
    industries and capability lists almost always take. Long prose and dupes are
    dropped so we keep facts (labels), not paragraphs."""
    items: List[str] = []
    seen = set()
    for m in re.finditer(r"<(?:li|h3|h4)\b[^>]*>(.*?)</(?:li|h3|h4)>", fragment, re.S | re.I):
        t = _text(m.group(1))
        key = t.lower()
        if t and 2 <= len(t) <= maxlen and key not in seen and "©" not in t:
            seen.add(key)
            items.append(t)
        if len(items) >= limit:
            break
    return items


def _paragraph(html: str) -> str:
    """First substantial <p> in the document body (a factual 'about' sentence)."""
    for m in re.finditer(r"<p\b[^>]*>(.*?)</p>", _strip_chrome(html), re.S | re.I):
        t = _text(m.group(1))
        if len(t) >= 80:
            return t
    return ""


# --------------------------------------------------------------------------- #
# Agency Profile — the normalized schema every micro-agent writes into
# --------------------------------------------------------------------------- #
@dataclass
class AgencyProfile:
    """Factual, normalized agency facts. Empty = not found (never guessed)."""
    name: str = ""
    website: str = ""
    description: str = ""
    founded_year: str = ""
    services: List[str] = field(default_factory=list)
    industries: List[str] = field(default_factory=list)
    portfolio: List[str] = field(default_factory=list)
    awards: List[str] = field(default_factory=list)
    offices: List[str] = field(default_factory=list)
    leadership: List[Dict[str, str]] = field(default_factory=list)  # {name, title}
    careers_url: str = ""
    open_roles: List[str] = field(default_factory=list)
    news: List[Dict[str, str]] = field(default_factory=list)        # {title, url}
    email: str = ""
    phone: str = ""
    social_links: Dict[str, str] = field(default_factory=dict)
    sources: Dict[str, str] = field(default_factory=dict)           # concept -> page URL

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "AgencyProfile":
        d = d or {}
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


# --------------------------------------------------------------------------- #
# Concept classification — the robustness layer. Map a link to one of these
# concepts by MEANING (path tokens + anchor text), longest keyword wins so
# 'work-with-us' (careers) beats 'work' (portfolio).
# --------------------------------------------------------------------------- #
CONCEPTS = ("about", "services", "industries", "work", "leadership",
            "offices", "awards", "careers", "news", "contact")

_CONCEPT_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "about": ("about us", "about", "who we are", "our story", "our agency",
              "the agency", "company", "overview", "mission"),
    "services": ("services", "capabilities", "what we do", "expertise",
                 "solutions", "offerings", "disciplines", "specialisms"),
    "industries": ("industries", "sectors", "markets", "verticals", "specialties"),
    "work": ("our work", "case studies", "case study", "portfolio", "projects",
             "work", "cases", "showcase", "clients"),
    "leadership": ("leadership", "our team", "the team", "our people", "people",
                   "team", "management", "founders", "meet the team"),
    "offices": ("offices", "locations", "where we are", "find us", "studios"),
    "awards": ("awards", "recognition", "accolades", "honours", "honors"),
    "careers": ("work with us", "join us", "join the team", "careers", "jobs",
                "vacancies", "hiring", "open roles", "opportunities"),
    "news": ("news", "insights", "blog", "articles", "thinking", "journal",
             "press", "updates", "stories", "ideas", "perspectives"),
    "contact": ("contact us", "contact", "get in touch", "enquiries",
                "say hello", "reach us"),
}

# (keyword, concept) sorted longest-keyword-first so the most specific match wins.
_KEYWORD_INDEX: List[Tuple[str, str]] = sorted(
    ((kw, concept) for concept, kws in _CONCEPT_KEYWORDS.items() for kw in kws),
    key=lambda pair: len(pair[0]), reverse=True,
)


def _normalize(s: str) -> str:
    """Lowercase; turn URL/word separators into single spaces, padded with spaces
    so whole-token matching is just a substring test."""
    s = re.sub(r"[/_\-.+]", " ", (s or "").lower())
    return " " + _WS.sub(" ", s).strip() + " "


def classify_link(url: str, anchor: str = "") -> Optional[str]:
    """Concept this link corresponds to, or None. Considers the URL's last path
    segments and the anchor text; the longest matching keyword decides."""
    path = urlsplit(url).path
    tail = "/".join([p for p in path.split("/") if p][-2:])  # last 2 segments
    hay = _normalize(tail) + _normalize(anchor)
    for kw, concept in _KEYWORD_INDEX:
        if (" " + kw + " ") in hay:
            return concept
    return None


def discover_links(html: str, base_url: str) -> List[Tuple[str, str, str]]:
    """Same-site links from a page, classified. Returns (abs_url, anchor, concept)
    for links that map to a concept, de-duplicated by URL, homepage excluded."""
    base_host = _host(base_url)
    base_path = (urlsplit(base_url).path or "/").rstrip("/") or "/"
    out: List[Tuple[str, str, str]] = []
    seen = set()
    for href, anchor in _anchors(_strip_chrome(html)):
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absu = urljoin(base_url, href)
        sp = urlsplit(absu)
        if sp.scheme not in ("http", "https") or _host(absu) != base_host:
            continue
        norm = (sp.path.rstrip("/") or "/")
        if norm == base_path:            # the homepage itself
            continue
        key = norm.lower()
        if key in seen:
            continue
        concept = classify_link(absu, anchor)
        if concept:
            seen.add(key)
            out.append((absu.split("#")[0], anchor, concept))
    return out


# --------------------------------------------------------------------------- #
# Run context handed to every micro-agent
# --------------------------------------------------------------------------- #
class _Ctx:
    """Per-run state shared by the micro-agents: the link map, a memoized fetch,
    and the homepage (the universal fallback page)."""

    def __init__(self, profile: AgencyProfile, homepage_url: str,
                 links: List[Tuple[str, str, str]], fetch: Fetch):
        self.profile = profile
        self.homepage_url = homepage_url
        self.links = links
        self._fetch = fetch
        self._cache: Dict[str, Tuple[str, bool]] = {}

    def fetch(self, url: str) -> str:
        if url not in self._cache:
            try:
                self._cache[url] = self._fetch(url)
            except Exception:
                self._cache[url] = ("", False)
        html, ok = self._cache[url]
        return html if ok else ""

    def homepage(self) -> str:
        return self.fetch(self.homepage_url)

    def page_for(self, concept: str) -> Tuple[str, str]:
        """(url, html) of the best page for a concept — the shortest matching path
        (most canonical), fetched. ('', '') if the site has no such page."""
        cands = [(u, a) for (u, a, c) in self.links if c == concept]
        if not cands:
            return "", ""
        url = min(cands, key=lambda ua: len(urlsplit(ua[0]).path))[0]
        return url, self.fetch(url)


# --------------------------------------------------------------------------- #
# Micro-agents. Each declares the concept it owns and returns {field: value}
# (non-empty only) to merge into the profile. None of them infer or score.
# --------------------------------------------------------------------------- #
class _Agent:
    name: str = ""
    concept: str = ""

    def run(self, ctx: _Ctx) -> Dict:                      # pragma: no cover
        raise NotImplementedError


_SOCIAL_HOSTS = {
    "facebook.com": "facebook", "linkedin.com": "linkedin", "twitter.com": "twitter",
    "x.com": "twitter", "instagram.com": "instagram", "youtube.com": "youtube",
    "vimeo.com": "vimeo", "tiktok.com": "tiktok", "dribbble.com": "dribbble",
    "behance.net": "behance",
}
_FOUNDED = re.compile(
    r"\b(?:founded|established|est\.?|since|launched|started)\b[^.\d]{0,18}((?:19|20)\d{2})",
    re.I)
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?:\+?\d[\d\-\s().]{7,}\d)")


class AboutAgent(_Agent):
    name, concept = "about", "about"

    def run(self, ctx: _Ctx) -> Dict:
        url, html = ctx.page_for("about")
        page = html or ctx.homepage()
        out: Dict = {}
        desc = _meta(page, "og:description", "description") or _paragraph(page)
        if desc:
            out["description"] = desc
        m = _FOUNDED.search(_text(_strip_chrome(page)))
        if m:
            out["founded_year"] = m.group(1)
        if url and (out.get("description") or out.get("founded_year")):
            out["_source"] = (self.concept, url)
        return out


class ServicesAgent(_Agent):
    name, concept = "services", "services"

    def run(self, ctx: _Ctx) -> Dict:
        url, html = ctx.page_for("services")
        if not html:
            return {}
        block = (_headed_block(html, "service", "what we do", "capabilit",
                               "expertise", "offering") or html)
        items = _list_items(block)
        return {"services": items, "_source": (self.concept, url)} if items else {}


class IndustriesAgent(_Agent):
    name, concept = "industries", "industries"

    def run(self, ctx: _Ctx) -> Dict:
        url, html = ctx.page_for("industries")
        if not html:
            return {}
        block = (_headed_block(html, "industr", "sector", "market", "vertical")
                 or html)
        items = _list_items(block)
        return {"industries": items, "_source": (self.concept, url)} if items else {}


class PortfolioAgent(_Agent):
    name, concept = "portfolio", "work"

    def run(self, ctx: _Ctx) -> Dict:
        url, html = ctx.page_for("work")
        if not html:
            return {}
        # Case-study / project titles: anchors that point deeper than the work
        # index, plus any work-section headings. Titles only — no scoring.
        titles: List[str] = []
        seen = set()
        base = urlsplit(url).path.rstrip("/")
        for href, anchor in _anchors(_strip_chrome(html)):
            p = urlsplit(urljoin(url, href)).path.rstrip("/")
            if anchor and p.startswith(base + "/") and p != base:
                key = anchor.lower()
                if key not in seen and 2 <= len(anchor) <= 80:
                    seen.add(key)
                    titles.append(anchor)
        for h in _list_items(_headed_block(html, "work", "case", "project", "client")):
            if h.lower() not in seen:
                seen.add(h.lower())
                titles.append(h)
        titles = titles[:40]
        return {"portfolio": titles, "_source": (self.concept, url)} if titles else {}


class AwardsAgent(_Agent):
    name, concept = "awards", "awards"
    _AWARD = re.compile(r"award|awwward|winner|won|gold|silver|bronze|finalist|"
                        r"shortlist|grand prix|recogni|honou?r|cannes|webby|d&ad|"
                        r"effie|site of the day|nominee", re.I)

    def run(self, ctx: _Ctx) -> Dict:
        url, html = ctx.page_for("awards")
        page = html or ctx.homepage()
        block = _headed_block(page, "award", "recognition", "accolade") or (html or "")
        lines = [t for t in _list_items(block, maxlen=160) if self._AWARD.search(t)]
        if not lines and html:
            lines = _list_items(html, maxlen=160)
        if lines:
            return {"awards": lines, "_source": (self.concept, url or "")}
        return {}


class OfficesAgent(_Agent):
    name, concept = "offices", "offices"

    def run(self, ctx: _Ctx) -> Dict:
        url, html = ctx.page_for("offices")
        page = html or ctx.homepage()
        offices: List[str] = []
        seen = set()
        for m in re.finditer(r"<address\b[^>]*>(.*?)</address>", page, re.S | re.I):
            t = _text(m.group(1))
            if t and t.lower() not in seen:
                seen.add(t.lower())
                offices.append(t)
        if not offices and html:
            block = _headed_block(html, "office", "location", "studio") or html
            for it in _list_items(block, maxlen=60):
                if it.lower() not in seen:
                    seen.add(it.lower())
                    offices.append(it)
        if offices:
            return {"offices": offices[:30], "_source": (self.concept, url or "")}
        return {}


class LeadershipAgent(_Agent):
    name, concept = "leadership", "leadership"
    # A person card: a name heading (h3-h5 — section headers are h1/h2, so this
    # avoids the section title swallowing the first card) immediately followed by
    # a short title line. The backreference keeps the heading open/close matched.
    _PERSON = re.compile(
        r"<h([3-5])\b[^>]*>(.*?)</h\1>\s*(?:<[^>]+>\s*)*<(?:p|span|div|h[3-6])\b[^>]*>(.*?)</",
        re.S | re.I)
    _TITLEISH = re.compile(
        r"chief|officer|ceo|cto|coo|cfo|cmo|founder|director|head of|president|"
        r"partner|principal|lead|manager|vp|vice president", re.I)

    def run(self, ctx: _Ctx) -> Dict:
        url, html = ctx.page_for("leadership")
        if not html:
            return {}
        people: List[Dict[str, str]] = []
        seen = set()
        for m in self._PERSON.finditer(_strip_chrome(html)):
            name = _text(m.group(2))
            title = _text(m.group(3))
            if (name and title and 2 <= len(name) <= 60 and len(title) <= 80
                    and self._TITLEISH.search(title) and name.lower() not in seen):
                seen.add(name.lower())
                people.append({"name": name, "title": title})
        if people:
            return {"leadership": people[:60], "_source": (self.concept, url)}
        return {}


class CareersAgent(_Agent):
    name, concept = "careers", "careers"

    def run(self, ctx: _Ctx) -> Dict:
        url, html = ctx.page_for("careers")
        if not url:
            return {}
        out: Dict = {"careers_url": url, "_source": (self.concept, url)}
        roles = _list_items(_headed_block(html, "role", "position", "vacanc",
                                          "opening", "job") or html, maxlen=80)
        if roles:
            out["open_roles"] = roles
        return out


class NewsAgent(_Agent):
    name, concept = "news", "news"

    def run(self, ctx: _Ctx) -> Dict:
        url, html = ctx.page_for("news")
        if not html:
            return {}
        items: List[Dict[str, str]] = []
        seen = set()
        base = urlsplit(url).path.rstrip("/")
        for href, anchor in _anchors(_strip_chrome(html)):
            absu = urljoin(url, href)
            p = urlsplit(absu).path.rstrip("/")
            if anchor and p.startswith(base + "/") and p != base and len(anchor) >= 10:
                if anchor.lower() not in seen:
                    seen.add(anchor.lower())
                    items.append({"title": anchor, "url": absu.split("#")[0]})
        if items:
            return {"news": items[:30], "_source": (self.concept, url)}
        return {}


class ContactAgent(_Agent):
    name, concept = "contact", "contact"

    def run(self, ctx: _Ctx) -> Dict:
        url, html = ctx.page_for("contact")
        page = html or ctx.homepage()
        out: Dict = {}
        socials: Dict[str, str] = {}
        for href, _ in _anchors(page):
            low = href.lower()
            if low.startswith("mailto:") and "email" not in out:
                addr = href[7:].split("?")[0].strip()
                if _EMAIL.fullmatch(addr):
                    out["email"] = addr
            elif low.startswith("tel:") and "phone" not in out:
                out["phone"] = href[4:].strip()
            else:
                host = _host(href)
                for sh, label in _SOCIAL_HOSTS.items():
                    if host == sh or host.endswith("." + sh):
                        socials.setdefault(label, href.split("?")[0])
        if "email" not in out:
            m = _EMAIL.search(_text(_strip_chrome(page)))
            if m:
                out["email"] = m.group(0)
        if socials:
            out["social_links"] = socials
        if url and out:
            out["_source"] = (self.concept, url)
        return out


# Pipeline order mirrors the requested flow:
# Website(discover) → About → Services → Portfolio → Awards → Industries →
# Offices → Leadership → Careers → News → Contact.
MICRO_AGENTS: List[_Agent] = [
    AboutAgent(), ServicesAgent(), PortfolioAgent(), AwardsAgent(),
    IndustriesAgent(), OfficesAgent(), LeadershipAgent(), CareersAgent(),
    NewsAgent(), ContactAgent(),
]


# --------------------------------------------------------------------------- #
# Default fetcher (network only when scraping is enabled)
# --------------------------------------------------------------------------- #
def _default_fetch(url: str, timeout: float = 15.0) -> Tuple[str, bool]:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace"), True
    except Exception:
        return "", False


def _merge(profile: AgencyProfile, result: Dict) -> None:
    """Apply a micro-agent's output to the profile. Empty values never overwrite
    a found one (honesty rule); a (concept, url) provenance note is recorded."""
    src = result.pop("_source", None)
    for key, value in result.items():
        if not value:
            continue
        setattr(profile, key, value)
    if src:
        concept, page_url = src
        if page_url:
            profile.sources[concept] = page_url


# --------------------------------------------------------------------------- #
# The engine
# --------------------------------------------------------------------------- #
def enrich_agency(
    conn,
    agency_id: int,
    *,
    fetch: Optional[Fetch] = None,
    reset: bool = False,
    on_progress: Optional[Callable[[Dict], None]] = None,
) -> Dict:
    """Enrich ONE agency from the Master Company Database into an Agency Profile.

    Walks the agency's website like a person: homepage → discover & classify the
    navigation → run each micro-agent against the page its concept maps to. Each
    agent writes its slice of the profile and the state is committed after every
    step, so a re-call with ``reset=False`` resumes mid-pipeline rather than
    starting over. ``fetch`` overrides the network seam (tests pass a fake); with
    no fetch and scraping disabled the run is a no-op marked 'blocked'.

    Returns a summary dict; the full profile lives in agencies.enrichment_json.
    """
    row = db.get_agency(conn, agency_id)
    if row is None:
        return {"agency_id": agency_id, "status": "error", "detail": "no such agency"}

    website = (row["website"] or "").strip()
    if website and not urlsplit(website).scheme:
        website = "https://" + website

    if fetch is None:
        if not scrape_enabled():
            state = {"status": "blocked", "steps_done": [], "links": [],
                     "detail": "scraping disabled", "profile":
                     AgencyProfile(name=row["company"] or "", website=website).to_dict()}
            db.save_agency_enrichment(conn, agency_id, state)
            conn.commit()
            return {"agency_id": agency_id, "status": "blocked",
                    "detail": "scraping disabled"}
        fetch = _default_fetch

    if not website:
        state = {"status": "error", "steps_done": [], "links": [],
                 "detail": "no website on record",
                 "profile": AgencyProfile(name=row["company"] or "").to_dict()}
        db.save_agency_enrichment(conn, agency_id, state)
        conn.commit()
        return {"agency_id": agency_id, "status": "error", "detail": "no website"}

    if reset:
        db.reset_agency_enrichment(conn, agency_id)
        conn.commit()

    state = db.get_agency_enrichment(conn, agency_id) or {}
    steps_done: List[str] = list(state.get("steps_done") or [])
    profile = AgencyProfile.from_dict(state.get("profile"))
    if not profile.name:
        profile.name = row["company"] or ""
    profile.website = website
    links: List[Tuple[str, str, str]] = [tuple(x) for x in (state.get("links") or [])]

    def _save(status: str, detail: str = "") -> None:
        db.save_agency_enrichment(conn, agency_id, {
            "status": status, "steps_done": steps_done, "detail": detail,
            "links": [list(t) for t in links], "profile": profile.to_dict(),
        })
        conn.commit()
        if on_progress:
            on_progress({"agency_id": agency_id, "status": status,
                         "steps_done": list(steps_done), "detail": detail})

    # Step 0 — discover: fetch the homepage and classify its navigation.
    if "discover" not in steps_done:
        home_html, ok = fetch(website)
        if not ok:
            _save("error", "homepage fetch failed")
            return {"agency_id": agency_id, "status": "error",
                    "detail": "homepage fetch failed"}
        links = discover_links(home_html, website)
        steps_done.append("discover")
        _save("running", f"discovered {len(links)} pages")

    ctx = _Ctx(profile, website, links, fetch)

    # Micro-agents, in order, each resumable and committed after it writes.
    for agent in MICRO_AGENTS:
        if agent.name in steps_done:
            continue
        try:
            result = agent.run(ctx)
        except Exception as e:                  # one bad page never sinks the run
            result = {}
            steps_done.append(agent.name)
            _save("running", f"{agent.name}: skipped ({e})")
            continue
        _merge(profile, result)
        steps_done.append(agent.name)
        _save("running", f"{agent.name}: {'+' if result else 'no facts'}")

    _save("complete", "done")
    filled = [k for k, v in profile.to_dict().items() if v and k not in ("name", "website")]
    return {
        "agency_id": agency_id, "company": profile.name, "website": website,
        "status": "complete", "steps_done": steps_done,
        "fields_filled": filled, "profile": profile.to_dict(),
    }


# --------------------------------------------------------------------------- #
# Batch runner — enrich the Master Company Database one agency at a time
# --------------------------------------------------------------------------- #
def enrich_batch(
    conn,
    *,
    source: Optional[str] = None,
    limit: Optional[int] = None,
    fetch: Optional[Fetch] = None,
    delay: float = 0.0,
    reset: bool = False,
    on_agency: Optional[Callable[[Dict], None]] = None,
) -> Dict:
    """Enrich every not-yet-complete agency in the database, one at a time.

    Resumable at TWO levels: each agency is itself resumable (its profile +
    per-agent checkpoint are committed as it goes), and the batch re-selects only
    agencies whose status isn't 'complete' — so re-invoking after an interruption
    skips the finished ones and picks up the rest. Pass ``source`` to scope to one
    directory, ``limit`` to cap how many to process, ``delay`` to space out the
    network, ``reset=True`` to re-enrich everything from the homepage, and
    ``on_agency`` to observe each agency's summary as it completes.

    Network is gated exactly like enrich_agency: with no ``fetch`` and scraping
    off, every agency comes back 'blocked' (a no-op the run reports honestly).
    """
    if reset:
        rows = db.list_agencies(conn, source=source, limit=limit or 100000)
    else:
        rows = db.agencies_needing_enrichment(conn, source=source,
                                              limit=limit or 100000)
    if limit:
        rows = rows[:limit]

    results: List[Dict] = []
    counts: Dict[str, int] = {}
    for i, row in enumerate(rows):
        summary = enrich_agency(conn, row["id"], fetch=fetch, reset=reset)
        results.append(summary)
        counts[summary["status"]] = counts.get(summary["status"], 0) + 1
        if on_agency:
            on_agency(summary)
        if delay and i < len(rows) - 1:
            time.sleep(delay)

    return {
        "source": source, "total": len(results),
        "completed": counts.get("complete", 0),
        "blocked": counts.get("blocked", 0),
        "errors": counts.get("error", 0),
        "status_counts": counts, "results": results,
    }
