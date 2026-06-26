"""Delivery OS (Phase 0) — the deterministic delivery engine.

The supply-side counterpart to ``capabilities.py``: given a won project's real
data (client, campaign, assigned creators, uploaded assets) plus the few human
calls held in ``projects.delivery_json`` (license terms, approvals, release),
this module **assembles** the delivery documents — the Clearance Certificate,
the cue sheet, and the deliverables manifest — and reports revision status.

Like every other document layer it is **deterministic and human-in-the-loop**:
no AI, no scoring math, no fabricated specifics. Standard, clearly-templated
warranty/license/usage text (Chordential's own terms) is fine to state; the real
data — client, contributors, the actually-uploaded files — drives the rest.

Scope decision (founder-locked): **"documented & original, indemnity later."**
The Clearance Certificate states the original-work warranty, chain of title, the
license grant, and honest Content-ID language — but carries **NO indemnification
clause and NO indemnity mention at all** (founder chose indemnity-later; a
half-promise reads worse than silence, so the word is absent entirely).

IP3 (defensible rights): the certificate carries a **signatory block** (entity,
authorized signer, title) tied to the version it certifies, and the license grant
only reads as an asserted grant once the operator has **explicitly confirmed** it
(``delivery_json['license_confirmed']``); until then it reads as
"DRAFT — pending confirmation" rather than silently asserting a perpetual
worldwide exclusive buyout.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from .capabilities import _RIGHTS_SUMMARY, _deliverables_for, Deliverable

PUBLISHER = "Chordential Music"
DEFAULT_PRO = "BMI"

# IP3 — the certificate signatory block defaults (operator-editable per deal).
DEFAULT_SIGNATORY = {
    "entity": "Chordential Music",
    "signer": "Jon Shipp",
    "title": "Founder",
}

# IP3 — until the license is explicitly confirmed, the grant reads as a draft.
LICENSE_DRAFT_NOTE = "DRAFT — pending confirmation"

# Version states (Revisions agent) — the bounded v1→v2→v3 ladder.
VERSION_STATES = ["v1 Concept", "v2 Direction-lock", "v3 FINAL"]
# Delivery lifecycle states.
DELIVERY_STATES = ["In production", "In review", "Delivered", "Released"]

# Per-round human-readable label words (Revisions agent's v1→v2→v3 ladder). The
# last logged version reads as FINAL once the delivery is released/approved.
VERSION_LABELS = {1: "Concept", 2: "Direction-lock", 3: "FINAL"}

# Sensible license defaults — Chordential's own standard terms (fine to state),
# matching the rights summary in the static delivery sample. The license dict in
# delivery_json overrides any of these per-deal.
DEFAULT_LICENSE = {
    "type": "Full buyout / work-made-for-hire",
    "territory": "Worldwide",
    "term": "Perpetuity",
    "exclusivity": "Exclusive to client for the campaign category",
    # IP3 — an honest Content-ID *state* the operator can set, not a bare claim.
    # "Registrable" is the truthful default: an original work with no third-party
    # masters/samples can be registered with Content ID by the rights-holder.
    "content_id": "Registrable with Content ID",
}

# IP3 — the honest Content-ID line: original work, no third-party masters/samples,
# so there are no third-party Content-ID claims to clear, and the work is itself
# registrable with Content ID. NOT a bare "Content-ID-safe" assertion.
CONTENT_ID_HONEST = (
    "Original work — no third-party masters or samples, so no third-party "
    "Content-ID claims; the recording is registrable with Content ID by the "
    "rights-holder."
)


def _val(row, key, default=None):
    """Read a key from a sqlite3.Row / dict / object, tolerating absence."""
    if row is None:
        return default
    try:
        if hasattr(row, "keys"):
            return row[key] if key in row.keys() else default
    except Exception:
        pass
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def _contributors(assignments) -> List["Contributor"]:
    """Chain-of-title rows from the project's assignments: role → talent name.

    One entry per assigned creator (deduped on role+name); an unassigned role or a
    nameless assignment is skipped so the certificate only lists real contributors."""
    out: List[Contributor] = []
    seen = set()
    for a in assignments or []:
        role = (_val(a, "role") or "").strip()
        name = (_val(a, "talent_name") or "").strip()
        if not name:
            continue
        key = (role.lower(), name.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(Contributor(role=role or "Contributor", name=name))
    return out


def merge_license(license: Optional[dict]) -> dict:
    """The effective license terms: per-deal overrides on top of the defaults.

    A blank/missing field falls back to Chordential's standard term so the
    certificate is always complete."""
    out = dict(DEFAULT_LICENSE)
    for k, v in (license or {}).items():
        if v is not None and str(v).strip():
            out[k] = str(v).strip()
    return out


def merge_signatory(signatory: Optional[dict]) -> dict:
    """The effective certificate signatory: per-deal overrides on the defaults.

    {entity, signer, title} — a blank field falls back to the Chordential default so
    the signatory block is always complete (entity + an authorized signer)."""
    out = dict(DEFAULT_SIGNATORY)
    for k, v in (signatory or {}).items():
        if k in out and v is not None and str(v).strip():
            out[k] = str(v).strip()
    return out


def license_confirmation(delivery: Optional[dict]) -> Optional[dict]:
    """The explicit license confirmation ({by, date}) or ``None`` if unconfirmed.

    IP3: the license only reads as an asserted grant once the operator has
    confirmed the terms (the "Confirm license terms" console action). Until then
    the certificate shows the grant as a draft, never a silent buyout-by-default."""
    delivery = delivery or {}
    conf = delivery.get("license_confirmed")
    if isinstance(conf, dict) and (conf.get("by") or conf.get("date")):
        return {"by": (conf.get("by") or "").strip(), "date": (conf.get("date") or "").strip()}
    return None


# --------------------------------------------------------------------------- #
# Deterministic version naming (Metadata + Revisions agents)
#
# The founder's anti-chaos point: every file carries a deterministic, human-
# readable name — CAMPAIGN_CUE_LEN_ROLE_vN_STATE (e.g. AURORA_Anthem_60_MASTER_
# v3_FINAL) — so nobody ever reviews "the wrong version" again.
# --------------------------------------------------------------------------- #
def slug_token(value, default: str = "") -> str:
    """One naming token: uppercased, non-alphanumerics collapsed to nothing.

    ``Aurora Outdoor Co.`` → ``AURORAOUTDOORCO``; multi-word campaigns are squashed
    into a single token so the underscore only ever separates the naming *fields*."""
    text = re.sub(r"[^0-9a-zA-Z]+", "", str(value or "")).upper()
    return text or default


def slug_campaign(campaign) -> str:
    """The campaign's short naming token (first significant word, uppercased).

    Keeps the filename legible — ``Aurora Outdoor — Summer Anthem`` → ``AURORA`` —
    falling back to the whole slug when there's only one word."""
    words = re.findall(r"[0-9a-zA-Z]+", str(campaign or ""))
    if not words:
        return "CAMPAIGN"
    return words[0].upper()


