"""Campaign Intelligence (Creative OS) — the canonical, LIVING per-engagement record.

The stable spine every module inherits from and contributes back to, through one
provenance model. This module is the DOMAIN layer: the field catalog (facets × keys ×
kinds), the kind-aware disposition rules, the provenance API (contribute / dispose /
seed), and the read view. Storage primitives live in db.py; the design is in
docs/architecture/CAMPAIGN_INTELLIGENCE.md.

Every fact carries three orthogonal dimensions:
  • facet — which body of knowledge (engagement/buyer/direction/commercial/…)
  • kind  — what KIND of knowledge (fact / insight / recommendation / open_question)
  • provenance — sources[] (who says so) + status (how disposed) — machine proposes,
    the human disposes (Constitution §4.1).
"""
from __future__ import annotations

import re
from typing import List, Optional

from . import db

FACETS = ["engagement", "buyer", "direction", "commercial", "relationship", "outcome",
          "observed"]
KINDS = ["fact", "insight", "recommendation", "open_question"]

# The disposition lifecycle is KIND-AWARE, but there is always ONE gate: a human moves
# a field from its OPEN state to its DISPOSED state (§4bis). CI-1 wires the single
# primary disposition per kind; richer verbs (deferred/declined/dismissed) come later.
KIND_OPEN_STATUS = {
    "fact": "needs_review", "insight": "noted",
    "recommendation": "open", "open_question": "open",
}
KIND_DISPOSED_STATUS = {
    "fact": "confirmed", "insight": "acknowledged",
    "recommendation": "accepted", "open_question": "answered",
}
KIND_LABEL = {
    "fact": "Fact", "insight": "Insight",
    "recommendation": "Recommendation", "open_question": "Open question",
}
KIND_DISPOSE_VERB = {  # the button label for disposing an open field
    "fact": "Confirm", "insight": "Acknowledge",
    # "Mark answered" was a lie by label: it closed the question and kept nothing. The
    # producer's read now has a real answer box (detail.html) that records the answer as a
    # fact, so this verb is only ever the WITHOUT-an-answer path.
    "recommendation": "Accept", "open_question": "Dismiss",
}

DISPOSED_STATUSES = set(KIND_DISPOSED_STATUS.values())

FACET_LABEL = {
    "engagement": "The engagement", "buyer": "The buyer",
    "direction": "Creative direction", "commercial": "Commercial",
    "relationship": "Relationship", "outcome": "Outcome",
    "observed": "Observed facts",
}

