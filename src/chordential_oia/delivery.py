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
license grant, and Content-ID-safe status — but carries **NO indemnification
clause** (a single muted "available on request" line, never a promise).
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

# Indemnity is deliberately out of scope for Phase 0 — surfaced, never promised.
INDEMNITY_NOTE = "Indemnification available on request."

PUBLISHER = "Chordential Music"
DEFAULT_PRO = "BMI"

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
    "content_id": "Content-ID-safe",
}


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
    content_id: str                     # Content-ID-safe status
    indemnity_note: str = INDEMNITY_NOTE  # muted, NOT a promise — see scope note
    # NOTE: there is intentionally NO indemnification field/clause here.


def build_clearance_certificate(
    project, assignments, license: Optional[dict] = None
) -> ClearanceCertificate:
    """Assemble the Clearance Certificate from real project + assignment data.

    States the original-work warranty, the chain of title (contributors from the
    assignments), the license grant (merged license dict + defaults), and the
    Content-ID-safe status. Carries NO indemnification clause (founder scope:
    "documented & original, indemnity later")."""
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
        content_id=eff.get("content_id", "Content-ID-safe"),
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


def build_cue_sheet(project, assignments, deliverables=None) -> List[CueRow]:
    """The cue-sheet rows the client files for backend (PRO) royalties.

    One row for the primary cue plus a row for the cutdowns, attributing the
    assigned contributors as composer(s). Durations are placeholders ("—" / "var.")
    — no fabricated specifics — with the publisher/PRO/share filled from standard
    terms. Returns at least the primary row even with no assignments."""
    campaign = (_val(project, "need") or "Main cue").strip() or "Main cue"
    contributors = _contributors(assignments)
    composers = ", ".join(c.name for c in contributors) or "Chordential"
    rows = [
        CueRow(
            cue=campaign, usage="VV", duration="—",
            composers=composers, publisher=PUBLISHER, pro=DEFAULT_PRO, share="100%",
        ),
        CueRow(
            cue=f"{campaign} — cutdowns", usage="BI", duration="var.",
            composers=composers, publisher=PUBLISHER, pro=DEFAULT_PRO, share="100%",
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

# The folder structure of the delivery ZIP — auto-organised by asset kind/label.
DELIVERY_FOLDERS = ["Masters", "Cutdowns", "Social", "Stems", "Assets", "Docs"]


def asset_folder(asset: dict) -> str:
    """The named ZIP folder an uploaded asset belongs in, by a label/kind heuristic.

    Masters / Cutdowns / Social / Stems by keyword in the label; anything else
    (including non-audio files) lands in the catch-all ``Assets/``."""
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


def cue_sheet_csv(project, assignments) -> str:
    """The PRO cue sheet as CSV text (header + one row per cue).

    Columns: Cue, Usage, Duration, Composer, Publisher, PRO, Share%. Built from
    the same :func:`build_cue_sheet` rows the package renders — deterministic, no
    fabricated specifics."""
    rows = build_cue_sheet(project, assignments)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Cue", "Usage", "Duration", "Composer", "Publisher", "PRO", "Share%"])
    for r in rows:
        writer.writerow([r.cue, r.usage, r.duration, r.composers, r.publisher, r.pro, r.share])
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

    States the client + campaign, the chain of title (contributors), the
    original-work warranty, the license grant, the Content-ID-safe status, and the
    "documented & original" cleared line. Carries NO indemnification clause (scope:
    "documented & original, indemnity later") — only the muted available-on-request
    note. Deterministic from the certificate data."""
    lines: List[str] = []
    lines.append("CHORDENTIAL — CLEARANCE CERTIFICATE")
    lines.append("=" * 52)
    lines.append("")
    lines.append(f"Client:    {cert.client}")
    lines.append(f"Campaign:  {cert.campaign}")
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
    lines.append("GRANT OF RIGHTS / LICENSE")
    lines.append("-" * 52)
    lines.append(f"  Type:        {cert.license.get('type', '')}")
    lines.append(f"  Territory:   {cert.license.get('territory', '')}")
    lines.append(f"  Term:        {cert.license.get('term', '')}")
    lines.append(f"  Exclusivity: {cert.license.get('exclusivity', '')}")
    lines.append(f"  Content-ID:  {cert.content_id}")
    lines.append("")
    lines.append("CLEARANCE")
    lines.append("-" * 52)
    lines.append(cert.clearance_line)
    lines.append("Documented & original — Chordential holds clean chain of title.")
    lines.append("")
    lines.append(cert.indemnity_note)
    lines.append("")
    return "\n".join(lines)


def manifest_text(manifest) -> str:
    """The deliverables manifest as readable plain text, grouped by section."""
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

    cert = build_clearance_certificate(project, assignments, license)
    manifest = build_manifest(project, assets=assets, versions=versions)

    # The generated documents (stdlib-only — the guaranteed core).
    docs = {
        "Docs/cue_sheet.csv": cue_sheet_csv(project, assignments),
        "Docs/metadata.json": metadata_json(
            project, assignments, license=license, versions=versions,
            generated_at=built_at),
        "Docs/rights_certificate.txt": rights_certificate_text(cert),
        "Docs/manifest.txt": manifest_text(manifest),
    }

    slug = _campaign_slug(project)
    zip_name = f"{slug}_Delivery.zip"
    zip_path = os.path.join(upload_dir, zip_name)

    items: List[str] = []          # human labels of everything packaged
    converted: List[str] = []      # which assets also got an MP3 (best-effort)
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
        # 1) The uploaded deliverables — organised into named folders.
        for asset in assets:
            fname = os.path.basename(asset.get("filename") or "")
            if not fname:
                continue
            src = os.path.join(upload_dir, fname)
            if not os.path.isfile(src):
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

    with open(zip_path, "wb") as fh:
        fh.write(buf.getvalue())

    # The founder's payoff checklist: the deliverables + the generated docs + ZIP.
    checklist = list(items)
    checklist += ["Cue Sheet", "Metadata", "Rights Certificate", "Delivery ZIP"]

    return {
        "filename": zip_name,
        "url": f"/uploads/{zip_name}",
        "built_at": built_at,
        "checklist": checklist,
        "items": items,
        "converted": converted,
    }