def version_name(campaign, cue, length, role, n, state) -> str:
    """The deterministic delivery filename stem ``CAMPAIGN_CUE_LEN_ROLE_vN_STATE``.

    e.g. ``version_name("Aurora Outdoor", "Anthem", 60, "Master", 3, "FINAL")`` →
    ``AURORA_Anthem_60_MASTER_v3_FINAL``. Each token is slugged (alnum only); the
    cue keeps its original casing (it's the human-recognisable bit), everything
    else is uppercased. Blank fields are skipped so the stem never has ``__``."""
    cue_tok = re.sub(r"[^0-9a-zA-Z]+", "", str(cue or "")) or "Cue"
    parts = [slug_campaign(campaign), cue_tok]
    length_tok = slug_token(length)
    if length_tok:
        parts.append(length_tok)
    role_tok = slug_token(role)
    if role_tok:
        parts.append(role_tok)
    parts.append(f"v{int(n) if str(n).strip() else 1}")
    state_tok = slug_token(state)
    if state_tok:
        parts.append(state_tok)
    return "_".join(parts)


# --------------------------------------------------------------------------- #
# Version model (Revisions agent) — the real v1/v2/v3 ladder on delivery_json
# --------------------------------------------------------------------------- #
def version_label(n: int, *, final: bool = False) -> str:
    """The human label for version ``n`` (``v1 Concept`` … ``v3 FINAL``).

    ``final=True`` forces the FINAL label (used for the released/approved version
    regardless of how many rounds were logged)."""
    n = max(1, int(n or 1))
    if final:
        return f"v{n} FINAL"
    word = VERSION_LABELS.get(n, "Revision")
    return f"v{n} {word}"


def versions_list(delivery: Optional[dict]) -> List[dict]:
    """The ordered version list from ``delivery_json`` (``[]`` when none)."""
    delivery = delivery or {}
    versions = delivery.get("versions")
    return list(versions) if isinstance(versions, list) else []


def current_version(delivery: Optional[dict]) -> Optional[dict]:
    """The version under review — the latest entry in ``delivery_json['versions']``.

    Returns ``None`` when no version has been logged yet (Phase-0 projects)."""
    versions = versions_list(delivery)
    return versions[-1] if versions else None


# --------------------------------------------------------------------------- #
# Clearance Certificate (Rights agent) — the differentiator
# --------------------------------------------------------------------------- #
@dataclass
class Contributor:
    role: str
    name: str


@dataclass
class ClearanceCertificate:
    client: str
    campaign: str
    contributors: List[Contributor]
    warranty: str                       # the original-work warranty statement
    license: dict                       # effective grant of rights (merged)
    clearance_line: str                 # the "100% original & cleared" line
    content_id: str                     # honest Content-ID language (not a bare claim)
    # IP3 — defensible rights.
    signatory: dict = field(default_factory=lambda: dict(DEFAULT_SIGNATORY))
    license_confirmed: Optional[dict] = None  # {by, date} once explicitly confirmed
    certified_version: str = ""         # the version label this certificate attaches to
    certified_date: str = ""            # the date stamped at render/release
    # NOTE: there is intentionally NO indemnification field/clause/mention here.

    @property
    def license_status(self) -> str:
        """``CONFIRMED`` once the operator confirmed the terms, else ``DRAFT``."""
        return "CONFIRMED" if self.license_confirmed else "DRAFT"

    @property
    def license_draft(self) -> bool:
        """True while the grant is unconfirmed — render it as a draft, not a grant."""
        return self.license_confirmed is None


def build_clearance_certificate(
    project, assignments, license: Optional[dict] = None,
    *, signatory: Optional[dict] = None, license_confirmed: Optional[dict] = None,
    certified_version: str = "", certified_date: str = "",
) -> ClearanceCertificate:
    """Assemble the Clearance Certificate from real project + assignment data.

    States the original-work warranty, the chain of title (contributors from the
    assignments), the license grant (merged license dict + defaults), and honest
    Content-ID language. Carries NO indemnification clause and no indemnity mention
    (founder scope: "documented & original, indemnity later").

    IP3: ``signatory`` ({entity, signer, title}) drives the signatory block;
    ``license_confirmed`` ({by, date}) makes the grant read as an asserted grant
    (else it reads "DRAFT — pending confirmation"); ``certified_version`` /
    ``certified_date`` stamp the version + date the certificate attaches to."""
    client = (_val(project, "client") or "the client").strip() or "the client"
    campaign = (_val(project, "need") or "the campaign").strip() or "the campaign"
    contributors = _contributors(assignments)
    eff = merge_license(license)

    warranty = (
        f"Chordential warrants that the music delivered for {campaign} is "
        f"original work, authored by the contributors named below, and that "
        f"Chordential holds clean chain of title to grant the rights set out "
        f"in this certificate."
    )
    clearance_line = (
        "100% original & cleared — no samples, no third-party masters, "
        "no PRO surprises."
    )
    return ClearanceCertificate(
        client=client,
        campaign=campaign,
        contributors=contributors,
        warranty=warranty,
        license=eff,
        clearance_line=clearance_line,
        content_id=eff.get("content_id", "Registrable with Content ID"),
        signatory=merge_signatory(signatory),
        license_confirmed=license_confirmation({"license_confirmed": license_confirmed})
        if license_confirmed else None,
        certified_version=(certified_version or "").strip(),
        certified_date=(certified_date or "").strip(),
    )


# --------------------------------------------------------------------------- #
# Cue sheet (Metadata agent) — "no cue sheet, no backend"
# --------------------------------------------------------------------------- #
@dataclass
class CueRow:
    cue: str
    usage: str
    duration: str
    composers: str       # joined contributor names
    publisher: str
    pro: str
    share: str
    # IP3 — fileable cue identification (operator-fillable; blank allowed).
    isrc: str = ""       # International Standard Recording Code
    iswc: str = ""       # International Standard Musical Work Code


def _cue_meta(delivery: Optional[dict], cue: str) -> dict:
    """The operator-set duration/ISRC/ISWC for a cue (from ``delivery['cue_meta']``).

    Keyed by the cue name; returns ``{}`` when nothing has been filled in so the
    column stays present-but-blank (an agency's music coordinator fills it)."""
    meta = (delivery or {}).get("cue_meta")
    if isinstance(meta, dict):
        row = meta.get(cue)
        if isinstance(row, dict):
            return row
    return {}


def build_cue_sheet(project, assignments, deliverables=None,
                    delivery: Optional[dict] = None) -> List[CueRow]:
    """The cue-sheet rows the client files for backend (PRO) royalties.

    One row for the primary cue plus a row for the cutdowns, attributing the
    assigned contributors as composer(s). IP3: per-cue **Duration / ISRC / ISWC**
    are operator-fillable (``delivery_json['cue_meta']`` keyed by cue) — blank is
    allowed, but the columns are always present and structurally complete so an
    agency's music coordinator can file the sheet. Returns at least the primary row
    even with no assignments."""
    campaign = (_val(project, "need") or "Main cue").strip() or "Main cue"
    contributors = _contributors(assignments)
    composers = ", ".join(c.name for c in contributors) or "Chordential"
    cutdowns_cue = f"{campaign} — cutdowns"
    m_main = _cue_meta(delivery, campaign)
    m_cut = _cue_meta(delivery, cutdowns_cue)
    rows = [
        CueRow(
            cue=campaign, usage="VV",
            duration=(m_main.get("duration") or "").strip(),
            composers=composers, publisher=PUBLISHER, pro=DEFAULT_PRO, share="100%",
            isrc=(m_main.get("isrc") or "").strip(),
            iswc=(m_main.get("iswc") or "").strip(),
        ),
        CueRow(
            cue=cutdowns_cue, usage="BI",
            duration=(m_cut.get("duration") or "").strip(),
            composers=composers, publisher=PUBLISHER, pro=DEFAULT_PRO, share="100%",
            isrc=(m_cut.get("isrc") or "").strip(),
            iswc=(m_cut.get("iswc") or "").strip(),
        ),
    ]
    return rows