# The canonical, always-editable fields the Opportunity page shows as labeled slots —
# filled or "not yet observed," never guessed (ADR-0013 / intake-prd §18.4). Ordered for
# display, grouped by facet. `opp` marks a fact whose confirmed value writes back to the
# opportunity's own column so downstream engines recompute (§18.5). The dynamic epistemic
# kinds (Producer Debrief / Risks / Recommendations / Open questions) are NOT fixed slots —
# they render as lists of the debrief-contributed items.
CANONICAL_FIELDS = [
    ("engagement", "business_objective", "fact", "Business objective",
     "What the brand is trying to achieve", None),
    ("engagement", "budget_band", "fact", "Budget", "e.g. $18,000–$24,000", "budget"),
    ("engagement", "deadline", "fact", "Timeline", "Air date / delivery deadline", None),
    ("engagement", "deliverables", "fact", "Deliverables",
     "Spot lengths, cutdowns, stems…", None),
    ("buyer", "decision_makers", "fact", "Decision makers",
     "Who signs off / final approver", None),
    ("buyer", "brand_notes", "fact", "Brand notes", "How the brand shows up", None),
    ("buyer", "agency_notes", "fact", "Agency notes", "How the agency works", None),
    ("direction", "campaign_objective", "fact", "Campaign objective",
     "What this piece of music is for", None),
    ("direction", "emotional_arc", "fact", "Emotional arc",
     "The feeling / journey the music carries", None),
    ("direction", "reference_playlist", "fact", "Reference playlist",
     "Tracks / artists cited as touchstones", None),
]
# Engine-proposed keys are STEERED toward the canonical slots by a prompt guide, and a
# model that ignores the guide is not a bug you fix by asking louder. On the live
# comprehension call every trap was read correctly and then filed under a name of the
# model's own choosing: the $45,000 landed in "Production Budget", the conditional launch
# in "Seasonality", the asset list inside that same "Production Budget" — while Budget,
# Timeline and Deliverables sat EMPTY. Everything downstream (the estimate, the brief, the
# proposal) reads the canonical slots, so a perfect read filed beside them is worth
# nothing. Case alone caused a second bug: "Business Objective" rendered as a duplicate
# field beside "Business objective".
#
# So the mapping is deterministic, and happens after extraction rather than by instruction.
#
# AN ALIAS IS A CLAIM THAT TWO NAMES MEAN THE SAME THING, and `production_budget` was not
# one. It was added because call one's model called the MUSIC budget "Production Budget";
# on call two a speaker used the words for what they normally mean — "total production on
# the film is about nine hundred thousand" — and the alias walked that $900,000 straight
# into the Budget field, past a value that even said "(not the music)". A distractor
# promoted by our own map is worse than no map: an empty Budget asks a question, a Budget
# reading $900,000 does not. Only names that can ONLY mean the music fee belong here.
_KEY_ALIASES = {
    "budget": "budget_band", "budget_range": "budget_band", "music_budget": "budget_band",
    "music_fee": "budget_band", "fee": "budget_band", "budget_figure": "budget_band",
    "timeline": "deadline", "seasonality": "deadline", "launch_timing": "deadline",
    "air_date": "deadline", "delivery_date": "deadline", "launch_window": "deadline",
    "schedule": "deadline", "timing": "deadline",
    "assets": "deliverables", "formats": "deliverables", "deliverable": "deliverables",
    "deliverables_list": "deliverables", "spot_lengths": "deliverables",
    "references": "reference_playlist", "reference_tracks": "reference_playlist",
    "sonic_references": "reference_playlist", "reference_artists": "reference_playlist",
    "decision_maker": "decision_makers", "approver": "decision_makers",
    "final_approver": "decision_makers",
    "objective": "business_objective", "brand": "brand_notes", "agency": "agency_notes",
    "mood": "emotional_arc", "emotional_direction": "emotional_arc",
}


def canonical_key(key: str) -> str:
    """Snap a proposed field name onto the canonical slot it means, if it means one.

    Case and punctuation normalise first, so "Business Objective" and "business_objective"
    are ONE field rather than two. A name with no canonical meaning is left alone — that
    is the dynamic field doing its job, and it must keep working."""
    k = re.sub(r"[^a-z0-9]+", "_", (key or "").strip().lower()).strip("_")
    if any(k == ck for _f, ck, _kind, _l, _p, _o in CANONICAL_FIELDS):
        return k
    return _KEY_ALIASES.get(k, k)


CANONICAL_BY_KEY = {(f, k, kind): (label, ph, opp)
                    for f, k, kind, label, ph, opp in CANONICAL_FIELDS}
# A canonical key has exactly ONE home, so the facet is not the model's to choose.
CANONICAL_FACET_FOR_KEY = {k: f for f, k, _kind, _l, _p, _o in CANONICAL_FIELDS}

# What a COMPOSER needs from the call, chosen — not the whole intelligence dump.
#
# Dumping every canonical field was the lazy route and a dangerous one: it put the
# BUDGET in front of the person we are negotiating a rate with, along with the decision
# makers and how the agency behaves. None of that helps anyone write music, and one of
# them is commercially ours. Reported live.
#
# A composer needs to know what the music is FOR, how it should FEEL, what to write TO,
# what to DELIVER and by WHEN. That is the whole list, in reading order, and it is an
# allowlist so a new canonical field cannot leak into the room by being added.
BRIEF_KEYS = (
    ("campaign_objective", "What this music is for"),
    ("business_objective", "What the brand is trying to achieve"),
    ("emotional_arc", "The feeling it carries"),
    ("reference_playlist", "Touchstones they named"),
    ("deliverables", "What you deliver"),
    ("deadline", "When it is needed"),
)
# Never shown to a creator. Commercial and relationship facts: our side of the table.
BRIEF_WITHHELD = ("budget_band", "decision_makers", "agency_notes", "brand_notes")


