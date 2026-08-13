"""Decision Maker Discovery Engine — find the people worth contacting at an
agency and explain WHY, as a chain of single-responsibility agents (not one giant
prompt), mirroring the Company Enrichment Engine.

    Agency
      → Leadership Discovery   (Agent 1: find every person; no judgment)
      → Role Classification    (Agent 2: title → role/priority/relevance)
      → Contact Discovery      (Agent 3: LinkedIn / email / phone / social)
      → LinkedIn Verification  (Agent 4: structural name↔profile check)
      → Confidence Scoring     (Agent 5: deterministic 0–100 from signals)
      → Database Update        (Agent 6: store every decision maker)

Design rules (honor the Chordential spine):
  * "The machine proposes, Jon disposes" — we surface ranked, explained contacts;
    a human still decides who to reach out to.
  * Factual only — every stored field is copied from a public page or is a
    deterministic classification of one. Contacts are NEVER invented; a field that
    can't be found is left empty.
  * Hybrid classification — a deterministic rules engine decides by default; an
    LLM is consulted ONLY for titles the rules can't classify confidently (gated +
    optional). Whatever the LLM decides is written back into the title taxonomy, so
    the same title is answered by rules next time — the taxonomy grows, the AI
    calls shrink, and the result stays explainable.

Network + LLM are seams (injectable for tests; null/offline by default): pass your
own ``fetch`` and ``llm`` to drive the engine deterministically.
"""

from __future__ import annotations

import json
import os
import re
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

from . import db, web_search
from .enrichment import (
    Fetch, _anchors, _default_fetch, _host, _strip_chrome, _text,
    classify_link, discover_links, scrape_enabled,
)

# An LLM classifier seam: title + context -> classification dict (or None).
LLM = Callable[[str, str], Optional[Dict]]
# A web-search seam: query -> [{title, url, snippet}] (see web_search.search).
SearchFn = Callable[[str], List[Dict]]

# The concepts whose pages name people (leadership covers team/people/management).
_PEOPLE_CONCEPTS = ("leadership", "about")


# --------------------------------------------------------------------------- #
# Agent 1 — Leadership Discovery: find every person. No judgment.
# --------------------------------------------------------------------------- #
# A person card is a name (a 2–4 word proper noun in a heading or a "Name — Title"
# line) paired with a job-title line. We detect the title with a BROAD job-word
# lexicon (not just executives) so producers, designers and coordinators are all
# captured here — Agent 2 does the judging, not this one.
_JOB_WORDS = (
    r"director|producer|manager|officer|head|lead|designer|strateg|partner|"
    r"founder|owner|ceo|cto|coo|cfo|cmo|cco|president|principal|chair|"
    r"vice president|vp|chief|executive|creative|account|coordinator|specialist|"
    r"supervisor|editor|engineer|developer|analyst|consultant|planner|buyer|"
    r"controller|associate|assistant|marketing|business development|talent|"
    r"casting|composer|sound|music|production|copywriter|art director"
)
_TITLE_LINE = re.compile(_JOB_WORDS, re.I)
_NAME_RE = re.compile(r"^[A-Z][A-Za-z'’.\-]+(?:\s+[A-Z][A-Za-z'’.\-]+){1,3}$")
_NAME_STOPWORDS = re.compile(
    r"\b(team|leadership|people|management|about|our|the|meet|staff|board|"
    r"contact|careers|work|services|home|menu|©|copyright)\b", re.I)
_SPLIT_NAME_TITLE = re.compile(r"\s*[–—|:]\s*|,\s+")   # "Jane Doe — Creative Director"
_IMG = re.compile(r'<img\b[^>]*\bsrc=["\'](.*?)["\']', re.I | re.S)
_PARA = re.compile(r"<p\b[^>]*>(.*?)</p>", re.S | re.I)


def _looks_like_name(s: str) -> bool:
    s = (s or "").strip()
    return bool(_NAME_RE.match(s)) and not _NAME_STOPWORDS.search(s) and len(s) <= 60