# --------------------------------------------------------------------------- #
# Deliverables manifest (Metadata + Assets agents)
# --------------------------------------------------------------------------- #
@dataclass
class ManifestRow:
    group: str
    asset: str
    spec: str
    status: str          # "Delivered" (an uploaded asset) | "Scoped" (standard type)


def _standard_deliverables(project) -> List[Deliverable]:
    """The standard deliverable *types* for the project's discipline.

    Reconstructs the linked opportunity's qualification to pick the discipline-aware
    list (``capabilities._deliverables_for``); falls back to the base campaign
    manifest when there's no linked opp / qualification to read."""
    try:
        from .web import db as _db  # local import to avoid a cycle
        from .web.evaluate import evaluate
        conn_opp_id = _val(project, "opp_id")
        if conn_opp_id is not None:
            # project may carry its own conn-less row; resolve qual lazily via a
            # fresh connection only when an opp is linked.
            conn = _db.connect()
            try:
                opp_row = _db.get_opportunity(conn, conn_opp_id)
                if opp_row is not None:
                    opp = _db.opportunity_from_row(opp_row)
                    qual, _ = evaluate(opp)
                    return _deliverables_for(qual)
            finally:
                conn.close()
    except Exception:
        pass
    # Fallback: the base campaign manifest (the standard six asset types).
    from .capabilities import _BASE_DELIVERABLES
    return list(_BASE_DELIVERABLES)


def build_manifest(
    project, deliverables=None, assets=None, versions=None
) -> List[ManifestRow]:
    """The deliverables manifest: standard asset *types* + the real uploaded assets.

    ``deliverables`` (a list of :class:`capabilities.Deliverable`) overrides the
    auto-derived standard list. ``assets`` is the project's uploaded asset list
    (from ``delivery_json['assets']``); each uploaded file appears as a Delivered
    row grouped under "Uploaded assets" carrying its **deterministic version name**
    (``CAMPAIGN_CUE_LEN_ROLE_vN_STATE``) so the manifest reads as real filenames.
    ``versions`` (``delivery_json['versions']``) are listed as their own Delivered
    rows under "Versions" — the v1/v2/v3 ladder, latest marked current."""
    campaign = (_val(project, "need") or "Campaign").strip() or "Campaign"
    std = deliverables if deliverables is not None else _standard_deliverables(project)
    rows = [
        ManifestRow(group=d.group, asset=d.asset, spec=d.spec, status="Scoped")
        for d in std
    ]
    versions = versions or []
    last = len(versions)
    for i, v in enumerate(versions, start=1):
        n = v.get("n", i)
        label = v.get("label") or version_label(n)
        # FINAL once it's the released name; the deterministic stem is the file.
        state = "FINAL" if "FINAL" in label.upper() else f"v{n}"
        name = version_name(campaign, "Master", 60, "Master", n, state)
        suffix = " · current" if i == last else ""
        rows.append(ManifestRow(
            group="Versions", asset=f"{name} — {label}{suffix}",
            spec="Audio", status="Delivered",
        ))
    for asset in assets or []:
        label = (asset.get("label") or asset.get("filename") or "Asset").strip()
        kind = asset.get("kind") or "file"
        spec = "Audio" if kind == "audio" else "File"
        # Deterministic version name for the uploaded file (campaign + asset + v1).
        name = version_name(
            campaign, label, "", "Master" if kind == "audio" else "",
            1, "MASTER" if kind == "audio" else "FILE",
        )
        rows.append(ManifestRow(
            group="Uploaded assets", asset=f"{name} — {label}",
            spec=spec, status="Delivered",
        ))
    return rows


# --------------------------------------------------------------------------- #
# Revision status (Revisions agent)
# --------------------------------------------------------------------------- #
def _scoped_rounds(estimate_or_scoped) -> int:
    """Rounds scoped — from the estimate's revision multiplier, or a plain int.

    Reads the ``Revisions`` multiplier ``setting`` ("3 rounds", "1 round", or the
    "2 rounds assumed" default) the estimator already derived; defaults to 2."""
    if estimate_or_scoped is None:
        return 2
    if isinstance(estimate_or_scoped, int):
        return estimate_or_scoped
    multipliers = getattr(estimate_or_scoped, "multipliers", None)
    if multipliers:
        for m in multipliers:
            if getattr(m, "name", "") == "Revisions":
                setting = (getattr(m, "setting", "") or "").lower()
                if "3 round" in setting or "three round" in setting:
                    return 3
                if "1 round" in setting or "one round" in setting:
                    return 1
                return 2
    return 2


def revision_status(project, estimate_or_scoped=None, delivery: Optional[dict] = None) -> dict:
    """{scoped, used, remaining, state} for the Revisions agent.

    ``scoped`` comes from the estimate's revision multiplier (or a passed int);
    ``used`` + ``state`` (version state) come from ``delivery_json``. ``remaining``
    is floored at zero so an overrun reads as 0 left, not a negative."""
    delivery = delivery or {}
    scoped = _scoped_rounds(estimate_or_scoped)
    used = int(delivery.get("revisions_used") or 0)
    remaining = max(0, scoped - used)
    state = delivery.get("version_state") or VERSION_STATES[0]
    return {"scoped": scoped, "used": used, "remaining": remaining, "state": state}


# --------------------------------------------------------------------------- #
# Creative brief (Phase 4) — the object that opens the campaign record.
#
# A small, all-optional dict on delivery_json['brief']: {objective, references,
# tone, deliverables_needed, deadline}. The brief is the start of the record (the
# founder's "creative brief seeds the package"); when none is logged yet we seed
# sensible defaults from the linked opportunity behind the project — the need →
# objective, the description → references/tone — so the console is never blank.
# --------------------------------------------------------------------------- #
BRIEF_FIELDS = ["objective", "references", "tone", "deliverables_needed", "deadline"]


def seed_brief(project, opp=None, delivery: Optional[dict] = None) -> dict:
    """The effective creative brief: the logged ``delivery_json['brief']`` if present,
    otherwise sensible defaults seeded from the project + linked opportunity.

    All five fields (``objective``, ``references``, ``tone``,
    ``deliverables_needed``, ``deadline``) are optional strings. Defaults: the
    opportunity ``need`` (or the project need) → objective; the opportunity
    ``description`` → references and tone; the project ``deadline`` → deadline.
    A stored brief always wins field-by-field over the seeded defaults."""
    delivery = delivery or {}
    need = (_val(opp, "need") or _val(project, "need") or "").strip()
    description = (_val(opp, "description") or "").strip()
    deadline = (_val(project, "deadline") or "").strip()
    seeded = {
        "objective": (
            f"Original music for {need}." if need else ""
        ),
        "references": description,
        "tone": description,
        "deliverables_needed": "",
        "deadline": deadline,
    }
    stored = delivery.get("brief") if isinstance(delivery.get("brief"), dict) else {}
    out = {}
    for f in BRIEF_FIELDS:
        v = stored.get(f)
        out[f] = (str(v).strip() if v is not None and str(v).strip() else seeded.get(f, ""))
    return out