def composer_brief(view: dict) -> list:
    """The call, curated for the person writing the music.

    An ALLOWLIST, deliberately: `BRIEF_WITHHELD` is documentation of intent, but what
    protects the budget is that nothing outside `BRIEF_KEYS` is ever returned. Values are
    trimmed to a readable length — a brief that has to be scrolled is one nobody reads,
    and the full record is always on the operator's page.
    """
    fields = dict((view or {}).get("fields") or {})
    out = []
    for key, label in BRIEF_KEYS:
        val = " ".join((fields.get(key) or "").split())
        if not val:
            continue
        if len(val) > 320:
            val = val[:317].rstrip(" ,;.") + "…"
        out.append({"label": label, "value": val, "key": key})
    return out


def arrived_by_alias(key: str) -> bool:
    """Did this field reach its slot under its own name, or through the alias map?

    The difference decides a collision. An exact key is the extractor naming the slot; an
    alias is US deciding two words mean the same thing, which is a weaker claim and the one
    that has been wrong."""
    k = re.sub(r"[^a-z0-9]+", "_", (key or "").strip().lower()).strip("_")
    return k in _KEY_ALIASES and not any(
        k == ck for _f, ck, _kind, _l, _p, _o in CANONICAL_FIELDS)


def canonical_slot(facet: str, key: str, kind: str = "fact"):
    """Snap a proposed (facet, key) onto the canonical slot it means.

    Snapping the KEY alone was not enough, and the second live call proved it. The budget
    was read perfectly — *"the number I've been given is roughly 25. No, no, 30,000, all in
    including any licensing"* — and filed as **commercial/budget_band**. The key was already
    canonical; the FACET was not. The Budget slot is keyed (engagement, budget_band, fact),
    so the lookup missed by one column and the field on the page stayed empty while the
    correct answer sat in the evidence list beside it. Deliverables went the same way.

    A canonical key belongs to exactly one facet — that is what makes it canonical — so the
    facet is derived here rather than accepted. Only facts are moved: an *open question*
    about the budget is legitimately an open question, not a value for the slot.

    A key with no canonical meaning is returned untouched, facet and all. That is the
    dynamic field doing its job, and it must keep working.
    """
    k = canonical_key(key)
    kind = (kind or "fact").strip().lower() or "fact"
    if kind == "fact" and k in CANONICAL_FACET_FOR_KEY:
        return CANONICAL_FACET_FOR_KEY[k], k, kind
    return (facet or "").strip().lower(), k, kind
CANONICAL_FACET_ORDER = ["engagement", "buyer", "direction"]


def is_open(status: str) -> bool:
    """True when a field still awaits a human's disposition."""
    return status not in DISPOSED_STATUSES


def has_conflict(field_row) -> bool:
    """A machine value that disagrees with a human-owned value is parked as a conflict."""
    try:
        return bool(field_row["proposed_value"])
    except (KeyError, IndexError):
        return False