def _first_title_line(fragment: str) -> str:
    """First short, job-title-ish line in a person card."""
    for m in re.finditer(r"<(?:p|span|div|h[2-6]|li|em|strong)\b[^>]*>(.*?)</",
                         fragment, re.S | re.I):
        t = _text(m.group(1))
        # a job-word match is what makes it a title; a real name has no job word,
        # so we don't second-guess two-capitalized-word titles ("Creative Director")
        if t and 2 <= len(t) <= 80 and _TITLE_LINE.search(t):
            return t
    return ""


def _first_photo(fragment: str, base_url: str) -> str:
    m = _IMG.search(fragment)
    return urljoin(base_url, m.group(1)) if m else ""


def _first_bio(fragment: str) -> str:
    for m in _PARA.finditer(fragment):
        t = _text(m.group(1))
        if len(t) >= 60:
            return t
    return ""


def extract_people(html: str, page_url: str) -> List[Dict]:
    """Every person on one page → [{name, title, photo_url, bio, source_url}].
    Two layouts: heading cards (<hN>Name</hN> + a title line in the card), and
    inline "Name — Title" list/paragraph lines. No filtering by importance."""
    text = _strip_chrome(html or "")
    people: List[Dict] = []
    seen = set()

    def add(name, title, photo="", bio="", card=""):
        key = name.lower()
        if name and title and key not in seen:
            seen.add(key)
            # ``card`` is this person's own slice (heading→next heading, or the
            # inline row) so contact discovery reads only their details — never the
            # neighbouring person's email/LinkedIn.
            people.append({"name": name, "title": title, "photo_url": photo,
                           "bio": bio, "source_url": page_url, "card": card})

    # Layout A — heading cards. The card runs to the next heading of any level.
    heads = list(re.finditer(r"<h([1-6])\b[^>]*>(.*?)</h\1>", text, re.S | re.I))
    for i, m in enumerate(heads):
        name = _text(m.group(2))
        if not _looks_like_name(name):
            continue
        end = heads[i + 1].start() if i + 1 < len(heads) else min(len(text), m.end() + 1500)
        card = text[m.end():end]
        pre = text[max(0, m.start() - 400):m.start()]      # photo often precedes name
        title = _first_title_line(card)
        if title:
            add(name, title, _first_photo(pre + card, page_url), _first_bio(card),
                card=card)

    # Layout B — inline "Name — Title" rows (list items / paragraphs).
    for m in re.finditer(r"<(?:li|p|div)\b[^>]*>(.*?)</(?:li|p|div)>", text, re.S | re.I):
        line = _text(m.group(1))
        if not line or len(line) > 120:
            continue
        parts = _SPLIT_NAME_TITLE.split(line, maxsplit=1)
        if len(parts) == 2:
            name, title = parts[0].strip(), parts[1].strip()
            if _looks_like_name(name) and _TITLE_LINE.search(title) and len(title) <= 80:
                add(name, title, _first_photo(m.group(1), page_url), "",
                    card=m.group(1))
    return people


# --------------------------------------------------------------------------- #
# Agent 2 — Role Classification: title → role / department / priority / music
# relevance + a REASON. Deterministic rules first; the LLM only for the unknowns,
# and its answers are learned so they become rules.
# --------------------------------------------------------------------------- #
# Each rule: (compiled pattern, role_category, department, priority,
#             music_relevance, reason, confidence). First match wins; the list is
# ordered most-specific first. confidence ≥ threshold means "the rules are sure".
_PRIORITY = ("Very High", "High", "Medium", "Low", "Very Low")


def _rule(pat, role, dept, prio, music, reason, conf):
    return (re.compile(pat, re.I), role, dept, prio, music, reason, conf)