# --------------------------------------------------------------------------- #
# Brief-as-contract (re-review top-5 #5) — parse the brief's free-text
# deliverables into items and reconcile them against the delivered assets so
# both sides see what was promised vs delivered. The brief stops being a note
# and becomes the agreed scope the buyer can point to.
#
# The matcher is deliberately simple + deterministic: a brief item is Delivered
# when ANY uploaded asset plausibly satisfies it — a case-insensitive keyword /
# substring match between the item's significant words and an asset label (e.g.
# "social cutdowns" ↔ a ":30 cutdown" / "9:16 vertical cuts"). No AI, no scoring.
# --------------------------------------------------------------------------- #

# Tiny synonym groups so a brief item phrased one way matches an asset labelled
# another — the words a brief and a filename plausibly share for the same thing.
_DELIVERABLE_SYNONYMS = [
    {"master", "anthem", "broadcast", "full", "60", ":60", "hero"},
    {"cutdown", "cutdowns", "cut", "edit", "edits", "30", ":30", "15", ":15"},
    {"social", "vertical", "9:16", "9x16", "tiktok", "reel", "reels", "story",
     "stories", "06", ":06", ":6"},
    {"stem", "stems", "multitrack", "multi-track"},
    {"instrumental", "inst", "underscore", "bed"},
    {"bumper", "sting", "stinger", "tag"},
    {"vo", "voiceover", "voice-over", "voice"},
]

# Words too generic to carry a match on their own (every brief says "the", "and").
_DELIVERABLE_STOPWORDS = {
    "a", "an", "and", "the", "of", "for", "to", "with", "plus", "or", "version",
    "versions", "deliverable", "deliverables", "asset", "assets", "file", "files",
}


def _deliverable_tokens(text: str) -> set:
    """The significant lowercase keyword tokens of a deliverable phrase.

    Splits on non-alphanumerics (keeping ``:30``-style colon tokens), drops the
    generic stopwords, and expands each token through the synonym groups so a
    brief item and an asset label that mean the same thing share tokens."""
    raw = re.findall(r"[0-9a-zA-Z:]+", str(text or "").lower())
    toks = set()
    for w in raw:
        w = w.strip(":")
        if not w or w in _DELIVERABLE_STOPWORDS:
            continue
        toks.add(w)
        for group in _DELIVERABLE_SYNONYMS:
            if w in group:
                toks |= group
    return toks


def brief_deliverables(brief: Optional[dict]) -> List[str]:
    """The brief's ``deliverables_needed`` parsed into a list of deliverable items.

    Splits the free-text on newlines / commas / semicolons, trims each, and drops
    blanks (and exact duplicates, case-insensitively) so a prose line like
    ":60 master, :30/:15 cutdowns; stems" reads as discrete, checkable items.
    Returns ``[]`` when nothing is scoped."""
    brief = brief or {}
    text = str(brief.get("deliverables_needed") or "")
    out: List[str] = []
    seen = set()
    for part in re.split(r"[\n,;]+", text):
        item = part.strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def reconcile_brief(brief: Optional[dict], assets=None) -> List[dict]:
    """Reconcile the brief's deliverables against the delivered ``assets``.

    For each item parsed from ``deliverables_needed`` (:func:`brief_deliverables`),
    matches it against the uploaded asset labels — a case-insensitive keyword /
    substring + synonym match. Returns ``[{item, status, matched}]`` where
    ``status`` ∈ {``"Delivered"``, ``"Pending"``} and ``matched`` is the satisfying
    asset's label (or ``""``). An item counts Delivered the moment ANY asset
    plausibly satisfies it. Deterministic — the first plausible asset wins."""
    items = brief_deliverables(brief)
    labels = [
        (a.get("label") or a.get("filename") or "").strip()
        for a in (assets or [])
    ]
    labels = [l for l in labels if l]
    out: List[dict] = []
    for item in items:
        item_toks = _deliverable_tokens(item)
        item_lower = item.lower()
        matched = ""
        for label in labels:
            label_lower = label.lower()
            # Plausible match: a shared significant token (synonym-expanded), or a
            # direct substring either way (handles short labels like ":30").
            if (item_toks & _deliverable_tokens(label)
                    or item_lower in label_lower or label_lower in item_lower):
                matched = label
                break
        out.append({
            "item": item,
            "status": "Delivered" if matched else "Pending",
            "matched": matched,
        })
    return out


def brief_rollup(items) -> dict:
    """The brief-vs-delivered rollup: ``{delivered, total, text}`` for a header line.

    ``text`` reads "N of M brief items delivered" (deterministic) so the portal,
    console, and package can all show the same one-line contract status."""
    items = list(items or [])
    total = len(items)
    delivered = sum(1 for i in items if i.get("status") == "Delivered")
    return {
        "delivered": delivered,
        "total": total,
        "text": f"{delivered} of {total} brief item{'s' if total != 1 else ''} delivered",
    }


# --------------------------------------------------------------------------- #
# Delivery-completeness gate — the honest "is everything actually uploaded?"
# check. "Approve & deliver" assembles a ZIP from whatever was uploaded; if the
# editor/engineer/composer never uploaded the cutdowns/stems/verticals, they're
# silently missing (README placeholders). This computes which scoped, upload-
# required deliverables have a real uploaded asset behind them vs which don't, so
# the portal/console can WARN before shipping an incomplete package as "everything".
#
# Deterministic, no AI: it reuses the same keyword/synonym matcher the manifest
# and brief-reconciliation use — a scoped deliverable counts uploaded when ANY
# uploaded asset plausibly satisfies it.
# --------------------------------------------------------------------------- #

# The standard-manifest groups that are AUTO-GENERATED by the system (cue sheet,
# rights certificate, metadata) and therefore never need a human upload. These are
# excluded from the completeness expectation — they're always produced.
_AUTO_DOC_GROUPS = {"documentation", "docs", "paperwork"}


def _deliverable_uploaded(deliverable: Deliverable, asset_labels: List[str]) -> str:
    """The label of the first uploaded asset that plausibly satisfies ``deliverable``.

    Same plausible-match rule as :func:`reconcile_brief`: a shared significant
    (synonym-expanded) token between the deliverable's group/asset text and an
    asset label, or a direct substring either way. Returns ``""`` when nothing
    uploaded matches. Deterministic — the first plausible asset wins."""
    want = _deliverable_tokens(f"{deliverable.group} {deliverable.asset}")
    text_lower = f"{deliverable.group} {deliverable.asset}".lower()
    for label in asset_labels:
        label_lower = label.lower()
        if (want & _deliverable_tokens(label)
                or label_lower in text_lower or text_lower in label_lower):
            return label
    return ""


