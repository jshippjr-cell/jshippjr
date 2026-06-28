"""Company Intelligence Engine — turn the collected Agency Profile (Discovery +
Enrichment + Decision Makers) into a structured, evidence-backed intelligence
profile: how the agency operates, what it makes, who it serves, and how it likely
buys music.

Built as small evidence-based agents, mirroring the other engines. The cardinal
rule here is traceability: EVERY conclusion records the observed items it was
drawn from, and a confidence score. Nothing is fabricated — when the evidence is
thin the field says so ("additional evidence required") and confidence is low.
This is deterministic intelligence, not marketing copy and not an LLM guess: the
same profile in always yields the same output, and every value can point back to
why the system believes it.

Output (stored as agencies.intel_json) — each inferred field is
``{"value": ..., "evidence": [str, ...], "confidence": int}``:
  executive_summary, primary_industries, creative_focus, campaign_types,
  production_style, typical_clients, production_complexity, music_usage,
  music_procurement, momentum  +  overall_confidence, status, generated_at.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from . import db
from .enrichment import AgencyProfile, scrape_enabled  # noqa: F401 (parity seam)


def _field(value, evidence: List[str], confidence: int) -> Dict:
    return {"value": value, "evidence": evidence, "confidence": max(0, min(100, confidence))}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


# --------------------------------------------------------------------------- #
# Taxonomies (keyword → label). Matching is on observed text; the matched item
# becomes the evidence, so a conclusion always cites what produced it.
# --------------------------------------------------------------------------- #
_INDUSTRIES = {
    "Healthcare": ("health", "pharma", "medical", "wellness", "biotech", "hospital", "patient"),
    "Financial": ("financ", "bank", "fintech", "insurance", "investment", "payments"),
    "Luxury": ("luxury", "premium", "fashion", "jewel", "couture", "haute"),
    "Retail": ("retail", "ecommerce", "e-commerce", "shopper", "store", "commerce"),
    "Automotive": ("automotive", "car", "vehicle", "mobility", "motor", "ev"),
    "Gaming": ("gaming", "game", "esports", "console"),
    "Entertainment": ("entertainment", "film", "streaming", "studio", "tv network", "media"),
    "Government": ("government", "public sector", "civic", "gov", "municipal"),
    "Technology": ("technology", "software", "saas", "platform", "app", "tech", "ai"),
    "Sports": ("sport", "athletic", "fitness", "football", "basketball", "soccer"),
    "CPG": ("cpg", "consumer goods", "fmcg", "beverage", "food", "snack", "drink"),
    "Travel": ("travel", "hospitality", "airline", "hotel", "tourism", "resort"),
    "Nonprofit": ("nonprofit", "non-profit", "charity", "ngo", "foundation", "cause"),
}

_CONTENT_TYPES = {
    "Brand Films": ("brand film", "cinematic", "branded content", "film"),
    "Commercials": ("commercial", "tvc", "advert", "spot", "advertising campaign"),
    "Social": ("social", "tiktok", "instagram", "reels", "short-form", "ugc", "influencer"),
    "Experiential": ("experiential", "activation", "installation", "immersive", "popup", "pop-up"),
    "Broadcast": ("broadcast", "television", "national campaign", "tv campaign"),
    "Animation": ("animation", "animated", "motion", "cgi", "2d", "3d", "vfx"),
    "Product Launches": ("launch", "product launch", "reveal", "unveil"),
    "Corporate": ("corporate", "b2b", "internal comms", "employer brand"),
    "Documentary": ("documentary", "docu", "short film"),
    "Events": ("event", "conference", "festival", "live"),
    "Digital": ("digital", "interactive", "website", "web design", "app", "platform"),
}

# Major award programs that signal high-end production capability.
_MAJOR_AWARDS = re.compile(
    r"cannes|lion|d&ad|one show|effie|clio|grand prix|webby|emmy|ciclope|"
    r"andy award|cristal|epica", re.I)

# Observed-music signals → the music-usage flag they evidence.
_MUSIC_SIGNALS = [
    (re.compile(r"original score|original music|bespoke (?:music|score)|composed for", re.I), "Uses Original Score"),
    (re.compile(r"\bcompos(?:er|ed|ition)\b", re.I), "Uses Original Score"),
    (re.compile(r"licens(?:ed|ing) music|music licensing|sync(?:\s|hronization|hronisation)", re.I), "Uses Licensed Music"),
    (re.compile(r"stock music|library music|production library", re.I), "Uses Stock Libraries"),
    (re.compile(r"sound design|sound designer|audio post|sonic", re.I), "Uses Sound Design"),
    (re.compile(r"sonic brand|audio brand|sonic identity|audio identity", re.I), "Uses Sonic Branding"),
    (re.compile(r"orchestra|orchestral|symphon", re.I), "Uses Live Orchestra"),
    (re.compile(r"hybrid score|hybrid music", re.I), "Uses Hybrid Score"),
]


def _detect(corpus: str, taxonomy: Dict[str, Tuple[str, ...]]) -> List[Tuple[str, str]]:
    """[(label, matched_keyword)] for every taxonomy label whose keyword appears
    in the corpus (whole-word-ish), most-specific keyword as the evidence token."""
    hay = " " + re.sub(r"[^a-z0-9& ]+", " ", corpus.lower()) + " "
    out = []
    for label, keywords in taxonomy.items():
        for kw in keywords:
            if (" " + kw + " ") in hay or (" " + kw) in hay and len(kw) > 4:
                out.append((label, kw))
                break
    return out


# --------------------------------------------------------------------------- #
# Agent: Industry Classification
# --------------------------------------------------------------------------- #
def classify_industries(profile: AgencyProfile, row_industries: str) -> Dict:
    """Primary industries the agency serves — from the enriched industries list,
    the directory's industry tags, and keywords across services/clients/about."""
    found: Dict[str, str] = {}

    for it in profile.industries:                       # already-extracted tags
        for label, _kw in _detect(it, _INDUSTRIES):     # word-boundary match
            found.setdefault(label, f"Listed industry: “{it}”")
    corpus = " ".join(profile.services + profile.clients + [profile.description, row_industries or ""])
    for label, kw in _detect(corpus, _INDUSTRIES):
        found.setdefault(label, f"Mentioned ‘{kw}’ in services/clients/about")

    value = sorted(found)
    evidence = [found[k] for k in value]
    conf = 0 if not value else min(90, 45 + 12 * len(value))
    if not value:
        evidence = ["No industry signals found in the collected data — additional evidence required."]
    return _field(value, evidence, conf)