# --------------------------------------------------------------------------- #
# Provenance API — contribute (any module) + dispose (the human gate).
# --------------------------------------------------------------------------- #
def contribute(conn, ci_id: int, facet: str, key: str, value: str, *,
               kind: str = "fact", source: str, contributed_by: str = "",
               confidence: Optional[int] = None, is_concern: bool = False,
               value_json=None, confirmed: bool = False,
               capture_id: Optional[int] = None) -> int:
    """Contribute a fact/insight/recommendation/open_question to Campaign Intelligence
    through the provenance model — the ONE way every module (intake, proposal, workspace,
    production, delivery, client success, retrospective) writes. Lands at the OPEN status
    for its kind (machine/non-owner proposes) unless ``confirmed`` (the operator, or an
    owner writing its own facet, disposing directly). Merges the source; stamps the raw
    evidence ``capture_id`` (ADR-0014); logs the event."""
    if facet not in FACETS or kind not in KINDS:
        raise ValueError(f"bad facet/kind: {facet}/{kind}")
    # Never clobber a human-owned value (ADR-0013). If a human has authored/confirmed this
    # exact field and the machine now proposes a DIFFERENT non-empty value, park it as a
    # conflict (proposed_value) for the operator to resolve — the human value stands.
    existing = conn.execute(
        "SELECT * FROM campaign_intelligence_field WHERE ci_id=? AND facet=? AND key=? AND kind=?",
        (ci_id, facet, key, kind)).fetchone()
    if (existing is not None and not confirmed and existing["human_value"]
            and (value or "").strip()
            and (value or "").strip() != (existing["value"] or "").strip()):
        db.set_ci_field(conn, existing["id"], proposed_value=value,
                        proposed_source=source)
        db.add_ci_event(conn, ci_id, actor=(contributed_by or source), verb="proposed",
                        facet=facet, key=key, kind=kind,
                        from_value=(existing["value"] or "")[:200],
                        to_value=value[:200], source=source, capture_id=capture_id)
        return int(existing["id"])
    status = KIND_DISPOSED_STATUS[kind] if confirmed else KIND_OPEN_STATUS[kind]
    fid = db.upsert_ci_field(
        conn, ci_id, facet, key, kind, value=value, value_json=value_json,
        source=source, status=status, origin=source, confidence=confidence,
        is_concern=is_concern, contributed_by=contributed_by or source, capture_id=capture_id)
    if confirmed:
        db.set_ci_field(conn, fid, human_value=True)  # operator-confirmed → authoritative
    db.add_ci_event(conn, ci_id, actor=(contributed_by or source),
                    verb=("confirmed" if confirmed else "contributed"),
                    facet=facet, key=key, kind=kind, to_value=value[:200], source=source,
                    capture_id=capture_id)
    return fid


def dispose(conn, field_row, actor: str = "operator") -> None:
    """The human disposition gate: move an open field to its disposed state for its kind
    (confirm a fact, acknowledge an insight, accept a recommendation, answer a question).
    Only a human calls this — the machine can only ever leave a field OPEN."""
    kind = field_row["kind"]
    new_status = KIND_DISPOSED_STATUS.get(kind, "confirmed")
    db.set_ci_field(conn, field_row["id"], status=new_status, human_value=True,
                    add_source=actor)
    db.add_ci_event(conn, field_row["ci_id"], actor=actor, verb=new_status,
                    facet=field_row["facet"], key=field_row["key"], kind=kind)


def edit_field(conn, field_id: int, value: str, *, actor: str = "operator"):
    """A HUMAN edit is authoritative (ADR-0013): it sets the value, marks the field
    human-owned (the machine can never silently overwrite it afterward — later
    disagreements park as conflicts), disposes it, appends the operator to provenance,
    resolves any pending conflict, and logs the change. Returns the updated row."""
    row = db.get_ci_field(conn, field_id)
    if row is None:
        return None
    new_status = KIND_DISPOSED_STATUS.get(row["kind"], "confirmed")
    updated = db.set_ci_field(conn, field_id, value=value.strip(), status=new_status,
                              human_value=True, add_source=actor, clear_proposed=True)
    db.add_ci_event(conn, row["ci_id"], actor=actor, verb="edited",
                    facet=row["facet"], key=row["key"], kind=row["kind"],
                    from_value=(row["value"] or "")[:200], to_value=value.strip()[:200],
                    source=actor)
    return updated