def delivery_completeness(project, delivery: Optional[dict] = None) -> dict:
    """Is the delivery package actually complete? ``{expected, uploaded, missing,
    complete, text}``.

    ``expected`` = the scoped audio/file deliverables that REQUIRE a human upload —
    the standard manifest (masters, cutdowns, social verticals, stems) MINUS the
    auto-generated docs (cue sheet / rights certificate / metadata) the system
    always produces. A deliverable counts **uploaded** when any uploaded asset
    (``delivery_json['assets']``) plausibly matches it (the manifest's
    Delivered/Scoped keyword matcher). ``missing`` is the labels of the expected
    deliverables with no uploaded asset; ``complete = not missing``; ``text`` reads
    e.g. "5 of 8 deliverables uploaded" so the portal, console, and ZIP all show
    the same one-line gate status. Deterministic + human-in-the-loop — it only
    reports the gap; the operator/client decides whether to ship partial."""
    delivery = delivery or {}
    std = _standard_deliverables(project)
    expected = [d for d in std if (d.group or "").strip().lower() not in _AUTO_DOC_GROUPS]
    asset_labels = [
        (a.get("label") or a.get("filename") or "").strip()
        for a in (delivery.get("assets") or [])
    ]
    asset_labels = [l for l in asset_labels if l]

    uploaded: List[str] = []
    missing: List[str] = []
    for d in expected:
        if _deliverable_uploaded(d, asset_labels):
            uploaded.append(d.asset)
        else:
            missing.append(d.asset)

    total = len(expected)
    have = len(uploaded)
    return {
        "expected": [d.asset for d in expected],
        "uploaded": uploaded,
        "missing": missing,
        "complete": not missing,
        "text": f"{have} of {total} deliverable{'s' if total != 1 else ''} uploaded",
    }


def scoped_deliverables(project, delivery: Optional[dict] = None) -> List[dict]:
    """The FULL scoped deliverable list paired with its matching uploaded asset.

    For making per-asset approval discoverable on the client portal: every scoped,
    upload-required deliverable (the completeness ``expected`` set) is returned as
    ``{group, asset, spec, uploaded, match}`` where ``uploaded`` is True when an
    uploaded asset plausibly satisfies it and ``match`` is that asset's label (or
    ``""``). The caller joins ``match`` back to the asset's per-asset-approval row
    so the portal can show ✓ uploaded (with Approve / Request-changes controls) vs
    ⧗ not uploaded yet ("waiting on Chordential") for the WHOLE scoped list — not
    just the handful of assets that happen to be uploaded. Deterministic."""
    delivery = delivery or {}
    std = _standard_deliverables(project)
    expected = [d for d in std if (d.group or "").strip().lower() not in _AUTO_DOC_GROUPS]
    asset_labels = [
        (a.get("label") or a.get("filename") or "").strip()
        for a in (delivery.get("assets") or [])
    ]
    asset_labels = [l for l in asset_labels if l]
    out: List[dict] = []
    for d in expected:
        match = _deliverable_uploaded(d, asset_labels)
        out.append({
            "group": d.group,
            "asset": d.asset,
            "spec": d.spec,
            "uploaded": bool(match),
            "match": match,
        })
    return out


# --------------------------------------------------------------------------- #
# Campaign timeline (Phase 4) — the campaign's chronology, merged + sorted.
#
# Deterministic assembly from data that already exists: the brief/project start,
# each logged version upload, each review comment / change-request / approval,
# the delivery-ZIP build, and the release. One chronological tape the operator
# reads top-to-bottom: brief → v1 → notes → v2 → approval → delivered → released.
# --------------------------------------------------------------------------- #
def _ts(value) -> str:
    """A sortable ISO-ish string for an event ``when`` (empty sorts first)."""
    return str(value or "")


def build_timeline(project, delivery: Optional[dict] = None, comments=None) -> List[dict]:
    """The campaign timeline: a chronological list of ``{when, icon, label, detail}``.

    Merges + sorts (oldest first) the events already recorded across the Delivery
    OS: the campaign opening (project ``created_at``), each logged version upload
    (``versions[].created_at``), each review comment / change request / approval
    (``review_comments`` carrying kind + author + body + timecode), the delivery
    ZIP build (``delivery_zip.built_at``), and the release (``released_at``).
    Purely deterministic — no fabricated specifics, no AI."""
    delivery = delivery or {}
    events: List[dict] = []

    # 1) The campaign opened (the brief is the start of the record).
    created = _val(project, "created_at")
    campaign = (_val(project, "need") or "the campaign").strip() or "the campaign"
    events.append({
        "when": _ts(created), "icon": "✎", "label": "Creative brief",
        "detail": f"Campaign opened — {campaign}.",
    })

    # 2) Each logged version upload (the v1/v2/v3 ladder).
    for v in versions_list(delivery):
        n = v.get("n")
        label = v.get("label") or version_label(n or 1)
        name = v.get("name") or f"v{n}"
        events.append({
            "when": _ts(v.get("created_at")), "icon": "♪",
            "label": f"Version {label}",
            "detail": f"{name} uploaded.",
        })

    # 3) Review events — comments, change requests, approvals (with timecode).
    for c in comments or []:
        kind = (_val(c, "kind") or "comment")
        author = (_val(c, "author") or "Anonymous").strip() or "Anonymous"
        body = (_val(c, "body") or "").strip()
        t = _val(c, "t_seconds")
        when = _ts(_val(c, "created_at"))
        if kind == "approval":
            icon, label = "✓", f"Approved by {author}"
            detail = body or "Approved the current version."
        elif kind == "change_request":
            icon, label = "↻", f"Changes requested by {author}"
            detail = body or "Requested changes."
        else:
            icon, label = "💬", f"Comment from {author}"
            tc = ""
            if t is not None:
                try:
                    s = int(float(t))
                    tc = f"[{s // 60}:{s % 60:02d}] "
                except (TypeError, ValueError):
                    tc = ""
            detail = f"{tc}{body}".strip()
        events.append({"when": when, "icon": icon, "label": label, "detail": detail})

    # 4) The delivery ZIP assembled (the payoff moment).
    zip_desc = delivery.get("delivery_zip") if isinstance(delivery.get("delivery_zip"), dict) else None
    if zip_desc and zip_desc.get("built_at"):
        events.append({
            "when": _ts(zip_desc.get("built_at")), "icon": "📦",
            "label": "Delivery package assembled",
            "detail": "Organised, documented, converted, and zipped — ready to download.",
        })

    # 5) Released.
    released_at = delivery.get("released_at")
    if released_at:
        events.append({
            "when": _ts(released_at), "icon": "🚀",
            "label": "Released",
            "detail": "Marked released — final hand-off complete.",
        })

    # Sort oldest-first; events without a timestamp keep their insertion order
    # (stable sort) so the brief still leads even when created_at is blank.
    events.sort(key=lambda e: e["when"])
    return events


# --------------------------------------------------------------------------- #
# Standard rights basis (reused for the certificate's media line)
# --------------------------------------------------------------------------- #
def rights_basis() -> List[str]:
    """The standard grant-of-rights summary lines (from ``capabilities``)."""
    return list(_RIGHTS_SUMMARY)