# --------------------------------------------------------------------------- #
# Agent: Creative Profile (creative focus + campaign types)
# --------------------------------------------------------------------------- #
def classify_creative_focus(profile: AgencyProfile) -> Tuple[Dict, Dict]:
    """Creative focus (formats from services + portfolio) and campaign types
    (the coarser campaign shapes those formats imply). Both evidence-cited."""
    svc_corpus = " ".join(profile.services + [profile.description])
    port_corpus = " ".join(profile.portfolio)
    focus: Dict[str, str] = {}
    for label, kw in _detect(svc_corpus + " " + port_corpus, _CONTENT_TYPES):
        where = "services" if any(k in svc_corpus.lower() for k in _CONTENT_TYPES[label]) else "portfolio"
        focus.setdefault(label, f"‘{kw}’ in {where}")
    focus_val = sorted(focus)
    focus_field = _field(
        focus_val, [focus[k] for k in focus_val] or
        ["No clear creative-format signals — additional evidence required."],
        0 if not focus_val else min(90, 45 + 11 * len(focus_val)))

    # Campaign types: a coarser read of scale/shape, derived from the same signals.
    types: Dict[str, str] = {}
    if {"Broadcast", "Brand Films", "Commercials"} & set(focus_val):
        types["Brand & Broadcast Campaigns"] = "Film/commercial/broadcast work observed"
    if {"Social"} & set(focus_val):
        types["Social / Short-form Campaigns"] = "Social/short-form work observed"
    if {"Experiential", "Events"} & set(focus_val):
        types["Experiential Activations"] = "Experiential/event work observed"
    if {"Product Launches"} & set(focus_val):
        types["Product Launches"] = "Launch work observed"
    if {"Digital", "Animation"} & set(focus_val):
        types["Digital & Content"] = "Digital/animation work observed"
    if len(profile.offices) >= 3 and ({"Broadcast", "Brand Films"} & set(focus_val)):
        types["Integrated Global Campaigns"] = f"{len(profile.offices)} offices + broadcast/film work"
    types_val = sorted(types)
    types_field = _field(
        types_val, [types[k] for k in types_val] or
        ["Insufficient signals to characterize campaign types."],
        0 if not types_val else min(88, 45 + 11 * len(types_val)))
    return focus_field, types_field