_RULES = [
    # Music-owning roles — the most direct buyers.
    _rule(r"music supervisor|music director|head of music|music producer|"
          r"music lead|sync(?:\s|$)|music",
          "Music", "Creative", "Very High", "High",
          "Owns music selection directly — the most direct music buyer.", 95),
    # Production — commissions and budgets production music.
    _rule(r"executive producer|head of production|director of production",
          "Production", "Production", "Very High", "High",
          "Senior production leader — commissions and budgets production music.", 92),
    _rule(r"\bproducer\b|production manager|line producer",
          "Production", "Production", "High", "High",
          "Producer — commissions music for productions.", 85),
    # Creative leadership — selects music to fit the creative.
    _rule(r"chief creative officer|executive creative director|\bcco\b",
          "Creative", "Creative", "Very High", "High",
          "Top creative leader — sets the creative direction music must serve.", 92),
    _rule(r"creative director|design director|art director|head of creative",
          "Creative", "Creative", "High", "High",
          "Creative lead — selects music to fit campaign creative.", 88),
    # Executive leadership — controls budgets, can greenlight partnerships.
    _rule(r"founder|owner|\bceo\b|chief executive|managing partner|"
          r"managing director|president|principal",
          "Executive Leadership", "Executive", "High", "Medium",
          "Top decision-maker — controls budgets and can greenlight music "
          "partnerships.", 88),
    _rule(r"chief\b|\bcoo\b|\bcfo\b|chief operating|chief financial",
          "Executive Leadership", "Executive", "Medium", "Low",
          "C-suite operations/finance — approves spend but not a creative buyer.", 80),
    # Strategy / accounts / commercial — influences but rarely picks music.
    _rule(r"strateg|planner|head of strategy",
          "Strategy", "Strategy", "Medium", "Medium",
          "Strategy lead — shapes briefs that define music needs.", 78),
    _rule(r"business development|\bbd\b|growth|new business",
          "Commercial", "Commercial", "Medium", "Low",
          "Commercial lead — a relationship entry point, not a music buyer.", 78),
    _rule(r"account director|account manager|client partner|client services",
          "Account", "Accounts", "Medium", "Medium",
          "Account lead — coordinates production needs with clients.", 78),
    _rule(r"marketing director|head of marketing|cmo|brand manager|marketing",
          "Marketing", "Marketing", "Medium", "Low",
          "Marketing lead — owns brand campaigns that may need music.", 75),
    # Operations / admin — not creative or music buyers.
    _rule(r"office manager|human resources|\bhr\b|people operations|recruit|"
          r"talent acquisition|finance|accounts payable|bookkeep|operations|"
          r"administrat|coordinator|assistant|reception|it support",
          "Operations", "Operations", "Low", "Low",
          "Operations/admin role — not involved in creative or music procurement.",
          82),
    # Generic catch-alls (lower confidence — a real but unspecific match).
    _rule(r"director", "Leadership", "", "Medium", "Medium",
          "Director-level role — may influence production decisions.", 62),
    _rule(r"head of|manager|lead", "Leadership", "", "Medium", "Low",
          "Mid-level leadership — relevance depends on remit.", 60),
]

_UNCLASSIFIED = {
    "role_category": "Unclassified", "department": "", "priority": "Low",
    "music_relevance": "Low",
    "relevance_reason": "Unrecognized title — defaulted pending review.",
    "confidence": 0, "classified_by": "unclassified",
}


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def _classify_by_rules(title: str) -> Optional[Dict]:
    """Deterministic classification from the keyword rules, or None if nothing
    matches. confidence reflects how specific the matching rule is."""
    t = title or ""
    for pat, role, dept, prio, music, reason, conf in _RULES:
        if pat.search(t):
            return {"role_category": role, "department": dept, "priority": prio,
                    "music_relevance": music, "relevance_reason": reason,
                    "confidence": conf, "classified_by": "rules"}
    return None


def _threshold() -> int:
    try:
        return max(0, min(100, int(os.environ.get(
            "CHORDENTIAL_DM_CONFIDENCE_THRESHOLD", "60"))))
    except ValueError:
        return 60