# --------------------------------------------------------------------------- #
# Delivery automation (Phase 3) — document generators + the delivery ZIP.
#
# AUTOMATION, NOT AI. These functions ORGANISE, DOCUMENT, CONVERT, and PACKAGE
# the deliverables the composer already uploaded. They never synthesise audio.
# The ZIP + the generated docs are stdlib-only (zipfile/csv/json/io) — the
# GUARANTEED core. Audio format-conversion (WAV→MP3) is OPTIONAL/best-effort: it
# runs only if an ffmpeg binary is reachable via imageio_ffmpeg, and a failure
# never aborts the package (the originals are always included).
# --------------------------------------------------------------------------- #

# The folder structure of the delivery ZIP — operator-assignable, else auto-organised.
DELIVERY_FOLDERS = ["Masters", "Cutdowns", "Social", "Stems", "Docs", "Other"]
# The folders the operator may assign an asset to on the console.
ASSIGNABLE_FOLDERS = ["Masters", "Cutdowns", "Social", "Stems", "Docs", "Other"]


def asset_folder(asset: dict) -> str:
    """The named ZIP folder an uploaded asset belongs in.

    IP3: an operator-assigned ``folder`` wins (one of ``ASSIGNABLE_FOLDERS``);
    otherwise it falls back to the label/kind keyword heuristic — Masters /
    Cutdowns / Social / Stems by keyword in the label; anything else (including
    non-audio files) lands in the catch-all ``Assets/``."""
    assigned = (asset.get("folder") or "").strip()
    if assigned in ASSIGNABLE_FOLDERS:
        return assigned
    label = (asset.get("label") or asset.get("filename") or "").lower()
    if any(w in label for w in ("stem", "stems", "multitrack", "multi-track")):
        return "Stems"
    if any(w in label for w in ("social", "vertical", ":15", ":06", ":6", "9x16", "9:16", "tiktok", "reel", "story")):
        return "Social"
    if any(w in label for w in ("cutdown", "cut-down", "cut down", ":30", ":15", ":06", "edit", "instrumental", "inst", "vo", "voiceover")):
        return "Cutdowns"
    if any(w in label for w in ("master", "broadcast", ":60", "anthem", "full")):
        return "Masters"
    # Non-audio (docs, art, etc.) and anything unclassified.
    if (asset.get("kind") or "") == "audio":
        return "Masters"
    return "Assets"


def cue_sheet_csv(project, assignments, delivery: Optional[dict] = None) -> str:
    """The PRO cue sheet as CSV text (header + one row per cue).

    Columns: Cue, Usage, Duration, ISRC, ISWC, Composer, Publisher, PRO, Share%.
    IP3 adds the fileable Duration / ISRC / ISWC columns (operator-fillable, blank
    allowed) so a music coordinator can file the sheet with the PRO. Built from the
    same :func:`build_cue_sheet` rows the package renders — deterministic."""
    rows = build_cue_sheet(project, assignments, delivery=delivery)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Cue", "Usage", "Duration", "ISRC", "ISWC",
        "Composer", "Publisher", "PRO", "Share%",
    ])
    for r in rows:
        writer.writerow([
            r.cue, r.usage, r.duration, r.isrc, r.iswc,
            r.composers, r.publisher, r.pro, r.share,
        ])
    return buf.getvalue()


def metadata_json(project, assignments, license=None, versions=None,
                  generated_at: Optional[str] = None) -> str:
    """A clean metadata JSON document (campaign, client, contributors, license,
    versions, generated_at) as a pretty-printed string.

    ``generated_at`` is passed in (deterministic for tests); defaults to now."""
    cert = build_clearance_certificate(project, assignments, license)
    versions = versions or []
    doc = {
        "campaign": cert.campaign,
        "client": cert.client,
        "publisher": PUBLISHER,
        "pro": DEFAULT_PRO,
        "contributors": [{"name": c.name, "role": c.role} for c in cert.contributors],
        "license": cert.license,
        "content_id": cert.content_id,
        "versions": [
            {"n": v.get("n"), "label": v.get("label"), "name": v.get("name"),
             "file": v.get("filename")}
            for v in versions
        ],
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "generated_by": "Chordential Delivery OS — automated assembly",
    }
    return json.dumps(doc, indent=2, ensure_ascii=False)


def rights_certificate_text(cert: ClearanceCertificate) -> str:
    """The Clearance Certificate as readable plain text.

    IP3 (defensible rights): states the client + campaign, the **version it
    certifies** + date, the chain of title (contributors), the original-work
    warranty, the license grant (shown as **"DRAFT — pending confirmation"** until
    the operator explicitly confirms it, never a silent buyout-by-default), honest
    Content-ID language, the "documented & original" cleared line, and a
    **signatory block** (entity, authorized signer, title, date). Carries NO
    indemnification clause and **no indemnity mention at all** (founder scope:
    "documented & original, indemnity later"). Deterministic from the cert data."""
    lines: List[str] = []
    lines.append("CHORDENTIAL — CLEARANCE CERTIFICATE")
    lines.append("=" * 52)
    lines.append("")
    lines.append(f"Client:     {cert.client}")
    lines.append(f"Campaign:   {cert.campaign}")
    if cert.certified_version:
        lines.append(f"Certifies:  {cert.certified_version}")
    if cert.certified_date:
        lines.append(f"Date:       {cert.certified_date}")
    lines.append("")
    lines.append("CHAIN OF TITLE / CONTRIBUTORS")
    lines.append("-" * 52)
    if cert.contributors:
        for c in cert.contributors:
            lines.append(f"  • {c.name} — {c.role}")
    else:
        lines.append("  • Chordential Music")
    lines.append("")
    lines.append("ORIGINAL-WORK WARRANTY")
    lines.append("-" * 52)
    lines.append(cert.warranty)
    lines.append("")
    if cert.license_draft:
        lines.append(f"GRANT OF RIGHTS / LICENSE — {LICENSE_DRAFT_NOTE}")
    else:
        lines.append("GRANT OF RIGHTS / LICENSE")
    lines.append("-" * 52)
    if cert.license_draft:
        lines.append(
            "  Terms below are the standard template — NOT yet asserted as the "
            "deal grant. Confirm the license to certify these terms."
        )
    lines.append(f"  Type:        {cert.license.get('type', '')}")
    lines.append(f"  Territory:   {cert.license.get('territory', '')}")
    lines.append(f"  Term:        {cert.license.get('term', '')}")
    lines.append(f"  Exclusivity: {cert.license.get('exclusivity', '')}")
    lines.append(f"  Content-ID:  {cert.content_id}")
    if cert.license_confirmed:
        by = cert.license_confirmed.get("by") or ""
        date = cert.license_confirmed.get("date") or ""
        stamp = " · ".join(p for p in (by, date) if p)
        lines.append(f"  Confirmed:   {stamp}".rstrip())
    lines.append("")
    lines.append("CLEARANCE")
    lines.append("-" * 52)
    lines.append(cert.clearance_line)
    lines.append(CONTENT_ID_HONEST)
    lines.append("Documented & original — Chordential holds clean chain of title.")
    lines.append("")
    lines.append("SIGNATORY")
    lines.append("-" * 52)
    lines.append(f"  Entity:      {cert.signatory.get('entity', '')}")
    signer = cert.signatory.get("signer", "")
    title = cert.signatory.get("title", "")
    signer_line = signer + (f", {title}" if title else "")
    lines.append(f"  Authorized:  {signer_line}")
    lines.append(f"  Signature:   ________________________________")
    if cert.certified_date:
        lines.append(f"  Date:        {cert.certified_date}")
    else:
        lines.append(f"  Date:        ____________________")
    lines.append("")
    return "\n".join(lines)