# --------------------------------------------------------------------------- #
# Agent: Production Complexity
# --------------------------------------------------------------------------- #
def _employee_count(raw: str) -> Optional[int]:
    nums = [int(n) for n in re.findall(r"\d+", raw or "")]
    return max(nums) if nums else None


def assess_production_complexity(profile: AgencyProfile, employees: str,
                                 creative_focus: List[str]) -> Dict:
    """Low / Medium / High, scored from the signals the spec calls out: offices,
    awards, clients, campaign scale, team size. Evidence is the signals found."""
    score = 0
    evidence: List[str] = []

    offices = [o for o in profile.offices if o]
    if len(offices) >= 3:
        score += 2
        evidence.append(f"Global footprint — {len(offices)} offices ({', '.join(offices[:3])}…)")
    elif len(offices) == 2:
        score += 1
        evidence.append(f"Multi-office — {', '.join(offices)}")

    majors = [a for a in profile.awards if _MAJOR_AWARDS.search(a)]
    if majors:
        score += 2
        evidence.append(f"{len(majors)} major industry award(s): {majors[0]}")
    elif profile.awards:
        score += 1
        evidence.append(f"{len(profile.awards)} award(s) listed")

    if {"Broadcast", "Brand Films", "Commercials"} & set(creative_focus):
        score += 1
        evidence.append("Film/broadcast work in portfolio (higher production values)")

    if len(profile.clients) >= 5:
        score += 1
        evidence.append(f"{len(profile.clients)} named clients incl. {profile.clients[0]}")

    n = _employee_count(employees)
    if n and n >= 100:
        score += 2
        evidence.append(f"Large team (~{employees})")
    elif n and n >= 50:
        score += 1
        evidence.append(f"Mid-size team (~{employees})")

    value = "High" if score >= 5 else "Medium" if score >= 3 else "Low" if score >= 1 else "Unknown"
    conf = 25 if score == 0 else min(95, 45 + score * 9)
    if score == 0:
        evidence = ["No scale signals (offices/awards/clients/team) observed — additional evidence required."]
    return _field(value, evidence, conf)


# --------------------------------------------------------------------------- #
# Agent: Observed Music Usage  (only what the work actually evidences)
# --------------------------------------------------------------------------- #
def detect_music_usage(profile: AgencyProfile) -> Dict:
    """Music characteristics OBSERVED in the collected work — never assumed. Each
    flag cites the phrase that evidenced it; absent evidence is stated plainly."""
    corpus = " ".join(profile.portfolio + profile.services + profile.awards +
                      [profile.description])
    flags: Dict[str, str] = {}
    for pat, flag in _MUSIC_SIGNALS:
        m = pat.search(corpus)
        if m and flag not in flags:
            flags[flag] = f"Observed ‘{m.group(0)}’ in collected work"
    value = list(flags)
    if not value:
        return _field([], ["No direct evidence of music usage on the collected pages — "
                           "additional research required (e.g. credits, case-study detail)."], 20)
    return _field(value, [flags[k] for k in value], min(85, 50 + 10 * len(value)))


# --------------------------------------------------------------------------- #
# Agent: Likely Music Procurement Characteristics
# --------------------------------------------------------------------------- #
def infer_procurement(complexity: Dict, music_usage: Dict, decision_makers: List) -> Dict:
    """How the agency likely BUYS music — reasoned from production complexity, the
    decision makers found, and any observed music usage. Evidence-cited; explicit
    when there isn't enough to say."""
    parts: List[str] = []
    evidence: List[str] = []

    music_people = [d for d in decision_makers
                    if (d["role_category"] in ("Production", "Music", "Creative")
                        and d["priority"] in ("Very High", "High"))]
    if music_people:
        d = music_people[0]
        parts.append(f"likely commissions music per-project through senior "
                     f"production/creative leads")
        evidence.append(f"Decision maker: {d['name']}, {d['title']} ({d['priority']})")

    cval = complexity["value"]
    if cval == "High":
        parts.append("high production values point to budget for original/commissioned music")
        evidence.append("Production complexity: High")
    elif cval == "Medium":
        parts.append("a mix of commissioned and licensed music is plausible")
        evidence.append("Production complexity: Medium")
    elif cval == "Low":
        parts.append("lower production complexity suggests licensed or library music")
        evidence.append("Production complexity: Low")

    if music_usage["value"]:
        parts.append("observed work already uses " +
                     ", ".join(v.replace("Uses ", "").lower() for v in music_usage["value"]))
        evidence.extend(music_usage["evidence"])

    if not parts:
        return _field("Insufficient evidence to characterize music procurement — "
                      "additional research required.", [], 20)
    text = "This agency " + "; ".join(parts) + "."
    conf = min(90, 35 + 12 * len(evidence))
    return _field(text, evidence, conf)