def resolve_conflict(conn, field_id: int, accept: bool, *, actor: str = "operator"):
    """Resolve a surfaced conflict: ``accept`` takes the machine's proposed value as the new
    authoritative value; otherwise the human value stands. Either way the conflict clears
    and the choice is logged (machine proposes, human disposes)."""
    row = db.get_ci_field(conn, field_id)
    if row is None or not row["proposed_value"]:
        return row
    if accept:
        updated = db.set_ci_field(
            conn, field_id, value=row["proposed_value"], human_value=True,
            add_source=row["proposed_source"] or "machine", clear_proposed=True)
        verb = "accepted_proposed"
    else:
        updated = db.set_ci_field(conn, field_id, clear_proposed=True)
        verb = "kept_own"
    db.add_ci_event(conn, row["ci_id"], actor=actor, verb=verb,
                    facet=row["facet"], key=row["key"], kind=row["kind"],
                    to_value=(row["proposed_value"] or "")[:200])
    return updated


# --------------------------------------------------------------------------- #
# Lazy creation + seeding — a CI for every campaign, populated from upstream.
# --------------------------------------------------------------------------- #
def ensure_for_campaign(conn, campaign_row):
    """Get the Campaign Intelligence for a campaign — ADOPTING the opportunity's existing CI
    in place if there is one (ADR-0013: inherit, never recreate). Only when no upstream CI
    exists (an engagement that reached production without any intake) is one lazily created
    and seeded here. Idempotent."""
    existing = db.ci_for_campaign(conn, campaign_row["id"])
    if existing is not None:
        return existing
    # Inherit: the opportunity already carries the CI — adopt it onto this campaign.
    if campaign_row["opp_id"]:
        opp_ci = db.ci_for_opportunity(conn, campaign_row["opp_id"])
        if opp_ci is not None:
            db.attach_ci_to_campaign(
                conn, opp_ci["id"], campaign_id=campaign_row["id"],
                project_id=campaign_row["project_id"], agency_id=campaign_row["agency_id"])
            db.add_ci_event(conn, opp_ci["id"], actor="system", verb="inherited")
            _seed_direction_cards(conn, opp_ci["id"], campaign_row)
            return db.get_campaign_intelligence(conn, opp_ci["id"])
    ci_id = db.create_campaign_intelligence(
        conn, campaign_id=campaign_row["id"], opp_id=campaign_row["opp_id"],
        agency_id=campaign_row["agency_id"], project_id=campaign_row["project_id"],
        title=campaign_row["title"], brand=campaign_row["brand"],
        agency_client=campaign_row["agency_client"])
    _seed(conn, ci_id, campaign_row)
    db.add_ci_event(conn, ci_id, actor="system", verb="seeded")
    return db.get_campaign_intelligence(conn, ci_id)


def ensure_for_opportunity(conn, opp_row):
    """Get (or lazily create + seed) the Campaign Intelligence anchored on an OPPORTUNITY
    (ADR-0013). This is where CI is born — while qualifying/pursuing, before any campaign
    exists. Seeds engagement facts from the opportunity's own fields and a buyer snapshot
    from the linked/resolved agency. Empty upstream → empty CI (honesty: nothing invented).
    Idempotent (one CI per opportunity)."""
    existing = db.ci_for_opportunity(conn, opp_row["id"])
    if existing is not None:
        return existing
    agency_id = db.resolve_opportunity_agency(conn, opp_row)
    ci_id = db.create_campaign_intelligence(
        conn, campaign_id=None, opp_id=opp_row["id"], agency_id=agency_id,
        project_id=None, title=opp_row["need"], brand=opp_row["client"],
        agency_client=opp_row["client"])
    _seed_from_opportunity(conn, ci_id, opp_row, agency_id)
    db.add_ci_event(conn, ci_id, actor="system", verb="seeded")
    return db.get_campaign_intelligence(conn, ci_id)


def get_for_campaign(conn, campaign_row):
    return db.ci_for_campaign(conn, campaign_row["id"])


def get_for_opportunity(conn, opp_row):
    return db.ci_for_opportunity(conn, opp_row["id"])