def manifest_text(manifest, asset_approvals: Optional[dict] = None,
                  brief_items=None) -> str:
    """The deliverables manifest as readable plain text, grouped by section.

    ``asset_approvals`` (``delivery_json['asset_approvals']``) adds a PER-ASSET
    APPROVAL section noting which deliverables a reviewer signed off (and which
    still await), so the delivered package records the granular sign-off.

    ``brief_items`` (the :func:`reconcile_brief` list) adds a short AGAINST THE
    BRIEF section reconciling each scoped brief deliverable against what was
    delivered — the contract part, recorded in the delivered package."""
    lines: List[str] = []
    lines.append("CHORDENTIAL — DELIVERABLES MANIFEST")
    lines.append("=" * 52)
    lines.append("")
    group = None
    for r in manifest:
        if r.group != group:
            lines.append("")
            lines.append(r.group.upper())
            lines.append("-" * 52)
            group = r.group
        mark = "[✓]" if r.status == "Delivered" else "[ ]"
        lines.append(f"  {mark} {r.asset}  ({r.spec}) — {r.status}")
    recorded = {k: v for k, v in (asset_approvals or {}).items()
                if isinstance(v, dict) and v.get("status")
                and v.get("status") != "Pending"}
    if recorded:
        lines.append("")
        lines.append("PER-ASSET APPROVAL")
        lines.append("-" * 52)
        for key, rec in recorded.items():
            who = (rec.get("by") or "").strip()
            on = (rec.get("date") or "").strip()
            tail = f" — {who}" if who else ""
            tail += f" ({on})" if on else ""
            lines.append(f"  {rec['status']}: {key}{tail}")
    items = list(brief_items or [])
    if items:
        roll = brief_rollup(items)
        lines.append("")
        lines.append("AGAINST THE BRIEF")
        lines.append("-" * 52)
        lines.append(f"  {roll['text']}.")
        for it in items:
            mark = "[✓]" if it.get("status") == "Delivered" else "[ ]"
            matched = (it.get("matched") or "").strip()
            tail = f" → {matched}" if matched else ""
            lines.append(f"  {mark} {it.get('item', '')} — {it.get('status', '')}{tail}")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Best-effort WAV → MP3 conversion (OPTIONAL — never a hard dependency)
# --------------------------------------------------------------------------- #
def ffmpeg_available() -> bool:
    """True only if an ffmpeg binary is reachable via imageio_ffmpeg (no new dep)."""
    return _ffmpeg_exe() is not None


def _ffmpeg_exe() -> Optional[str]:
    try:
        import imageio_ffmpeg  # optional; only present in some environments
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        return exe if exe and os.path.exists(exe) else None
    except Exception:
        return None