# --------------------------------------------------------------------------- #
# Agent: Agency Momentum
# --------------------------------------------------------------------------- #
_MOMENTUM_NEWS = [
    (re.compile(r"\bwins?\b|won|appoint|named|secures?", re.I), "Winning new accounts"),
    (re.compile(r"launch|unveil|debut", re.I), "Launching work/products"),
    (re.compile(r"open(?:s|ed|ing)? (?:a )?(?:new )?office|expand", re.I), "Expanding / new offices"),
    (re.compile(r"acqui|merg", re.I), "Acquired / merged"),
    (re.compile(r"hir(?:e|ing)|joins?|appoints?", re.I), "Hiring / new leadership"),
]


def assess_momentum(profile: AgencyProfile) -> Dict:
    tags: Dict[str, str] = {}
    if profile.open_roles or profile.careers_url:
        n = len(profile.open_roles)
        tags["Hiring"] = (f"{n} open role(s) listed" if n else "Active careers page")
    for item in profile.news:
        title = item.get("title", "") if isinstance(item, dict) else str(item)
        for pat, tag in _MOMENTUM_NEWS:
            if pat.search(title) and tag not in tags:
                tags[tag] = f"News: “{title[:80]}”"
    if profile.news and "Recent press activity" not in tags and len(tags) < 2:
        tags["Recent press activity"] = f"{len(profile.news)} recent news item(s)"
    if [a for a in profile.awards if _MAJOR_AWARDS.search(a)]:
        tags["Award-winning"] = "Major industry awards listed"
    if len([o for o in profile.offices if o]) >= 2:
        tags["Multi-market presence"] = f"{len(profile.offices)} offices"

    value = list(tags)
    if not value:
        return _field(["Stable"], ["No recent hiring, news, awards, or expansion "
                                   "signals observed in the collected data."], 30)
    return _field(value, [tags[k] for k in value], min(88, 45 + 10 * len(value)))


# --------------------------------------------------------------------------- #
# Agent: Executive Summary (assembled from the evidence above — not free-write)
# --------------------------------------------------------------------------- #
def build_summary(name: str, profile: AgencyProfile, industries: Dict,
                  creative_focus: Dict, complexity: Dict, music_usage: Dict,
                  offices: List[str]) -> Dict:
    evidence: List[str] = []
    bits: List[str] = []

    scale = ""
    if len(offices) >= 3:
        scale = "global "
        evidence.append(f"{len(offices)} offices")
    elif len(offices) == 2:
        scale = "multi-office "

    inds = industries["value"]
    ind_phrase = (", ".join(inds[:3]) + " " if inds else "")
    bits.append(f"{name} is a {scale}{ind_phrase}agency".replace("  ", " ").strip())
    if inds:
        evidence.append("Industries: " + ", ".join(inds[:3]))

    if creative_focus["value"]:
        bits.append("whose observed work spans " + ", ".join(v.lower() for v in creative_focus["value"][:5]))
        evidence.append("Creative focus: " + ", ".join(creative_focus["value"][:5]))

    cval = complexity["value"]
    if cval in ("High", "Medium"):
        bits.append(f"with {cval.lower()} production complexity")
        evidence.extend(complexity["evidence"][:2])

    # "{name} is a … agency, whose work spans …, with … production complexity."
    summary = bits[0]
    if len(bits) > 1:
        summary += ", " + bits[1]
    if len(bits) > 2:
        summary += ", " + bits[2]
    summary = summary.rstrip(".") + "."

    if music_usage["value"]:
        mu = ", ".join(v.replace("Uses ", "").lower() for v in music_usage["value"])
        summary += f" Observed work already uses {mu}."
        evidence.extend(music_usage["evidence"][:2])
    elif cval == "High":
        summary += (" Its high-production-value work is the kind where original "
                    "music is likely to play an important role — though music use "
                    "isn't directly evidenced yet and needs confirmation.")
    else:
        summary += " Music usage is not directly evidenced in the collected data and requires further research."

    conf = min(92, 30 + 8 * len(evidence))
    return _field(summary, evidence or ["Limited data collected — summary is preliminary."], conf)


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def _production_style(creative_focus: List[str], complexity: Dict) -> Dict:
    styles: Dict[str, str] = {}
    cf = set(creative_focus)
    if {"Brand Films", "Broadcast", "Commercials"} & cf and complexity["value"] in ("High", "Medium"):
        styles["Cinematic / high-production-value"] = "Film/broadcast work + production scale"
    if {"Social"} & cf:
        styles["Fast-turnaround social / short-form"] = "Social/short-form work observed"
    if {"Animation"} & cf:
        styles["Animation / motion-led"] = "Animation work observed"
    if {"Experiential", "Events"} & cf:
        styles["Experiential / live"] = "Experiential/event work observed"
    if {"Digital"} & cf and not styles:
        styles["Digital / interactive"] = "Digital work observed"
    value = list(styles)
    if not value:
        return _field([], ["Production style not determinable from the collected data."], 25)
    return _field(value, [styles[k] for k in value], min(85, 45 + 12 * len(value)))