def _txt(v) -> str:
    """Best-effort display string from a maybe-structured intel value ({value:…}, list, …)."""
    if v is None:
        return ""
    if isinstance(v, dict):
        v = v.get("value", v.get("summary", ""))
    if isinstance(v, list):
        return ", ".join(_txt(x) for x in v if x)
    return str(v).strip()


def _budget_band(bmin, bmax) -> str:
    if not (bmin or bmax):
        return ""
    return (f"${int(bmin):,} to ${int(bmax):,}" if bmin and bmax and bmin != bmax
            else f"${int(bmax or bmin):,}")


def _seed_agency_buyer(conn, ci_id: int, agency_id) -> None:
    """Snapshot the linked Agency/Company Intelligence into buyer facts (the moat thread)."""
    if not agency_id:
        return
    intel = db.get_agency_intel(conn, agency_id) or {}
    for key, ik in (("how_they_work", "executive_summary"),
                    ("production_complexity", "production_complexity"),
                    ("music_characteristics", "music_usage"),
                    ("typical_clients", "typical_clients"),
                    ("campaign_types", "campaign_types")):
        val = _txt(intel.get(ik))
        if val:
            contribute(conn, ci_id, "buyer", key, val,
                       source="agency_intelligence", contributed_by="system")
    state = db.get_agency_enrichment(conn, agency_id) or {}
    profile = (state.get("profile") or {})
    if profile.get("portfolio"):
        contribute(conn, ci_id, "buyer", "previous_campaigns",
                   _txt(profile["portfolio"]), source="agency_intelligence",
                   contributed_by="system", value_json=profile["portfolio"])


def _seed_direction_cards(conn, ci_id: int, campaign) -> None:
    """Fold the increment-1 creative-direction cards into CI direction facts (the STATED
    brief is a fact; a section marked complete is disposed). Used when a campaign inherits
    or is seeded — idempotent through the upsert."""
    for row in conn.execute(
            "SELECT * FROM campaign_direction WHERE campaign_id = ?", (campaign["id"],)):
        body = (row["body"] or "").strip()
        if body:
            contribute(conn, ci_id, "direction", row["section"], body,
                       source="workspace", contributed_by="operator",
                       confirmed=bool(row["complete"]))


def _seed_from_opportunity(conn, ci_id: int, opp, agency_id) -> None:
    """Seed CI from an opportunity's own fields (ADR-0013) — engagement facts + a buyer
    snapshot + the known decision-maker. Everything sourced ``opportunity``/needs_review."""
    if opp["client"]:
        contribute(conn, ci_id, "buyer", "brand_notes", opp["client"],
                   source="opportunity", contributed_by="system")
    band = _budget_band(opp["budget_min"], opp["budget_max"])
    if band:
        contribute(conn, ci_id, "engagement", "budget_band", band,
                   source="opportunity", contributed_by="system")
    if opp["description"]:
        contribute(conn, ci_id, "engagement", "business_objective",
                   _txt(opp["description"])[:400], source="opportunity",
                   contributed_by="system")
    # a known contact → the decision-maker starting point
    if opp["contact_name"]:
        who = opp["contact_name"] + (f" ({opp['contact_role']})"
                                     if opp["contact_role"] else "")
        contribute(conn, ci_id, "buyer", "decision_makers", who,
                   source="opportunity", contributed_by="system")
    _seed_agency_buyer(conn, ci_id, agency_id)


def _seed(conn, ci_id: int, campaign) -> None:
    # ── engagement facts (from the opportunity / campaign) ──────────────────
    if campaign["brand"]:
        contribute(conn, ci_id, "engagement", "brand", campaign["brand"],
                   source="opportunity", contributed_by="system")
    band = _budget_band(campaign["budget_min"], campaign["budget_max"])
    if band:
        contribute(conn, ci_id, "engagement", "budget_band", band,
                   source="opportunity", contributed_by="system")
    if campaign["deadline"]:
        contribute(conn, ci_id, "engagement", "deadline", campaign["deadline"],
                   source="opportunity", contributed_by="system")
    _seed_agency_buyer(conn, ci_id, campaign["agency_id"])
    _seed_direction_cards(conn, ci_id, campaign)