def _convert_wav_to_mp3(src_path: str) -> Optional[bytes]:
    """Best-effort transcode of a WAV file to MP3 320k via ffmpeg → bytes.

    Returns ``None`` (never raises) when ffmpeg is unavailable or the conversion
    fails for any reason — the caller then packages the original untouched."""
    exe = _ffmpeg_exe()
    if not exe:
        return None
    import subprocess
    import tempfile
    out_path = None
    try:
        fd, out_path = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        subprocess.run(
            [exe, "-y", "-i", src_path, "-b:a", "320k", out_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120,
            check=True,
        )
        with open(out_path, "rb") as fh:
            data = fh.read()
        return data or None
    except Exception:
        return None
    finally:
        if out_path:
            try:
                os.remove(out_path)
            except OSError:
                pass


# --------------------------------------------------------------------------- #
# The delivery ZIP — organise + document + (optionally) convert + package
# --------------------------------------------------------------------------- #
def _campaign_slug(project) -> str:
    """A filesystem-safe campaign slug for the ZIP name (e.g. ``FindYourHorizon``)."""
    campaign = (_val(project, "need") or "Campaign").strip() or "Campaign"
    token = re.sub(r"[^0-9a-zA-Z]+", "", campaign)
    return token or "Campaign"


def _readme_text(project, bundled: List[str], referenced: List[dict],
                 built_at: str, completeness: Optional[dict] = None) -> str:
    """The Docs/README.txt — what the package bundles, and what's referenced only.

    IP3: any asset present by remote URL but with no local file to bundle (e.g. the
    demo seed) is listed here as "referenced, not bundled" with its URL, so
    "download everything" is honest about what is and isn't inside the ZIP.

    Delivery-completeness gate: when ``completeness`` reports the package is
    incomplete, the README opens with a PARTIAL DELIVERY banner naming the scoped
    deliverables that were never uploaded — so the ZIP itself is honest that it
    isn't "everything"."""
    campaign = (_val(project, "need") or "the campaign").strip() or "the campaign"
    lines: List[str] = []
    lines.append("CHORDENTIAL — DELIVERY PACKAGE README")
    lines.append("=" * 52)
    lines.append("")
    lines.append(f"Campaign: {campaign}")
    lines.append(f"Assembled: {built_at}")
    if completeness is not None:
        if completeness.get("complete"):
            lines.append(f"Completeness: {completeness.get('text', '')} — complete.")
        else:
            lines.append(f"Completeness: {completeness.get('text', '')} — PARTIAL.")
    lines.append("")
    if completeness is not None and not completeness.get("complete"):
        lines.append("PARTIAL DELIVERY — NOT EVERYTHING IS HERE")
        lines.append("-" * 52)
        lines.append(
            "These scoped deliverables were NOT uploaded and are NOT in this ZIP:")
        for label in completeness.get("missing") or []:
            lines.append(f"  • {label}")
        lines.append("")
    lines.append("BUNDLED IN THIS PACKAGE")
    lines.append("-" * 52)
    if bundled:
        for label in bundled:
            lines.append(f"  • {label}")
    else:
        lines.append("  (No local deliverable files were bundled — see below.)")
    lines.append("")
    if referenced:
        lines.append("REFERENCED, NOT BUNDLED")
        lines.append("-" * 52)
        lines.append(
            "These assets are referenced by link and are NOT inside this ZIP "
            "(no local file was available to bundle):")
        for a in referenced:
            label = (a.get("label") or a.get("filename") or "Asset").strip()
            url = (a.get("url") or "").strip()
            lines.append(f"  • {label}" + (f" — {url}" if url else ""))
        lines.append("")
    lines.append("The Docs/ folder holds the cue sheet, metadata, the clearance")
    lines.append("certificate, and the deliverables manifest.")
    lines.append("")
    return "\n".join(lines)


def build_delivery_zip(
    project, assignments, delivery: dict, upload_dir: str,
    *, generated_at: Optional[str] = None,
) -> dict:
    """Assemble the delivery ZIP and write it to ``upload_dir``; return its descriptor.

    AUTOMATION, NOT AI. Organises the uploaded deliverables into named folders
    (``Masters/`` ``Cutdowns/`` ``Social/`` ``Stems/`` ``Assets/``), writes the
    generated docs into ``Docs/`` (cue_sheet.csv, metadata.json,
    rights_certificate.txt, manifest.txt), best-effort-converts each WAV to MP3 320
    (skipped silently when ffmpeg is unavailable), and packages everything as one
    ``<CampaignSlug>_Delivery.zip``.

    Returns ``{"filename", "url", "built_at", "checklist", "items", "converted"}``.
    ``checklist`` is the founder's payoff list (the deliverable labels + the docs +
    the ZIP). The engine logic is here; the route just calls it and stores the
    descriptor on ``delivery_json``."""
    delivery = delivery or {}
    assets = list(delivery.get("assets") or [])
    versions = versions_list(delivery)
    license = delivery.get("license") or {}
    built_at = generated_at or datetime.now(timezone.utc).isoformat()

    # IP3 — the certificate stamps the version it certifies + the build date, and
    # reads the grant as a draft until the operator explicitly confirmed it.
    cur = current_version(delivery)
    certified_version = (cur.get("label") if cur else "") or ""
    cert = build_clearance_certificate(
        project, assignments, license,
        signatory=delivery.get("signatory"),
        license_confirmed=license_confirmation(delivery),
        certified_version=certified_version,
        certified_date=built_at[:10],
    )
    manifest = build_manifest(project, assets=assets, versions=versions)

    # Brief-as-contract: reconcile the brief's deliverables against the delivered
    # assets so the package records what was promised vs delivered.
    brief = seed_brief(project, delivery=delivery)
    brief_items = reconcile_brief(brief, assets)

    # Delivery-completeness gate: which scoped, upload-required deliverables have a
    # real uploaded asset behind them vs which are silently missing. Drives the
    # honest "Partial delivery — N of M" labelling on the descriptor + README.
    completeness = delivery_completeness(project, delivery)

    # The generated documents (stdlib-only — the guaranteed core).
    docs = {
        "Docs/cue_sheet.csv": cue_sheet_csv(project, assignments, delivery=delivery),
        "Docs/metadata.json": metadata_json(
            project, assignments, license=license, versions=versions,
            generated_at=built_at),
        "Docs/rights_certificate.txt": rights_certificate_text(cert),
        "Docs/manifest.txt": manifest_text(
            manifest, asset_approvals=delivery.get("asset_approvals"),
            brief_items=brief_items),
    }

    slug = _campaign_slug(project)
    zip_name = f"{slug}_Delivery.zip"
    zip_path = os.path.join(upload_dir, zip_name)

    items: List[str] = []          # human labels of everything packaged
    converted: List[str] = []      # which assets also got an MP3 (best-effort)
    referenced: List[dict] = []    # assets present-by-URL but not bundled (no local file)
    used_names: set = set()

    def _unique(arcname: str) -> str:
        # Guard against two assets landing on the same arcname inside the zip.
        if arcname not in used_names:
            used_names.add(arcname)
            return arcname
        stem, ext = os.path.splitext(arcname)
        i = 2
        while f"{stem}-{i}{ext}" in used_names:
            i += 1
        out = f"{stem}-{i}{ext}"
        used_names.add(out)
        return out

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1) The uploaded deliverables — the actual LOCAL files, organised into
        # named (operator-assigned, else heuristic) folders. An asset with a blank
        # filename or no on-disk file (e.g. a remote-URL-only demo seed) is NOT
        # silently dropped — it's recorded for the Docs/README.txt as
        # "referenced, not bundled" so "download everything" is honest.
        for asset in assets:
            fname = os.path.basename((asset.get("filename") or "").strip())
            src = os.path.join(upload_dir, fname) if fname else ""
            if not fname or not os.path.isfile(src):
                referenced.append(asset)
                continue
            folder = asset_folder(asset)
            arc = _unique(f"{folder}/{fname}")
            zf.write(src, arc)
            items.append(asset.get("label") or fname)
            # Best-effort: WAV → MP3 320 alongside under Cutdowns/ (never fails).
            if fname.lower().endswith(".wav"):
                mp3 = _convert_wav_to_mp3(src)
                if mp3:
                    mp3_arc = _unique("Cutdowns/" + os.path.splitext(fname)[0] + ".mp3")
                    zf.writestr(mp3_arc, mp3)
                    converted.append(asset.get("label") or fname)
        # 2) The logged versions (the v1/v2/v3 ladder), under Masters/.
        for v in versions:
            fname = os.path.basename(v.get("filename") or "")
            if not fname:
                continue
            src = os.path.join(upload_dir, fname)
            if not os.path.isfile(src):
                continue
            disp = (v.get("name") or os.path.splitext(fname)[0]) + os.path.splitext(fname)[1]
            arc = _unique(f"Masters/{disp}")
            zf.write(src, arc)
        # 3) The generated documents.
        for arc, content in docs.items():
            zf.writestr(arc, content)
        # 4) A Docs/README.txt — what's bundled, plus any assets that are
        # referenced-by-URL only (not local files) so nothing is silently dropped.
        zf.writestr("Docs/README.txt", _readme_text(
            project, items, referenced, built_at, completeness=completeness))

    with open(zip_path, "wb") as fh:
        fh.write(buf.getvalue())

    # The founder's payoff checklist: the deliverables + the generated docs + ZIP.
    checklist = list(items)
    checklist += ["Cue Sheet", "Metadata", "Rights Certificate", "Delivery ZIP"]

    # Honest partial labelling: when the package shipped incomplete, the descriptor
    # carries a "Partial delivery — N of M deliverables" line (not "everything")
    # plus the missing-deliverable list, so the portal card + checklist tell the
    # truth instead of presenting placeholders as a complete package.
    n_have = len(completeness.get("uploaded") or [])
    n_total = len(completeness.get("expected") or [])
    partial = not completeness.get("complete")
    descriptor_text = (
        f"Partial delivery — {n_have} of {n_total} deliverable"
        f"{'s' if n_total != 1 else ''}"
        if partial else "Complete delivery — everything uploaded"
    )

    return {
        "filename": zip_name,
        "url": f"/uploads/{zip_name}",
        "built_at": built_at,
        "checklist": checklist,
        "items": items,
        "converted": converted,
        # IP3 — assets present-by-URL only (not bundled), surfaced for honesty.
        "referenced": [
            {"label": (a.get("label") or a.get("filename") or "Asset").strip(),
             "url": (a.get("url") or "").strip()}
            for a in referenced
        ],
        # Delivery-completeness gate — honest partial labelling for the portal/ZIP.
        "partial": partial,
        "completeness": {
            "expected": list(completeness.get("expected") or []),
            "uploaded": list(completeness.get("uploaded") or []),
            "missing": list(completeness.get("missing") or []),
            "complete": bool(completeness.get("complete")),
            "text": completeness.get("text", ""),
        },
        "descriptor": descriptor_text,
    }