def generate_intelligence(conn, agency_id: int) -> Dict:
    """Build and store the Company Intelligence Profile for one agency from its
    collected data. Returns a summary dict; the profile lives in agencies.intel_json.
    Runs purely on stored data (no network), so it's deterministic and always safe
    to (re-)run — re-running just refreshes from the latest collected data."""
    row = db.get_agency(conn, agency_id)
    if row is None:
        return {"agency_id": agency_id, "status": "error", "detail": "no such agency"}

    state = db.get_agency_enrichment(conn, agency_id) or {}
    profile = AgencyProfile.from_dict(state.get("profile"))
    if not profile.name:
        profile.name = row["company"] or ""
    decision_makers = [dict(d) for d in db.list_decision_makers(conn, agency_id)]
    offices = [o for o in profile.offices if o]

    industries = classify_industries(profile, row["industries"])
    creative_focus, campaign_types = classify_creative_focus(profile)
    complexity = assess_production_complexity(profile, row["employees"],
                                              creative_focus["value"])
    production_style = _production_style(creative_focus["value"], complexity)
    music_usage = detect_music_usage(profile)
    procurement = infer_procurement(complexity, music_usage, decision_makers)
    momentum = assess_momentum(profile)
    typical_clients = _field(
        profile.clients,
        [f"Named on the agency's site ({profile.sources.get('clients', row['website'])})"]
        if profile.clients else ["No client names collected — additional evidence required."],
        min(85, 40 + 9 * len(profile.clients)) if profile.clients else 20)
    summary = build_summary(profile.name, profile, industries, creative_focus,
                            complexity, music_usage, offices)

    enrichment_done = state.get("status") == "complete"
    inputs_present = sum(bool(x) for x in (
        industries["value"], creative_focus["value"], profile.portfolio,
        profile.awards, profile.clients, decision_makers, profile.news, offices))
    overall = min(95, 15 + inputs_present * 9)
    if not enrichment_done:
        overall = min(overall, 35)

    intel = {
        "status": "complete",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "enrichment_complete": enrichment_done,
        "executive_summary": summary,
        "primary_industries": industries,
        "creative_focus": creative_focus,
        "campaign_types": campaign_types,
        "production_style": production_style,
        "typical_clients": typical_clients,
        "production_complexity": complexity,
        "music_usage": music_usage,
        "music_procurement": procurement,
        "momentum": momentum,
        "decision_makers": [
            {"name": d["name"], "title": d["title"], "priority": d["priority"],
             "music_relevance": d["music_relevance"]} for d in decision_makers[:10]],
        "overall_confidence": overall,
        "note": ("" if enrichment_done else
                 "Enrichment hasn't completed for this agency, so this profile is "
                 "preliminary — confidence is capped until more data is collected."),
    }
    db.save_agency_intel(conn, agency_id, intel)
    conn.commit()
    return {"agency_id": agency_id, "status": "complete",
            "overall_confidence": overall}


def generate_batch(conn, *, source: Optional[str] = None, limit: int = 50) -> Dict:
    """Generate intelligence for agencies that are enriched but not yet profiled.
    Resumable: re-invoking re-processes nothing already complete (the queue
    advances via the intel_json marker). Pure computation — no network."""
    rows = db.agencies_needing_intelligence(conn, source=source, limit=limit)
    done = 0
    for r in rows:
        if generate_intelligence(conn, r["id"]).get("status") == "complete":
            done += 1
    return {"total": len(rows), "generated": done}