# --------------------------------------------------------------------------- #
# Edit / create a field by (facet, key, kind) — the empty-slot path.
# --------------------------------------------------------------------------- #
def edit_or_create(conn, ci_id: int, facet: str, key: str, kind: str, value: str, *,
                   actor: str = "operator"):
    """A human types into a canonical slot: edit the existing field or create it, either way
    as an authoritative human value (ADR-0013). Returns the row."""
    row = conn.execute(
        "SELECT * FROM campaign_intelligence_field WHERE ci_id=? AND facet=? AND key=? AND kind=?",
        (ci_id, facet, key, kind)).fetchone()
    if row is not None:
        return edit_field(conn, row["id"], value, actor=actor)
    fid = contribute(conn, ci_id, facet, key, value.strip(), kind=kind, source=actor,
                     contributed_by=actor, confirmed=True)
    return db.get_ci_field(conn, fid)


# --------------------------------------------------------------------------- #
# Read view for the UI — decorated fields, canonical slots, producer read, conflicts.
# --------------------------------------------------------------------------- #
def _decorate(r) -> dict:
    import json as _json
    try:
        sources = _json.loads(r["sources"]) or []
    except (_json.JSONDecodeError, TypeError):
        sources = []
    is_gap = r["kind"] == "open_question" and r["key"].startswith("ask_")
    canon = CANONICAL_BY_KEY.get((r["facet"], r["key"], r["kind"]))
    if is_gap:
        label = r["value"]
    elif canon:
        label = canon[0]
    elif r["kind"] == "fact":
        label = r["key"].replace("_", " ").title()
    else:
        label = ""
    return {
        "id": r["id"], "facet": r["facet"], "key": r["key"], "kind": r["kind"],
        "kind_label": KIND_LABEL.get(r["kind"], r["kind"]),
        "label": label, "placeholder": (canon[1] if canon else ""),
        "value": ("" if is_gap else (r["value"] or "")),
        "sources": sources, "status": r["status"],
        "open": is_open(r["status"]), "is_concern": bool(r["is_concern"]),
        "is_gap": is_gap, "editable": (not is_gap),
        "human_value": bool(_col(r, "human_value")),
        "has_conflict": bool(_col(r, "proposed_value")),
        "proposed_value": _col(r, "proposed_value") or "",
        "proposed_source": _col(r, "proposed_source") or "",
        "dispose_verb": KIND_DISPOSE_VERB.get(r["kind"], "Confirm"),
    }


def _col(r, name):
    try:
        return r[name]
    except (KeyError, IndexError):
        return None


def brief_view(conn, ci_id: int) -> dict:
    """The Campaign Brief's read of the intelligence (ADR-0017): one flat dict of canonical
    fact values by key (human/confirmed value wins by construction — edits overwrite the
    field), plus risks, open questions, and acknowledged insights as lists. Every brief
    section prefers this over any template."""
    rows = db.list_ci_fields(conn, ci_id)
    out = {"fields": {}, "risks": [], "open_questions": [], "insights": []}
    for r in rows:
        value = (r["value"] or "").strip()
        if not value:
            continue
        if r["is_concern"] and value not in out["risks"]:
            out["risks"].append(value)
        if r["kind"] == "open_question":
            if is_open(r["status"]):
                out["open_questions"].append(value)
            continue
        if r["kind"] == "insight":
            out["insights"].append(value)
            continue
        if r["kind"] == "fact" and r["key"] not in out["fields"]:
            out["fields"][r["key"]] = value
    return out


