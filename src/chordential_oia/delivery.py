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

import base64
import csv
import html as _html
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

# Who is a WRITER. A cue sheet's composer column is a legal claim about authorship
# of the composition — the PRO pays on it. Everyone assigned to the project used to
# land in that column, so a mix engineer, an editor and the project manager were all
# filed as composers of the work. Only these roles author it.
WRITER_ROLES = frozenset({
    "composer", "co-composer", "arranger", "orchestrator", "topline",
    "topliner", "songwriter", "lyricist",
})

# Standard PRO cue-sheet usage codes. We only ever claim the two we can actually
# know from a campaign brief: whether the cue carries a vocal. "Visual" codes
# (VI/VV) assert that performers appear on camera, which nothing in this system
# knows — the main cue was hardcoded VV, claiming an on-screen vocal performance
# for every campaign bed we have ever delivered.
USAGE_BACKGROUND_INSTRUMENTAL = "BI"
USAGE_BACKGROUND_VOCAL = "BV"
_VOCAL_HINTS = ("vocal", "topline", "lyric", "sung", "song", "choir", "singer", "anthem vocal")

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
# The rights basis (ADR-0032, operator ruling). This used to read "Full buyout /
# work-made-for-hire" while the cue sheet filed Chordential as 100% publisher and the
# grant carried a category-exclusivity clause — three mutually exclusive positions in
# one package. Under work-made-for-hire the CLIENT is the author and owns the
# publishing, so we could not also collect a publisher share; and you cannot grant
# exclusivity on something you no longer own. The ratified structure is the standard
# one in advertising: the client buys the RECORDING outright and a perpetual sync
# licence across every campaign medium; the COMPOSITION's publishing stays here, which
# is what makes the cue sheet — and the performance royalties it collects — coherent.
DEFAULT_LICENSE = {
    "type": "Buyout of master + perpetual sync licence",
    "publishing": "Composition publishing retained by Chordential Music",
    # Media was promised in the sales copy ("all campaign media") and had nowhere to
    # live on the grant, so the certificate could not record the scope being sold.
    "media": "All campaign media — broadcast, digital, social, OOH, in-store",
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
        out.append(Contributor(role=role or "Contributor", name=name,
                               pro=(_val(a, "talent_pro") or "").strip()))
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


def deliverable_filename(campaign, label: str, ext: str) -> str:
    """A clean, self-describing name for a delivered ASSET file — ``CAMPAIGN_<Label>.<ext>``
    (e.g. ``LOOKING_Instrumental_TV_mix.mp3``, ``LOOKING_9x16_vertical_cuts.mp3``) so the
    files in the package speak to what they are instead of ``proj12-eca999d83b.mp3``.
    Deterministic; keeps the original extension. A ``9:16``-style ratio becomes ``9x16``."""
    stem = re.sub(r"(?<=\d):(?=\d)", "x", str(label or ""))        # 9:16 → 9x16
    stem = re.sub(r"[^0-9A-Za-z]+", "_", stem).strip("_")
    ext = ext if ext.startswith(".") else ("." + ext if ext else "")
    if not stem:
        return f"{slug_campaign(campaign)}_deliverable{ext}"
    return f"{slug_campaign(campaign)}_{stem}{ext}"


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
    # PRO affiliation, carried per writer. Blank is honest — the coordinator fills
    # it or asks; asserting one PRO for everybody is worse than leaving it empty.
    pro: str = ""

    @property
    def is_writer(self) -> bool:
        """Does this role author the composition? Only writers belong in a cue
        sheet's composer column — the PRO pays royalties on that claim."""
        return (self.role or "").strip().lower() in WRITER_ROLES


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
    pro: str                 # per-writer affiliation(s), in name order
    # The single "share" column conflated the two sides of a cue sheet. A PRO
    # accounts writer share and publisher share separately; one 100% told it
    # neither, or told it something impossible.
    writer_share: str = "100%"
    publisher_share: str = "100%"
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
    writers = [c for c in contributors if c.is_writer]
    # Only writers are credited. With none assigned the work is still Chordential's
    # to account for, so the house stands in — but a mixer never does.
    composers = ", ".join(c.name for c in writers) or "Chordential"
    # One PRO per writer, in the same order as the names. Distinct affiliations are
    # listed; unknown ones stay blank rather than being asserted as the house PRO.
    pro = ", ".join(c.pro or "" for c in writers).strip(", ") if writers else DEFAULT_PRO
    # Writer share is split evenly across the credited writers; the publisher share
    # is the publisher's. These were one "100%" column, which reads as either an
    # impossible 100% writer share per writer or a conflation of the two sides.
    writer_share = f"{100.0 / len(writers):.0f}%" if writers else "100%"
    usage = _infer_usage(project)
    cutdowns_cue = f"{campaign} — cutdowns"
    m_main = _cue_meta(delivery, campaign)
    m_cut = _cue_meta(delivery, cutdowns_cue)
    rows = [
        CueRow(
            cue=campaign, usage=(m_main.get("usage") or usage).strip(),
            duration=(m_main.get("duration") or "").strip(),
            composers=composers, publisher=PUBLISHER, pro=pro,
            writer_share=writer_share, publisher_share="100%",
            isrc=(m_main.get("isrc") or "").strip(),
            iswc=(m_main.get("iswc") or "").strip(),
        ),
        CueRow(
            cue=cutdowns_cue, usage=(m_cut.get("usage") or usage).strip(),
            duration=(m_cut.get("duration") or "").strip(),
            composers=composers, publisher=PUBLISHER, pro=pro,
            writer_share=writer_share, publisher_share="100%",
            isrc=(m_cut.get("isrc") or "").strip(),
            iswc=(m_cut.get("iswc") or "").strip(),
        ),
    ]
    return rows


def _infer_usage(project) -> str:
    """Background instrumental unless the brief says there is a vocal.

    The main cue was hardcoded ``VV`` — Visual Vocal — which asserts a sung
    performance visible on camera. Nothing here knows whether anyone is on screen,
    so we never claim a visual code; the operator can override per cue via
    ``delivery_json['cue_meta'][cue]['usage']``.
    """
    text = " ".join(str(_val(project, k) or "") for k in ("need", "description")).lower()
    return USAGE_BACKGROUND_VOCAL if any(h in text for h in _VOCAL_HINTS) \
        else USAGE_BACKGROUND_INSTRUMENTAL


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


def _is_primary_master(deliverable: Deliverable) -> bool:
    """True for the PRIMARY master deliverable (``Final master`` / ``Produced master``) —
    the piece the client actually reviews and approves in the version player. NOT the
    derivative masters (``Instrumental / TV mix``, ``TV track``), which are separate
    human-produced files. The review version IS this deliverable, so it counts uploaded
    the moment there's a version to play, and approved the moment the creative is locked."""
    asset = (deliverable.asset or "").lower()
    if "master" not in asset:
        return False
    return "instrumental" not in asset and "tv" not in asset


def _has_version(delivery: dict) -> bool:
    """True when the project has at least one uploaded review version (the master)."""
    return bool((delivery or {}).get("versions"))


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

    has_version = _has_version(delivery)
    uploaded: List[str] = []
    missing: List[str] = []
    for d in expected:
        # The primary master IS the review version — it counts uploaded the moment
        # there's a version to play (the client is literally streaming it), even
        # before any separate asset file is attached.
        if _deliverable_uploaded(d, asset_labels) or (has_version and _is_primary_master(d)):
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


def _match_deliverables_to_assets(expected: List, asset_labels: List[str]) -> dict:
    """Assign each uploaded asset label to AT MOST ONE scoped deliverable (injective).

    Two passes so the strongest evidence wins before a weak token overlap can steal an
    asset: (1) exact / substring matches, (2) token overlap. Each label is consumed once,
    so two deliverables can never resolve to the same asset — which is what made approving
    one deliverable approve another, and left the client's file list disagreeing with the
    sign-off list. Returns ``{deliverable_index: matched_label}``. Deterministic."""
    used: set = set()
    result: dict = {}

    def _claim(indices, predicate):
        for i in indices:
            if i in result:
                continue
            d = expected[i]
            text_lower = f"{d.group} {d.asset}".lower()
            want = _deliverable_tokens(f"{d.group} {d.asset}")
            for label in asset_labels:
                if label in used:
                    continue
                if predicate(label, label.lower(), text_lower, want):
                    result[i] = label
                    used.add(label)
                    break

    idxs = list(range(len(expected)))
    # Pass 1 — exact / substring either way (the composer's own deliverable label).
    _claim(idxs, lambda label, ll, tl, want: ll == tl or ll in tl or tl in ll)
    # Pass 2 — synonym-expanded token overlap for whatever's still unmatched.
    _claim(idxs, lambda label, ll, tl, want: bool(want & _deliverable_tokens(label)))
    return result


def scoped_deliverables(project, delivery: Optional[dict] = None) -> List[dict]:
    """The FULL scoped deliverable list paired with its matching uploaded asset.

    For making per-asset approval discoverable on the client portal: every scoped,
    upload-required deliverable (the completeness ``expected`` set) is returned as
    ``{group, asset, spec, uploaded, match}`` where ``uploaded`` is True when an
    uploaded asset plausibly satisfies it and ``match`` is that asset's label (or
    ``""``). Matching is INJECTIVE — each asset satisfies one deliverable only. The
    caller joins ``match`` back to the asset's per-asset-approval row so the portal can
    show ✓ uploaded (with Approve / Request-changes controls) vs ⧗ not uploaded yet
    ("waiting on Chordential") for the WHOLE scoped list. Deterministic."""
    delivery = delivery or {}
    std = _standard_deliverables(project)
    expected = [d for d in std if (d.group or "").strip().lower() not in _AUTO_DOC_GROUPS]
    asset_labels = [
        (a.get("label") or a.get("filename") or "").strip()
        for a in (delivery.get("assets") or [])
    ]
    asset_labels = [l for l in asset_labels if l]
    has_version = _has_version(delivery)
    matches = _match_deliverables_to_assets(expected, asset_labels)
    out: List[dict] = []
    for i, d in enumerate(expected):
        match = matches.get(i, "")
        is_master = _is_primary_master(d)
        # The primary master is satisfied by the review version itself (see
        # delivery_completeness) — approved via the main "Approve the master" button,
        # not a per-row control. Its approval status follows the creative lock, which
        # the caller layers on (is_master + no asset match → look at creative_lock).
        master_from_version = is_master and has_version and not match
        out.append({
            "group": d.group,
            "asset": d.asset,
            "spec": d.spec,
            "uploaded": bool(match) or master_from_version,
            "match": match,
            "is_master": is_master,
            "from_version": master_from_version,
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
        "Composer", "Writer Share%", "Publisher", "Publisher Share%", "PRO",
    ])
    for r in rows:
        writer.writerow([
            r.cue, r.usage, r.duration, r.isrc, r.iswc,
            r.composers, r.writer_share, r.publisher, r.publisher_share, r.pro,
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
    # Publishing and Media are stated explicitly. Leaving publishing implicit is how
    # a buyout claim and a retained publisher share coexisted unnoticed; leaving media
    # off meant the certificate could not record the scope the sale promised.
    if cert.license.get("publishing"):
        lines.append(f"  Publishing:  {cert.license.get('publishing')}")
    if cert.license.get("media"):
        lines.append(f"  Media:       {cert.license.get('media')}")
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


def manifest_html(project, manifest, *, asset_approvals: Optional[dict] = None,
                  brief_items=None, pkgid: str = "") -> str:
    """The deliverables manifest as a BRANDED, self-contained HTML document (Chordential
    wordmark + palette) — the client-facing equivalent of :func:`manifest_text`, so the
    package's documents read as Chordential documents, not raw ``.txt``. Stdlib-only."""
    if not pkgid:
        pid = _val(project, "id")
        pkgid = f"CHD-PROJ-{int(pid):04d}" if pid is not None else "CHD-PROJ"
    logo = _wordmark_data_uri("ko")
    client = _esc(_val(project, "client") or "")
    campaign = _esc(_val(project, "need") or "the campaign")

    def _mark(done):
        return ('<span style="color:#1d6b43;font-weight:800">✓</span>' if done
                else '<span style="color:#b98a5e">○</span>')

    rows, group = [], None
    for r in manifest:
        if r.group != group:
            group = r.group
            rows.append('<tr><td colspan="3" style="padding:14px 0 4px;font-weight:800;'
                        'font-size:11px;letter-spacing:.08em;text-transform:uppercase;'
                        f'color:#8a4b1d">{_esc(r.group)}</td></tr>')
        done = r.status == "Delivered"
        rows.append(
            f'<tr><td style="padding:6px 10px 6px 0">{_mark(done)} {_esc(r.asset)}</td>'
            f'<td style="padding:6px 10px;color:#7a756d;font-size:12px">{_esc(r.spec)}</td>'
            f'<td style="padding:6px 0;color:#7a756d;font-size:12px">{_esc(r.status)}</td></tr>')
    body = ('<table style="width:100%;border-collapse:collapse;font-size:13.5px">'
            f'<tbody>{"".join(rows)}</tbody></table>')

    items = list(brief_items or [])
    if items:
        roll = brief_rollup(items)
        brows = []
        for it in items:
            done = it.get("status") == "Delivered"
            matched = (it.get("matched") or "").strip()
            tail = f' <span style="color:#7a756d">→ {_esc(matched)}</span>' if matched else ""
            brows.append(
                f'<tr><td style="padding:5px 0">{_mark(done)} {_esc(it.get("item", ""))}{tail}</td>'
                f'<td style="padding:5px 0;color:#7a756d;font-size:12px">{_esc(it.get("status", ""))}</td></tr>')
        body += ('<h2 style="margin:26px 0 4px;font-size:15px">Against the brief</h2>'
                 f'<p class="legend" style="margin:0 0 8px">{_esc(roll["text"])}.</p>'
                 '<table style="width:100%;border-collapse:collapse;font-size:13.5px">'
                 f'<tbody>{"".join(brows)}</tbody></table>')

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Chordential — Deliverables Manifest · {client}</title>
<style>{_BRANDED_CSS}</style>
</head>
<body>
<section class="page">
  <div class="content">
    <div class="lh"><img class="logo" src="{logo}" alt="Chordential"><div class="lh-meta">Deliverables Manifest · {_esc(pkgid)}</div></div>
    <p class="doc-kicker">Manifest</p>
    <h1 class="doc">Deliverables Manifest</h1>
    <p class="doc-sub">Everything scoped and delivered for {client} — {campaign}.</p>
    <div class="accent-bar"></div>
    {body}
  </div>
  <div class="foot"><span>{_esc(pkgid)} · {campaign}</span><span>Prepared by Chordential</span></div>
</section>
</body>
</html>"""


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
# Branded, self-contained HTML documents (stdlib only — string templating +
# base64). The delivery ZIP carries pretty, on-brand HTML versions of the
# package + the standalone clearance certificate, matching the house style of
# web/templates/delivery_package.html (palette wine #44161E / orange #E4671F /
# cream #FCF7F8, the wordmark, the seal, the cap-audio player). Everything is
# inlined so the doc opens stand-alone when the agency unzips it: all CSS is in a
# <style> block and the Chordential wordmark is embedded as a base64 data URI.
#
# Uploaded audio that is actually bundled in the ZIP gets a playable
# <audio>-backed cap-audio player whose src is a RELATIVE path to the bundled
# file (e.g. ../Masters/xyz.wav), so it plays when opened locally; a download
# link is kept too. Referenced-only assets (no local file) are listed without a
# player.
# --------------------------------------------------------------------------- #

# The brand palette (mirrors delivery_package.html's :root vars).
_BRAND = {
    "ink": "#1F1E1E", "wine": "#44161E", "orange": "#E4671F", "cream": "#FCF7F8",
    "sand": "#D8CDB6", "slate": "#546671", "line": "#E6DFD2", "muted": "#7a756d",
}

# The shared CSS for the branded docs — the same look as the web package, inlined
# so the file is self-contained. Brace-free interpolation of the palette via %.
_BRANDED_CSS = """
  *{box-sizing:border-box}
  body{margin:0;background:#cfc9bf;color:%(ink)s;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    -webkit-font-smoothing:antialiased}
  .serif{font-family:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,"Times New Roman",serif}
  .page{position:relative;width:210mm;min-height:297mm;margin:14px auto;background:#fff;
    padding:22mm 20mm 26mm;overflow:hidden;box-shadow:0 8px 34px rgba(0,0,0,.22)}
  .content{position:relative;z-index:1}
  .lh{display:flex;align-items:center;justify-content:space-between;background:%(wine)s;
    padding:11px 16px;border-radius:8px;margin-bottom:26px}
  .lh .logo{height:19px;width:auto;display:block}
  .lh-meta{font-size:10px;color:#e7c6ba;text-transform:uppercase;letter-spacing:.14em;text-align:right}
  .doc-kicker{font-size:11px;letter-spacing:.22em;text-transform:uppercase;color:%(orange)s;font-weight:700;margin:0 0 6px}
  h1.doc{font-family:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
    font-size:30px;line-height:1.1;margin:0 0 4px;color:%(ink)s;font-weight:600}
  .doc-sub{color:%(muted)s;font-size:13px;margin:0 0 22px}
  .foot{position:absolute;left:20mm;right:20mm;bottom:12mm;display:flex;justify-content:space-between;
    border-top:1px solid %(line)s;padding-top:8px;font-size:9.5px;color:%(muted)s;
    text-transform:uppercase;letter-spacing:.1em;z-index:1}
  table{width:100%%;border-collapse:collapse;font-size:11.5px}
  th{text-align:left;font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;color:%(slate)s;
    border-bottom:2px solid %(wine)s;padding:7px 8px}
  td{padding:8px;border-bottom:1px solid %(line)s;vertical-align:top}
  tr.grp td{background:%(cream)s;font-weight:700;color:%(wine)s;text-transform:uppercase;
    letter-spacing:.08em;font-size:9.5px}
  .tick{color:%(orange)s;font-weight:800}
  .chip{display:inline-block;background:%(wine)s;color:#fff;font-size:10px;font-weight:700;
    letter-spacing:.06em;padding:5px 11px;border-radius:20px}
  .chip.ok{background:rgba(228,103,31,.14);color:#b5500f}
  .panel{background:%(cream)s;border:1px solid %(line)s;border-radius:10px;padding:16px 18px}
  .accent-bar{height:3px;background:linear-gradient(90deg,%(orange)s,%(wine)s);border-radius:3px;margin:0 0 18px}
  .two{display:grid;grid-template-columns:1fr 1fr;gap:18px}
  .seal{width:96px;height:96px;border-radius:50%%;border:3px solid %(orange)s;color:%(wine)s;
    display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;
    font-size:9px;letter-spacing:.12em;text-transform:uppercase;font-weight:700;line-height:1.5}
  .seal b{font-family:"Iowan Old Style",Palatino,Georgia,serif;font-size:15px;letter-spacing:0}
  .cover{background:radial-gradient(120%% 90%% at 20%% 0%%, #3a1219 0%%, #1f1013 60%%, #160c0e 100%%);
    color:%(cream)s;padding:0;display:flex;flex-direction:column;justify-content:space-between}
  .cover .inner{position:relative;z-index:1;padding:30mm 22mm}
  .cover .logo-cover{height:30px;width:auto;display:block}
  .cover h1{font-family:"Iowan Old Style",Palatino,Georgia,serif;font-weight:600;
    font-size:46px;line-height:1.05;margin:18px 0 6px;color:%(cream)s}
  .cover .tag{color:%(sand)s;font-size:15px;max-width:70%%}
  .cover .rule{height:2px;width:120px;background:%(orange)s;margin:26px 0}
  .cover .meta{display:grid;grid-template-columns:1fr 1fr;gap:10px 28px;max-width:80%%;font-size:12.5px}
  .cover .meta div span{display:block;color:#b89a8c;font-size:9.5px;letter-spacing:.16em;
    text-transform:uppercase;margin-bottom:2px}
  .cover .status{display:inline-block;margin-top:26px;border:1px solid %(orange)s;color:%(orange)s;
    font-size:11px;letter-spacing:.18em;text-transform:uppercase;font-weight:700;padding:8px 16px;border-radius:4px}
  ul.clean{margin:6px 0;padding-left:18px;font-size:12px;line-height:1.7}
  .legend{font-size:10.5px;color:%(muted)s}
  .wine{color:%(wine)s}
  .label{margin:22px 0 6px;font-weight:700;color:%(wine)s;font-size:12px;text-transform:uppercase;letter-spacing:.08em}
  /* compact, brand-coloured audio player */
  .cap-audio{display:inline-flex;align-items:center;gap:10px;max-width:340px;width:100%%;
    background:#fff;border:1px solid #e4ddd8;border-radius:999px;padding:4px 12px 4px 4px;margin:8px 0 4px}
  .cap-audio-btn{flex:0 0 auto;width:28px;height:28px;border-radius:50%%;border:0;
    background:%(orange)s;color:#fff;font-size:11px;line-height:1;cursor:pointer;
    display:inline-flex;align-items:center;justify-content:center}
  .cap-audio-body{flex:1 1 auto;min-width:110px}
  .cap-audio-bar{position:relative;height:5px;border-radius:999px;background:rgba(228,103,31,.18);cursor:pointer}
  .cap-audio-fill{position:absolute;left:0;top:0;bottom:0;width:0;border-radius:999px;background:%(orange)s}
  .cap-audio-time{flex:0 0 auto;font-size:11px;color:%(muted)s;font-variant-numeric:tabular-nums;min-width:30px;text-align:right}
  @media print{
    body{background:#fff}
    .page{margin:0;box-shadow:none;width:auto;min-height:auto;page-break-after:always}
  }
""" % _BRAND

# The small inline JS that drives the cap-audio players (mirrors the web template).
_CAP_AUDIO_JS = """
(function () {
  function fmt(s){ s = Math.floor(s || 0); return Math.floor(s/60) + ':' + ('0' + (s%60)).slice(-2); }
  document.querySelectorAll('.cap-audio').forEach(function (p) {
    var audio = p.querySelector('audio'), btn = p.querySelector('.cap-audio-btn'),
        fill = p.querySelector('.cap-audio-fill'), bar = p.querySelector('.cap-audio-bar'),
        time = p.querySelector('.cap-audio-time');
    if (!audio) return;
    btn.addEventListener('click', function () {
      if (audio.paused) {
        document.querySelectorAll('.cap-audio audio').forEach(function (a) { if (a !== audio) a.pause(); });
        audio.play();
      } else { audio.pause(); }
    });
    audio.addEventListener('play', function(){ btn.textContent = '\\u275A\\u275A'; });
    audio.addEventListener('pause', function(){ btn.textContent = '\\u25B6'; });
    audio.addEventListener('timeupdate', function(){
      if (audio.duration) { fill.style.width = (100*audio.currentTime/audio.duration) + '%'; }
      time.textContent = fmt(audio.currentTime);
    });
    bar.addEventListener('click', function(e){
      if (!audio.duration) return;
      var r = bar.getBoundingClientRect();
      audio.currentTime = audio.duration * (e.clientX - r.left) / r.width;
    });
  });
})();
"""


def _esc(value) -> str:
    """HTML-escape a value for safe inlining (empty string for None)."""
    return _html.escape("" if value is None else str(value), quote=True)


# Cache the embedded-wordmark data URI so we read the PNG off disk at most once.
_WORDMARK_CACHE: dict = {}


def _wordmark_data_uri(variant: str = "ko") -> str:
    """The Chordential wordmark as a base64 ``data:image/png`` URI (embedded).

    ``variant`` ∈ {``"ko"`` (knockout/light, for dark backgrounds), ``"dark"``}.
    Reads ``web/static/public/wordmark-<variant>.png`` once and caches it; returns
    ``""`` (never raises) if the asset can't be read, so the doc still renders."""
    if variant in _WORDMARK_CACHE:
        return _WORDMARK_CACHE[variant]
    uri = ""
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "web", "static", "public", f"wordmark-{variant}.png")
        with open(path, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode("ascii")
        uri = f"data:image/png;base64,{b64}"
    except Exception:
        uri = ""
    _WORDMARK_CACHE[variant] = uri
    return uri


def _audio_player_html(label: str, rel_src: str) -> str:
    """A branded cap-audio player for a bundled audio file at ``rel_src`` (relative).

    The ``<audio src>`` is the RELATIVE in-ZIP path (e.g. ``../Masters/xyz.wav``) so
    the player works when the agency unzips and opens the doc locally."""
    s = _esc(rel_src)
    return (
        '<div class="cap-audio">'
        '<button type="button" class="cap-audio-btn" aria-label="Play">▶</button>'
        '<div class="cap-audio-body"><div class="cap-audio-bar"><div class="cap-audio-fill"></div></div></div>'
        '<span class="cap-audio-time">0:00</span>'
        f'<audio preload="none" src="{s}"></audio>'
        '</div>'
    )


def _certificate_body_html(cert: "ClearanceCertificate", pkgid: str,
                           *, seal_label: str = "") -> str:
    """The inner HTML of the Clearance Certificate (warranty, contributors, grant,
    seal, honest Content-ID, signatory) — shared by the package + standalone cert.

    ``seal_label`` defaults to the certificate's own state rather than a constant
    "CLEARED": the body already titles the grant "Draft, pending confirmation" and
    prints "not yet confirmed as the deal grant", so stamping a clearance seal beside
    it made the document disagree with itself. Pass a label explicitly to override."""
    if cert.contributors:
        contrib_rows = "".join(
            f"<tr><td>{_esc(c.role)}</td><td>{_esc(c.name)}</td></tr>"
            for c in cert.contributors
        )
    else:
        contrib_rows = '<tr><td colspan="2" class="legend">No contributors assigned yet.</td></tr>'

    draft = cert.license_draft
    seal_label = seal_label or ("IN CLEARANCE" if draft else "CLEARED")
    grant_title = "Grant of rights" + (" — Draft, pending confirmation" if draft else "")
    draft_note = (
        '<p style="margin:0 0 8px;font-size:10.5px;color:#7a756d">'
        'Standard template terms — not yet confirmed as the deal grant.</p>'
        if draft else ""
    )
    confirmed = ""
    if cert.license_confirmed:
        by = _esc(cert.license_confirmed.get("by") or "")
        date = cert.license_confirmed.get("date") or ""
        date_part = f" · {_esc(date)}" if date else ""
        confirmed = (
            f'<p style="margin:8px 0 0;font-size:10.5px;color:#7a756d">'
            f'Confirmed by {by}{date_part}.</p>'
        )

    sig_extra = ""
    if cert.certified_version:
        sig_extra += f"<li><b>Certifies:</b> {_esc(cert.certified_version)}</li>"
    if cert.certified_date:
        sig_extra += f"<li><b>Date:</b> {_esc(cert.certified_date)}</li>"

    signer = _esc(cert.signatory.get("signer", ""))
    title = cert.signatory.get("title", "")
    signer_line = signer + (f", {_esc(title)}" if title else "")

    return f"""
    <div class="panel" style="margin-bottom:18px">
      <p style="margin:0;font-size:12.5px;line-height:1.6">{_esc(cert.warranty)}</p>
    </div>

    <p class="label" style="margin-top:0">Contributors &amp; chain of title</p>
    <table style="margin-bottom:18px">
      <thead><tr><th>Role</th><th>Contributor</th></tr></thead>
      <tbody>{contrib_rows}</tbody>
    </table>

    <div class="two">
      <div class="panel">
        <p class="label" style="margin-top:0">{_esc(grant_title)}</p>
        {draft_note}
        <ul class="clean">
          <li><b>Type:</b> {_esc(cert.license.get('type', ''))}</li>
          <li><b>Territory:</b> {_esc(cert.license.get('territory', ''))}</li>
          <li><b>Term:</b> {_esc(cert.license.get('term', ''))}</li>
          <li><b>Exclusivity:</b> {_esc(cert.license.get('exclusivity', ''))}</li>
          <li><b>Content-ID:</b> {_esc(cert.content_id)}</li>
        </ul>
        {confirmed}
      </div>
      <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center">
        <div class="seal"><span>Chordential</span><b>{_esc(seal_label)}</b><span>{_esc(pkgid)}</span></div>
        <p style="font-size:10.5px;color:#7a756d;margin:12px 0 0;max-width:230px">{_esc(cert.clearance_line)}</p>
      </div>
    </div>
    <p style="margin:14px 0 0;font-size:11px;color:#7a756d">{_esc(CONTENT_ID_HONEST)}</p>

    <div class="panel" style="margin-top:16px">
      <p class="label" style="margin-top:0">Signatory</p>
      <ul class="clean">
        <li><b>Entity:</b> {_esc(cert.signatory.get('entity', ''))}</li>
        <li><b>Authorized:</b> {signer_line}</li>
        {sig_extra}
      </ul>
      <p style="margin:14px 0 0;font-size:11px;color:#7a756d">Signature: ________________________________</p>
    </div>
    """


def clearance_certificate_html(
    cert: "ClearanceCertificate", *, pkgid: str = "", project=None,
) -> str:
    """The standalone branded Clearance Certificate as a self-contained HTML string.

    All CSS inline, the Chordential wordmark embedded as a base64 data URI, the
    seal, and the honest (no-indemnity) certificate body. ``pkgid`` defaults to a
    ``CHD-PROJ-NNNN`` id derived from the project when given."""
    if not pkgid:
        pid = _val(project, "id")
        pkgid = f"CHD-PROJ-{int(pid):04d}" if pid is not None else "CHD-PROJ"
    logo = _wordmark_data_uri("ko")
    body = _certificate_body_html(cert, pkgid)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Chordential — Clearance Certificate · {_esc(cert.client)}</title>
<style>{_BRANDED_CSS}</style>
</head>
<body>
<section class="page">
  <div class="content">
    <div class="lh"><img class="logo" src="{logo}" alt="Chordential"><div class="lh-meta">Clearance Certificate · {_esc(pkgid)}</div></div>
    <p class="doc-kicker">Clearance</p>
    <h1 class="doc">Clearance Certificate</h1>
    <p class="doc-sub">Original-work warranty, chain of title, and grant of rights — cleared on delivery for {_esc(cert.client)}.</p>
    <div class="accent-bar"></div>
    {body}
  </div>
  <div class="foot"><span>{_esc(pkgid)} · {_esc(cert.campaign)}</span><span>Prepared by Chordential</span></div>
</section>
</body>
</html>"""


def delivery_package_html(
    project, cert: "ClearanceCertificate", manifest, cues, assets,
    *, pkgid: str = "", state: str = "", version_state: str = "",
    released_at: str = "", brief_items=None, bundled_audio=None,
) -> str:
    """The full branded delivery package as a self-contained HTML string.

    Cover (campaign · client), the deliverables manifest, the Clearance
    Certificate, the cue-sheet table, the version/"against the brief" recap, and a
    delivered-assets block. All CSS inline + the wordmark embedded as a base64 data
    URI (stdlib only).

    ``bundled_audio`` maps an asset's identity (its ``filename`` and its ``label``)
    to the RELATIVE in-ZIP path of the bundled file (e.g. ``../Masters/xyz.wav``);
    a bundled audio asset gets a playable ``<audio>``-backed cap-audio player whose
    src is that relative path (plus a download link). Referenced-only assets (no
    bundled file) are listed without a player."""
    if not pkgid:
        pid = _val(project, "id")
        pkgid = f"CHD-PROJ-{int(pid):04d}" if pid is not None else "CHD-PROJ"
    bundled_audio = bundled_audio or {}
    logo_ko = _wordmark_data_uri("ko")

    def lh() -> str:
        return (
            f'<div class="lh"><img class="logo" src="{logo_ko}" alt="Chordential">'
            f'<div class="lh-meta">Delivery Package · {_esc(pkgid)}</div></div>'
        )

    def foot() -> str:
        return (
            f'<div class="foot"><span>{_esc(pkgid)} · {_esc(cert.campaign)}</span>'
            f'<span>Prepared by Chordential</span></div>'
        )

    # --- Cover -------------------------------------------------------------- #
    status_line = _esc(state) + (f" · {_esc(version_state)}" if version_state else "")
    released_meta = (
        f'<div><span>Released</span>{_esc(released_at)}</div>' if released_at else ""
    )
    cover = f"""
<section class="page cover">
  <div class="inner">
    <img class="logo-cover" src="{logo_ko}" alt="Chordential">
    <div class="rule"></div>
    <p class="doc-kicker" style="color:{_BRAND['orange']}">Delivery Package</p>
    <h1>{_esc(cert.campaign)}</h1>
    <p class="tag">Original music — composed, produced, and cleared for {_esc(cert.client)}.</p>
    <div class="status">{status_line}</div>
    <div class="rule" style="margin:34px 0 22px"></div>
    <div class="meta">
      <div><span>Client / Brand</span>{_esc(cert.client)}</div>
      <div><span>Campaign</span>{_esc(cert.campaign)}</div>
      <div><span>Package ID</span>{_esc(pkgid)}</div>
      <div><span>Status</span>{_esc(state)}</div>
      <div><span>Locked Version</span>{_esc(version_state)}</div>
      {released_meta}
    </div>
  </div>
  <div class="foot" style="color:#9b8276;border-color:rgba(255,255,255,.12)">
    <span>{_esc(pkgid)} · {_esc(cert.campaign)}</span><span>Prepared by Chordential</span></div>
</section>"""

    # --- Manifest ----------------------------------------------------------- #
    man_rows = []
    grp = None
    for r in manifest:
        if r.group != grp:
            man_rows.append(f'<tr class="grp"><td colspan="3">{_esc(r.group)}</td></tr>')
            grp = r.group
        status_cell = (
            '<span class="tick">✓</span> Delivered' if r.status == "Delivered"
            else _esc(r.status)
        )
        man_rows.append(
            f"<tr><td>{_esc(r.asset)}</td><td>{_esc(r.spec)}</td><td>{status_cell}</td></tr>"
        )
    n_assets = len(list(assets or []))
    manifest_page = f"""
<section class="page">
  <div class="content">
    {lh()}
    <p class="doc-kicker">Document 01</p>
    <h1 class="doc">Deliverables Manifest</h1>
    <p class="doc-sub">Everything scoped, accounted for in one place.
      <span class="chip ok" style="margin-left:8px">{n_assets} asset{'' if n_assets == 1 else 's'} uploaded</span></p>
    <table>
      <thead><tr><th>Asset</th><th>Format / Spec</th><th>Status</th></tr></thead>
      <tbody>{''.join(man_rows)}</tbody>
    </table>
    <p class="legend" style="margin-top:14px">Scoped rows are the standard asset types for this engagement; Delivered rows are the files uploaded into this package.</p>
  </div>
  {foot()}
</section>"""

    # --- Clearance certificate ---------------------------------------------- #
    cert_page = f"""
<section class="page">
  <div class="content">
    {lh()}
    <p class="doc-kicker">Document 02</p>
    <h1 class="doc">Clearance Certificate</h1>
    <p class="doc-sub">Original-work warranty, chain of title, and grant of rights — cleared on delivery.</p>
    <div class="accent-bar"></div>
    {_certificate_body_html(cert, pkgid)}
  </div>
  {foot()}
</section>"""

    # --- Cue sheet ---------------------------------------------------------- #
    cue_rows = "".join(
        f"<tr><td>{_esc(q.cue)}</td><td>{_esc(q.usage)}</td>"
        f"<td>{_esc(q.duration or '—')}</td><td>{_esc(q.isrc or '—')}</td>"
        f"<td>{_esc(q.iswc or '—')}</td><td>{_esc(q.composers)}</td>"
        f"<td>{_esc(q.writer_share)}</td><td>{_esc(q.publisher)}</td>"
        f"<td>{_esc(q.publisher_share)}</td><td>{_esc(q.pro or '—')}</td></tr>"
        for q in (cues or [])
    )
    cue_page = f"""
<section class="page">
  <div class="content">
    {lh()}
    <p class="doc-kicker">Document 03</p>
    <h1 class="doc">Cue Sheet</h1>
    <p class="doc-sub">The metadata your team files for backend (PRO) royalties — no cue sheet, no backend.</p>
    <table>
      <thead><tr><th>Cue</th><th>Usage</th><th>Dur.</th><th>ISRC</th><th>ISWC</th><th>Composer / Writer</th><th>Publisher</th><th>PRO</th><th>%</th></tr></thead>
      <tbody>{cue_rows}</tbody>
    </table>
    <p class="legend" style="margin-top:14px">Usage codes — VV Visual Vocal · BI Background Instrumental. Shares total 100% per cue. ISRC/ISWC + duration are filed per cue.</p>
  </div>
  {foot()}
</section>"""

    # --- Delivered assets (with playable audio) + against-the-brief --------- #
    asset_blocks = []
    for a in (assets or []):
        label = a.get("label") or a.get("filename") or "Asset"
        kind = a.get("kind") or "file"
        fname = (a.get("filename") or "").strip()
        rel = bundled_audio.get(fname) if fname else None
        if not rel:
            rel = bundled_audio.get(f"label:{label}")
        block = [f'<div style="margin-bottom:12px"><div style="font-size:12px;font-weight:600">{_esc(label)}</div>']
        if kind == "audio" and rel:
            block.append(_audio_player_html(label, rel))
            block.append(f'<div class="legend"><a href="{_esc(rel)}">⤓ {_esc(label)}</a></div>')
        elif rel:
            block.append(f'<div class="legend"><a href="{_esc(rel)}">⤓ {_esc(label)}</a></div>')
        else:
            url = (a.get("url") or "").strip()
            if url:
                block.append(f'<div class="legend"><a href="{_esc(url)}">⤓ {_esc(label)}</a> — referenced (not bundled)</div>')
            else:
                block.append('<div class="legend">Referenced — not bundled in this package.</div>')
        block.append("</div>")
        asset_blocks.append("".join(block))
    assets_section = ""
    if asset_blocks:
        assets_section = (
            '<p class="label">Delivered assets</p>' + "".join(asset_blocks)
        )

    brief_section = ""
    items = list(brief_items or [])
    if items:
        roll = brief_rollup(items)
        li = []
        for it in items:
            mark = "✓" if it.get("status") == "Delivered" else "—"
            matched = (it.get("matched") or "").strip()
            tail = f" → {_esc(matched)}" if matched else ""
            li.append(
                f'<li><span class="tick">{mark}</span> {_esc(it.get("item", ""))} — '
                f'{_esc(it.get("status", ""))}{tail}</li>'
            )
        brief_section = (
            '<p class="label">Against the brief</p>'
            f'<p class="legend">{_esc(roll["text"])}.</p>'
            f'<ul class="clean">{"".join(li)}</ul>'
        )

    recap_page = f"""
<section class="page">
  <div class="content">
    {lh()}
    <p class="doc-kicker">Document 04</p>
    <h1 class="doc">Assets &amp; Version State</h1>
    <p class="doc-sub">Controlled variation, a clean sign-off, and the delivered files in hand.</p>
    <div class="accent-bar"></div>
    <p class="legend">Current state: <b>{_esc(version_state or state)}</b>.</p>
    {assets_section}
    {brief_section}
    <div class="panel" style="text-align:center;padding:26px 22px;margin-top:24px;border-color:{_BRAND['orange']}">
      <div class="seal" style="margin:0 auto 14px;width:100px;height:100px">
        <span>Chordential</span><b>{'RELEASED' if state == 'Released' else 'IN PROGRESS'}</b>
        <span>{_esc('for release' if state == 'Released' else (state or 'in progress'))}</span></div>
      <p class="serif" style="font-size:20px;color:{_BRAND['wine']};margin:0 0 4px">{_esc(cert.campaign)}</p>
      <p style="color:#7a756d;font-size:12px;margin:0">{_esc(cert.client)}</p>
      {f'<p style="margin:12px 0 0;font-size:12.5px">Released <b>{_esc(released_at)}</b></p>' if released_at else ''}
    </div>
  </div>
  {foot()}
</section>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Chordential — Delivery Package · {_esc(cert.client)}</title>
<style>{_BRANDED_CSS}</style>
</head>
<body>
{cover}
{manifest_page}
{cert_page}
{cue_page}
{recap_page}
<script>{_CAP_AUDIO_JS}</script>
</body>
</html>"""


def _render_pdf_from_html(html_str: str) -> Optional[bytes]:
    """Best-effort render of ``html_str`` to PDF bytes via a headless browser.

    OPTIONAL — only runs if Playwright (+ a chromium binary) is already importable
    at runtime; wrapped in try/except so a missing browser simply returns ``None``
    (the HTML is the guaranteed deliverable). NEVER raises, NEVER a hard dependency."""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception:
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                page.set_content(html_str, wait_until="load")
                pdf = page.pdf(print_background=True, format="A4")
            finally:
                browser.close()
        return pdf or None
    except Exception:
        return None


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
    client = (_val(project, "client") or "").strip()
    lines: List[str] = []
    lines.append("CHORDENTIAL")
    lines.append(f"Your delivery — {campaign}" + (f" · {client}" if client else ""))
    lines.append("")
    lines.append("▶  START HERE")
    lines.append("   Open  Docs/Delivery-Package.html  in any web browser.")
    lines.append("   That's your complete delivery, beautifully: every track (playable),")
    lines.append("   the clearance certificate, cue sheet, rights, and credits — one clean page.")
    lines.append("")
    lines.append("WHAT'S IN THIS PACKAGE")
    lines.append("-" * 52)
    lines.append("   Masters/ · Cutdowns/ · Social/ · Stems/    your audio, sorted into folders")
    lines.append("   Docs/Delivery-Package.html                 your delivery (start here)")
    lines.append("   Docs/Clearance-Certificate.html            original-work warranty + chain of title")
    lines.append("   Docs/For-filing/                           cue sheet + metadata your coordinator files with the PROs")
    lines.append("")
    if completeness is not None and not completeness.get("complete"):
        lines.append("PLEASE NOTE — PARTIAL DELIVERY")
        lines.append("-" * 52)
        lines.append(f"   {completeness.get('text', '')}. These aren't in this ZIP yet:")
        for label in completeness.get("missing") or []:
            lines.append(f"     • {label}")
        lines.append("   We'll send them as soon as they're ready.")
        lines.append("")
    if referenced:
        lines.append("REFERENCED, NOT BUNDLED — available by link")
        lines.append("-" * 52)
        for a in referenced:
            label = (a.get("label") or a.get("filename") or "Asset").strip()
            url = (a.get("url") or "").strip()
            lines.append(f"     • {label}" + (f" — {url}" if url else ""))
        lines.append("")
    lines.append("Organised, documented, and cleared by Chordential.")
    lines.append("The music is your composer's original work.")
    lines.append("")
    return "\n".join(lines)


def build_delivery_zip(
    project, assignments, delivery: dict, upload_dir: str,
    *, generated_at: Optional[str] = None,
) -> dict:
    """Assemble the delivery ZIP and write it to ``upload_dir``; return its descriptor.

    AUTOMATION, NOT AI. Organises the uploaded deliverables into named folders
    (``Masters/`` ``Cutdowns/`` ``Social/`` ``Stems/`` ``Assets/``), writes the
    generated docs into ``Docs/`` — the primary, BRANDED, self-contained HTML
    (``Delivery-Package.html`` with playable audio + ``Clearance-Certificate.html``),
    plus the machine-fileable ``cue_sheet.csv`` / ``metadata.json`` (an agency's
    coordinator files those) and the plain-text ``rights_certificate.txt`` /
    ``manifest.txt``. Best-effort-converts each WAV to MP3 320 (skipped silently
    when ffmpeg is unavailable), best-effort-renders the package HTML to
    ``Delivery-Package.pdf`` if a headless browser is importable (skipped silently
    otherwise), and packages everything as one ``<CampaignSlug>_Delivery.zip``.

    The branded HTML is stdlib-only (string templating + base64 wordmark). Each
    bundled audio deliverable gets a playable ``<audio>``-backed player in the
    package HTML whose src is a relative in-ZIP path (e.g. ``../Masters/xyz.wav``)
    so it plays when the agency unzips and opens the doc locally.

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
    cue_rows_for_docs = build_cue_sheet(project, assignments, delivery=delivery)

    # Brief-as-contract: reconcile the brief's deliverables against the delivered
    # assets so the package records what was promised vs delivered.
    brief = seed_brief(project, delivery=delivery)
    brief_items = reconcile_brief(brief, assets)

    # Delivery-completeness gate: which scoped, upload-required deliverables have a
    # real uploaded asset behind them vs which are silently missing. Drives the
    # honest "Partial delivery — N of M" labelling on the descriptor + README.
    completeness = delivery_completeness(project, delivery)

    slug = _campaign_slug(project)
    zip_name = f"{slug}_Delivery.zip"
    zip_path = os.path.join(upload_dir, zip_name)

    items: List[str] = []          # human labels of everything packaged
    converted: List[str] = []      # which assets also got an MP3 (best-effort)
    referenced: List[dict] = []    # assets present-by-URL but not bundled (no local file)
    used_names: set = set()
    # filename → relative in-ZIP path (from Docs/) of the bundled audio file, so the
    # branded package HTML can give each bundled audio a playable <audio> player.
    bundled_audio: dict = {}

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

    # Plan the bundled-file layout up front (which assets land where) so the branded
    # HTML docs can reference each bundled audio by its relative in-ZIP path before
    # we write the bytes. Mirrors the asset-write loop's folder + uniqueness logic.
    asset_arcs: List[tuple] = []   # (asset, src, arc) for the writable assets
    for asset in assets:
        fname = os.path.basename((asset.get("filename") or "").strip())
        src = os.path.join(upload_dir, fname) if fname else ""
        if not fname or not os.path.isfile(src):
            referenced.append(asset)
            continue
        folder = asset_folder(asset)
        # Name the file for what it IS (CAMPAIGN_Label.ext), not its random upload id, so
        # the package is self-describing. Falls back to the original name when unlabeled.
        nice = (deliverable_filename(_val(project, "need"), asset.get("label") or "",
                                     os.path.splitext(fname)[1])
                if (asset.get("label") or "").strip() else fname)
        arc = _unique(f"{folder}/{nice}")
        asset_arcs.append((asset, src, arc))
        items.append(asset.get("label") or fname)
        if (asset.get("kind") or "") == "audio":
            # Docs/ live one level deep, so the relative path back out is "../<arc>".
            rel = "../" + arc
            bundled_audio[asset.get("filename") or fname] = rel
            label = asset.get("label") or asset.get("filename") or "Asset"
            bundled_audio.setdefault(f"label:{label}", rel)

    # The branded, self-contained HTML docs (stdlib only — the primary deliverable).
    package_html = delivery_package_html(
        project, cert, manifest, cues=cue_rows_for_docs, assets=assets,
        pkgid=f"CHD-PROJ-{int(_val(project, 'id') or 0):04d}",
        state=(delivery.get("state") or "").strip(),
        version_state=(delivery.get("version_state") or "").strip(),
        released_at=(delivery.get("released_at") or "").strip(),
        brief_items=brief_items, bundled_audio=bundled_audio,
    )
    cert_html = clearance_certificate_html(cert, project=project)

    # The generated documents (stdlib-only — the guaranteed core). The branded HTML
    # is the primary, pretty deliverable; the CSV + JSON stay machine-fileable.
    docs = {
        # The client's Docs/ folder is ALL branded, self-contained HTML documents — the
        # deliverable is the document, not a raw .txt (reported live: the generated docs
        # were still plain text).
        "Docs/Delivery-Package.html": package_html,
        "Docs/Clearance-Certificate.html": cert_html,
        "Docs/Deliverables-Manifest.html": manifest_html(
            project, manifest, asset_approvals=delivery.get("asset_approvals"),
            brief_items=brief_items),
        # Machine-readable / plain-text data an agency's music coordinator files with the
        # PROs — tucked into a subfolder so the client's Docs/ view shows only the clean,
        # branded HTML documents (the raw files aren't the deliverable, the HTML is).
        "Docs/For-filing/cue_sheet.csv": cue_sheet_csv(project, assignments, delivery=delivery),
        "Docs/For-filing/metadata.json": metadata_json(
            project, assignments, license=license, versions=versions,
            generated_at=built_at),
        "Docs/For-filing/rights_certificate.txt": rights_certificate_text(cert),
        "Docs/For-filing/manifest.txt": manifest_text(
            manifest, asset_approvals=delivery.get("asset_approvals"),
            brief_items=brief_items),
    }

    # Best-effort PDF of the branded package (OPTIONAL — only if a headless browser
    # is importable; never a hard dependency, never aborts the package).
    pdf_bytes = _render_pdf_from_html(package_html)
    pdf_written = False

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1) The uploaded deliverables — the actual LOCAL files, organised into
        # named (operator-assigned, else heuristic) folders. An asset with a blank
        # filename or no on-disk file (e.g. a remote-URL-only demo seed) is NOT
        # silently dropped — it's recorded for the Docs/README.txt as
        # "referenced, not bundled" so "download everything" is honest.
        for asset, src, arc in asset_arcs:
            zf.write(src, arc)
            fname = os.path.basename(arc)
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
        if pdf_bytes:
            zf.writestr("Docs/Delivery-Package.pdf", pdf_bytes)
            pdf_written = True
        # 4) The plain-text README (what's bundled + any referenced-by-URL-only assets, so
        # nothing is silently dropped) lives in For-filing/ with the other raw records — the
        # client's top-level Docs/ folder shows only the branded HTML documents.
        zf.writestr("Docs/For-filing/README.txt", _readme_text(
            project, items, referenced, built_at, completeness=completeness))

    with open(zip_path, "wb") as fh:
        fh.write(buf.getvalue())

    # The founder's payoff checklist: the deliverables + the generated docs + ZIP.
    checklist = list(items)
    checklist += ["Branded Delivery Package", "Clearance Certificate",
                  "Cue Sheet", "Metadata", "Rights Certificate", "Delivery ZIP"]

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
        # Best-effort PDF render of the branded package (absent when no headless
        # browser is available — the HTML is always the guaranteed deliverable).
        "pdf": pdf_written,
    }