def _default_llm(title: str, context: str) -> Optional[Dict]:
    """LLM title classifier — Render-only, off by default. Returns None unless an
    Anthropic key is present AND it's enabled (CHORDENTIAL_DM_LLM not falsey), so
    the engine is fully deterministic in tests and the sandbox."""
    if os.environ.get("CHORDENTIAL_DM_LLM", "1").strip().lower() in (
            "0", "false", "off", "no", ""):
        return None
    # One gate for every paid call: no key, engine off, nobody approved, or over
    # the cap → the free deterministic path. Unattended work never spends.
    from . import ai_budget
    ok, why = ai_budget.may_spend("decision-maker discovery")
    if not ok:
        return None
    try:                                            # pragma: no cover - networked
        import anthropic
        client = anthropic.Anthropic()
        model = os.environ.get("CHORDENTIAL_DM_MODEL") or "claude-haiku-4-5-20251001"
        prompt = (
            "Classify this advertising/creative-agency job title for a company that "
            "sells original music to agencies. Title: " + json.dumps(title) +
            ("\nContext: " + context[:500] if context else "") +
            "\nReturn JSON with keys: role_category, department, priority "
            "(one of Very High/High/Medium/Low/Very Low), music_relevance "
            "(High/Medium/Low), relevance_reason (one sentence on why this person "
            "would or wouldn't buy music), confidence (0-100). Be conservative; "
            "operations/admin titles are Low.")
        resp = client.messages.create(
            model=model, max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = next((b.text for b in resp.content if b.type == "text"), "")
        data = json.loads(raw) if raw else None
        if isinstance(data, dict) and data.get("role_category"):
            data["classified_by"] = "llm"
            return data
    except Exception:
        return None
    return None


def classify_title(conn, title: str, *, context: str = "",
                   llm: Optional[LLM] = None, threshold: Optional[int] = None) -> Dict:
    """Classify one title via the hybrid pipeline:

      1. Learned taxonomy lookup (cache hit → no recompute, no LLM).
      2. Deterministic rules. If confident (≥ threshold) → learn + return.
      3. LLM (only if available) for the unknown/low-confidence title → learn +
         return. Whatever it decides becomes a rule for next time.
      4. Otherwise return an explicit 'unclassified' default (not learned, so it
         gets another shot — by rules or a now-available LLM — on a later run).

    The returned dict carries role_category / department / priority /
    music_relevance / relevance_reason / confidence / classified_by.
    """
    thr = _threshold() if threshold is None else threshold
    norm = _normalize_title(title)
    if not norm:
        return dict(_UNCLASSIFIED)

    cached = db.taxonomy_get(conn, norm, bump=True)
    if cached is not None:
        return {"role_category": cached["role_category"],
                "department": cached["department"] or "",
                "priority": cached["priority"],
                "music_relevance": cached["music_relevance"],
                "relevance_reason": cached["relevance_reason"],
                "confidence": cached["confidence"],
                "classified_by": cached["source"]}

    ruled = _classify_by_rules(title)
    if ruled and ruled["confidence"] >= thr:
        _learn(conn, norm, ruled, source="rules")
        return ruled

    llm_fn = llm if llm is not None else _default_llm
    decided = None
    try:
        decided = llm_fn(title, context)
    except Exception:
        decided = None
    if isinstance(decided, dict) and decided.get("role_category"):
        result = {
            "role_category": decided.get("role_category", "Unclassified"),
            "department": decided.get("department", "") or "",
            "priority": decided.get("priority") if decided.get("priority") in _PRIORITY else "Medium",
            "music_relevance": decided.get("music_relevance") if decided.get("music_relevance") in ("High", "Medium", "Low") else "Medium",
            "relevance_reason": decided.get("relevance_reason", "") or "Classified by AI.",
            "confidence": int(decided.get("confidence") or 70),
            "classified_by": "llm",
        }
        _learn(conn, norm, result, source="llm",
               rationale=decided.get("relevance_reason", ""))
        return result

    if ruled:                       # a weak rule match beats nothing (but unlearned)
        return ruled
    return dict(_UNCLASSIFIED)


def _learn(conn, norm: str, result: Dict, *, source: str, rationale: str = "") -> None:
    """Write a confident classification into the taxonomy so it's a cache hit next
    time. The caller commits."""
    db.taxonomy_put(
        conn, norm,
        role_category=result["role_category"], department=result.get("department", ""),
        priority=result["priority"], music_relevance=result["music_relevance"],
        relevance_reason=result["relevance_reason"], confidence=result["confidence"],
        source=source, rationale=rationale or result["relevance_reason"])


# --------------------------------------------------------------------------- #
# Agent 3 — Contact Discovery: LinkedIn / email / phone / social. Public only.
# --------------------------------------------------------------------------- #
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_LINKEDIN = re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[^\s\"'<>]+", re.I)
_SOCIAL_HOSTS = {
    "twitter.com": "twitter", "x.com": "twitter", "instagram.com": "instagram",
    "facebook.com": "facebook", "youtube.com": "youtube", "vimeo.com": "vimeo",
    "tiktok.com": "tiktok", "dribbble.com": "dribbble", "behance.net": "behance",
}


def discover_contacts(card_html: str, person: Dict, page_url: str) -> Dict:
    """Public contact details for one person, from their card (and the page it sits
    on). Nothing is guessed: an email/handle is only taken if it's actually present."""
    out: Dict = {"linkedin": "", "email": "", "phone": "", "social": {}}
    anchors = _anchors(card_html or "")
    surname = (person.get("name", "").split()[-1].lower() if person.get("name") else "")

    for href, _ in anchors:
        low = href.lower()
        if not out["linkedin"] and "linkedin.com/in/" in low:
            out["linkedin"] = href.split("?")[0]
        elif low.startswith("mailto:") and not out["email"]:
            addr = href[7:].split("?")[0].strip()
            if _EMAIL.fullmatch(addr):
                out["email"] = addr
        elif low.startswith("tel:") and not out["phone"]:
            out["phone"] = href[4:].strip()
        else:
            host = _host(href)
            for sh, label in _SOCIAL_HOSTS.items():
                if host == sh or host.endswith("." + sh):
                    out["social"].setdefault(label, href.split("?")[0])

    if not out["linkedin"]:
        m = _LINKEDIN.search(card_html or "")
        if m:
            out["linkedin"] = m.group(0).split("?")[0]
    if not out["email"]:
        # prefer an address that contains the surname (more likely to be theirs)
        addrs = _EMAIL.findall(_text(_strip_chrome(card_html or "")))
        chosen = next((a for a in addrs if surname and surname in a.lower()), "")
        out["email"] = chosen or (addrs[0] if addrs else "")
    return out


# --------------------------------------------------------------------------- #
# Agent 4 — LinkedIn Verification: a structural name↔profile check (NOT a live
# fetch — LinkedIn blocks bots; this validates the URL we already found).
# --------------------------------------------------------------------------- #
def verify_linkedin(name: str, linkedin_url: str) -> bool:
    """True if ``linkedin_url`` is a real /in/ profile whose slug plausibly matches
    the person's name (a surname or given-name token appears in the slug). This is
    a structural check on a found URL, honestly not a live LinkedIn lookup."""
    if not linkedin_url or "linkedin.com/in/" not in linkedin_url.lower():
        return False
    slug = urlsplit(linkedin_url).path.rstrip("/").split("/in/")[-1].lower()
    slug_tokens = set(re.split(r"[-_]", re.sub(r"-\w{6,}$", "", slug)))
    name_tokens = {t for t in re.split(r"\s+", name.lower()) if len(t) >= 3}
    return bool(name_tokens & slug_tokens)


# --------------------------------------------------------------------------- #
# External search enrichment — fill LinkedIn / press from a web search when the
# agency's own site doesn't expose them. Off by default (the seam returns nothing
# until a provider is configured). Honesty rule: a searched LinkedIn is accepted
# ONLY if it structurally matches the person's name; press is off-site results.
# --------------------------------------------------------------------------- #
def _pick_linkedin(results: List[Dict], name: str) -> str:
    """The first /in/ profile in the results whose slug matches the person's name —
    so a wrong-person hit (or a non-matching top result) is never attached."""
    for r in results:
        url = (r.get("url") or "").split("?")[0]
        if "linkedin.com/in/" in url.lower() and verify_linkedin(name, url):
            return url
    return ""


def _press_from(results: List[Dict], exclude_hosts: set, limit: int = 5) -> List[Dict]:
    """Off-site, non-social search results → press mentions [{title, url}]."""
    out: List[Dict] = []
    seen = set()
    for r in results:
        url = (r.get("url") or "").strip()
        if not url:
            continue
        host = _host(url)
        if host in exclude_hosts or any(host.endswith("." + h) for h in exclude_hosts):
            continue
        if "linkedin.com" in host or host in _SOCIAL_HOSTS:
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append({"title": r.get("title") or url, "url": url.split("?")[0]})
        if len(out) >= limit:
            break
    return out


def search_enrich(person: Dict, contacts: Dict, agency_name: str,
                  agency_host: str, search: SearchFn) -> Dict:
    """Use the search seam to fill a missing LinkedIn (only if it verifies) and to
    find press mentions. Returns {"linkedin": str, "press": [...]}; both empty when
    search is off or nothing matches. Never invents — a found LinkedIn must match
    the person's name to be accepted."""
    name = person.get("name", "")
    out = {"linkedin": "", "press": []}
    if not name or search is None:
        return out
    if not contacts.get("linkedin"):
        try:
            hits = search(f'{name} {agency_name} linkedin')
        except Exception:
            hits = []
        out["linkedin"] = _pick_linkedin(hits or [], name)  # only a name-matching one
    try:
        hits = search(f'{name} {agency_name}')
    except Exception:
        hits = []
    out["press"] = _press_from(hits or [], {agency_host, "linkedin.com"})
    return out


# --------------------------------------------------------------------------- #
# Agent 5 — Confidence Scoring: deterministic 0–100 from the signals we collected.
# --------------------------------------------------------------------------- #
def score_confidence(person: Dict, contacts: Dict, classification: Dict,
                     linkedin_verified: bool) -> int:
    """How sure are we this is a real, correctly-identified decision maker? Each
    signal adds points (found-on-site is the floor); capped at 100."""
    score = 30                                   # found on the agency's own site
    if person.get("title"):
        score += 10
    if len(person.get("bio") or "") >= 80:
        score += 15
    if person.get("photo_url"):
        score += 5
    if contacts.get("linkedin"):
        score += 15
    if linkedin_verified:
        score += 15
    if contacts.get("email"):
        score += 10
    if classification.get("classified_by") in ("rules", "llm") and \
            classification.get("confidence", 0) >= _threshold():
        score += 10
    return min(100, score)


# --------------------------------------------------------------------------- #
# Agent 6 + orchestration — discover every decision maker for one agency
# --------------------------------------------------------------------------- #
def _dedup_key(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def discover_decision_makers(
    conn, agency_id: int, *, fetch: Optional[Fetch] = None,
    llm: Optional[LLM] = None, search: Optional[SearchFn] = None,
    reset: bool = False, threshold: Optional[int] = None,
) -> Dict:
    """Run the full pipeline for ONE agency and store every decision maker found.

    Visits the leadership/team/about pages, extracts every person, classifies and
    contacts each, scores confidence, and upserts them (collapsed on name). Stores
    them ALL — the scoring engine decides later who matters. ``reset`` clears the
    agency's existing decision makers first. With no ``fetch`` and scraping off, it
    reports 'blocked' rather than inventing anyone.
    """
    row = db.get_agency(conn, agency_id)
    if row is None:
        return {"agency_id": agency_id, "status": "error", "detail": "no such agency"}

    website = (row["website"] or "").strip()
    if website and not urlsplit(website).scheme:
        website = "https://" + website
    if not website:
        return {"agency_id": agency_id, "status": "error", "detail": "no website",
                "found": 0}

    if fetch is None:
        if not scrape_enabled():
            return {"agency_id": agency_id, "status": "blocked",
                    "detail": "scraping disabled", "found": 0}
        fetch = _default_fetch
    if search is None:
        search = web_search.search          # null seam until a provider is set

    agency_name = (row["company"] or "").strip()
    agency_host = _host(website)

    if reset:
        db.delete_decision_makers(conn, agency_id)
        db.save_agency_dm(conn, agency_id, {})
        conn.commit()

    cache: Dict[str, Tuple[str, bool]] = {}

    def get(url: str) -> str:
        if url not in cache:
            try:
                cache[url] = fetch(url)
            except Exception:
                cache[url] = ("", False)
        html, ok = cache[url]
        return html if ok else ""

    # Which pages name people: the homepage's people-concept links + the homepage
    # itself (small agencies list their team there).
    home = get(website)
    pages = [website]
    for absu, _anchor, concept in discover_links(home, website):
        if concept in _PEOPLE_CONCEPTS and absu not in pages:
            pages.append(absu)

    # Agent 1 — find every person across those pages, de-duplicated by name.
    people: List[Dict] = []
    by_name = {}
    for purl in pages:
        for person in extract_people(get(purl), purl):
            k = _dedup_key(person["name"])
            if k not in by_name:
                by_name[k] = person
                people.append(person)

    found = 0
    for person in people:
        page_html = get(person["source_url"])
        card = person.get("card") or page_html      # this person's own slice
        # Agent 2 — classify the title (rules → LLM → learn).
        cls = classify_title(conn, person["title"], context=person.get("bio", ""),
                             llm=llm, threshold=threshold)
        # Agent 3 — public contacts (from the agency's own page).
        contacts = discover_contacts(card or page_html, person, person["source_url"])
        # Agent 3b — external search: fill a missing LinkedIn (only if it matches)
        # and find press mentions. No-op unless a search provider is configured.
        extra = search_enrich(person, contacts, agency_name, agency_host, search)
        if extra["linkedin"]:
            contacts["linkedin"] = extra["linkedin"]
        # Agent 4 — structural LinkedIn verification.
        verified = verify_linkedin(person["name"], contacts["linkedin"])
        # Agent 5 — confidence.
        confidence = score_confidence(person, contacts, cls, verified)
        # Agent 6 — store.
        from datetime import datetime, timezone
        if db.upsert_decision_maker(conn, agency_id, {
            "dedup_key": _dedup_key(person["name"]),
            "name": person["name"], "title": person["title"],
            "department": cls["department"], "office": "", "reports_to": "",
            "bio": person.get("bio", ""), "photo_url": person.get("photo_url", ""),
            "linkedin": contacts["linkedin"], "email": contacts["email"],
            "phone": contacts["phone"],
            "social_json": json.dumps(contacts["social"]),
            "source_urls_json": json.dumps([person["source_url"]]),
            "press_json": json.dumps(extra["press"]),
            "role_category": cls["role_category"], "priority": cls["priority"],
            "music_relevance": cls["music_relevance"],
            "relevance_reason": cls["relevance_reason"],
            "confidence": confidence,
            "linkedin_verified": 1 if verified else 0,
            "classified_by": cls["classified_by"],
            "last_verified": datetime.now(timezone.utc).isoformat(),
        }):
            found += 1
    total = db.count_decision_makers(conn, agency_id)
    from datetime import datetime, timezone
    db.save_agency_dm(conn, agency_id, {
        "status": "complete", "found": found, "total": total,
        "last_run": datetime.now(timezone.utc).isoformat()})
    conn.commit()
    return {"agency_id": agency_id, "status": "complete", "found": found,
            "total": total, "people": len(people)}


# --------------------------------------------------------------------------- #
# Batch runner — discover decision makers across enriched agencies
# --------------------------------------------------------------------------- #
def discover_batch(
    conn, *, source: Optional[str] = None, limit: int = 50,
    fetch: Optional[Fetch] = None, llm: Optional[LLM] = None,
    search: Optional[SearchFn] = None, reset: bool = False,
) -> Dict:
    """Run discovery over agencies that have a website, one at a time. Resumable in
    the same spirit as enrichment: re-invoking re-processes (idempotent upserts), so
    a bounded ``limit`` per call keeps each run short."""
    rows = db.agencies_needing_decision_makers(conn, source=source, limit=limit)
    results: List[Dict] = []
    counts: Dict[str, int] = {}
    for r in rows:
        summary = discover_decision_makers(
            conn, r["id"], fetch=fetch, llm=llm, search=search, reset=reset)
        results.append(summary)
        counts[summary["status"]] = counts.get(summary["status"], 0) + 1
    return {"total": len(results), "complete": counts.get("complete", 0),
            "found": sum(s.get("found", 0) for s in results),
            "status_counts": counts, "results": results}