def fields_view(conn, ci_id: int) -> dict:
    """The Campaign Intelligence view for the Opportunity page (and the workspace):
      • ``sections`` — canonical facts as labeled, always-editable slots (filled or empty),
        grouped by facet in display order, with any extra facts appended.
      • ``producer_read`` — the debrief items (insight / recommendation / open_question)
        that carry interpretation, each with its kind badge + disposition.
      • ``conflicts`` — fields where the machine proposed a value that disagrees with a human
        one (surface-and-resolve, never silent overwrite).
      • ``gaps`` — the follow-up open_questions (the ask_* fields) for the inline answer UI.
      • ``by_facet`` / ``counts`` / ``facets_present`` — kept for the workspace panel."""
    rows = db.list_ci_fields(conn, ci_id)
    items = [_decorate(r) for r in rows]
    by_id = {it["key"] + "|" + it["facet"] + "|" + it["kind"]: it for it in items}
    grouped: dict = {f: [] for f in FACETS}
    counts = {"total": 0, "open": 0}
    producer_read, conflicts, gaps, observed = [], [], [], []
    for it in items:
        grouped.setdefault(it["facet"], []).append(it)
        counts["total"] += 1
        if it["open"]:
            counts["open"] += 1
        if it["has_conflict"]:
            conflicts.append(it)
        if it["facet"] == "observed":
            # The EP's working-memory scratchpad (ADR-0021): every meaningful observation
            # the extractor caught that has no dedicated slot yet. Its own bucket.
            observed.append(it)
        elif it["is_gap"]:
            gaps.append(it)
        elif it["kind"] in ("insight", "recommendation", "open_question"):
            producer_read.append(it)

    # Canonical sections — every slot present (filled from a field, or an empty editable
    # slot) so the operator can type into any of them; extra facts appended per facet.
    sections = []
    used = set()
    for facet in CANONICAL_FACET_ORDER:
        slots = []
        for f, k, kind, label, ph, _opp in CANONICAL_FIELDS:
            if f != facet:
                continue
            key = k + "|" + f + "|" + kind
            if key in by_id:
                slots.append(by_id[key]); used.add(id(by_id[key]))
            else:
                slots.append({"id": None, "facet": f, "key": k, "kind": kind,
                              "kind_label": KIND_LABEL.get(kind, kind), "label": label,
                              "placeholder": ph, "value": "", "sources": [],
                              "status": "empty", "open": False, "is_concern": False,
                              "is_gap": False, "editable": True, "human_value": False,
                              "has_conflict": False, "proposed_value": "",
                              "proposed_source": "", "dispose_verb": "Confirm"})
        # extra facts on this facet that aren't canonical and aren't producer-read/gaps
        for it in grouped.get(facet, []):
            if it["kind"] == "fact" and CANONICAL_BY_KEY.get(
                    (it["facet"], it["key"], it["kind"])) is None:
                slots.append(it); used.add(id(it))
        sections.append({"facet": facet, "label": FACET_LABEL.get(facet, facet.title()),
                         "items": slots})

    # …and every OTHER facet that holds facts. This loop used to run over
    # CANONICAL_FACET_ORDER alone — engagement, buyer, direction — so a fact in `commercial`
    # was written, confirmed, and rendered NOWHERE. That is where the engine files payment
    # terms, cost concerns and usage rights, and it is where an answered question lands when
    # the question was filed there; the answer was being stored somewhere the operator could
    # not see it, which is nearly as useless as not storing it. `observed` keeps its own
    # bucket (the producer's scratchpad) and is not repeated here.
    for facet in FACETS:
        if facet in CANONICAL_FACET_ORDER or facet == "observed":
            continue
        extra = [it for it in grouped.get(facet, [])
                 if it["kind"] == "fact" and id(it) not in {id(x) for x in
                                                            sum((s["items"] for s in sections), [])}]
        if extra:
            sections.append({"facet": facet,
                             "label": FACET_LABEL.get(facet, facet.title()),
                             "items": extra})

    return {"sections": sections, "producer_read": producer_read,
            "conflicts": conflicts, "gaps": gaps, "observed": observed,
            "by_facet": grouped, "counts": counts,
            "facets_present": [f for f in FACETS if grouped.get(f)]}
