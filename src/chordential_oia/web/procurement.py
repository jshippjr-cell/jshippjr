"""Procurement Intelligence (ADR-0022) — ChordOS as an intelligent procurement coordinator.

The governing principle: **ChordOS does NOT integrate with procurement systems. It prepares
clients for procurement.** Never build for Ariba/Coupa/Oracle/SAP/Jaggaer — build around
Procurement Intelligence: discover requirements from conversation, adapt a checklist to what
this client actually needs, generate the artifacts ChordOS honestly can, guide onboarding,
and learn from every completed engagement so the next one starts further ahead.

Three layers:
  1. **Discovery** — procurement requirements are DISCOVERED from CI (the EP extractor already
     captures ``procurement_requirements``) and normalized against a known vocabulary. Never
     hardcoded per client: two clients get two different checklists because they said two
     different things.
  2. **Generation** — for requirements ChordOS can legally produce (W-9, ACH authorization,
     remittance/banking sheets, vendor profile, company overview, cover letter, contact
     sheet), a deterministic document is built from the ONE Company Profile. For requirements
     it can't (COI needs the insurer; MSA/NDA need legal), it generates a professional
     placeholder requesting the missing information.
  3. **Learning** — on completion the requirement set is snapshotted to a client-scoped
     history; a future campaign for the same client pre-loads it (Relationship Intelligence).

The requirement lifecycle (``STATUSES``): needed → requested → generated → uploaded →
complete (plus ``na`` for waived). Owner ∈ chordential | client | shared.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Optional

from . import db

STATUSES = ["needed", "requested", "generated", "uploaded", "complete", "na"]
STATUS_LABEL = {"needed": "Needed", "requested": "Requested by client",
                "generated": "Generated — ready to send", "uploaded": "Uploaded",
                "complete": "Complete", "na": "Not required"}
OWNERS = ["chordential", "client", "shared"]


# --------------------------------------------------------------------------- #
# The requirement VOCABULARY — the known types ChordOS can recognize + normalize.
# This is NOT a per-client checklist (those are discovered); it is how a discovered
# phrase ("we'll need your W-9") maps to a canonical requirement + whether ChordOS can
# generate the artifact. Every entry: key → {label, owner, generator, category, cues}.
#   generator: the doc ChordOS produces (None = needs external input → placeholder).
# --------------------------------------------------------------------------- #
VOCAB = {
    "w9":                {"label": "W-9", "owner": "chordential", "generator": "w9",
                          "category": "Tax", "cues": ["w-9", "w9", "w 9", "tax form", "taxpayer id form"]},
    "ach":               {"label": "ACH authorization", "owner": "chordential", "generator": "ach",
                          "category": "Banking", "cues": ["ach", "direct deposit", "ach form", "ach authorization"]},
    "remittance":        {"label": "Remittance information", "owner": "chordential", "generator": "remittance",
                          "category": "Banking", "cues": ["remittance", "where to send payment"]},
    "banking_letter":    {"label": "Banking verification letter", "owner": "chordential", "generator": "banking",
                          "category": "Banking", "cues": ["banking letter", "bank letter", "banking verification", "voided check", "banking verification"]},
    "coi":               {"label": "Certificate of Insurance (COI)", "owner": "shared", "generator": None,
                          "category": "Insurance", "cues": ["coi", "certificate of insurance", "insurance certificate", "proof of insurance"]},
    "vendor_registration": {"label": "Vendor registration", "owner": "chordential", "generator": "vendor_profile",
                          "category": "Onboarding", "cues": ["vendor registration", "register as a vendor", "vendor onboarding", "supplier registration", "new vendor"]},
    "vendor_portal":     {"label": "Vendor portal registration", "owner": "chordential", "generator": None,
                          "category": "Onboarding", "cues": ["portal", "vendor portal", "supplier portal", "procurement portal", "coupa", "ariba", "jaggaer"]},
    "vendor_code":       {"label": "Vendor code", "owner": "client", "generator": None,
                          "category": "Onboarding", "cues": ["vendor code", "vendor number", "supplier code", "vendor id"]},
    "vendor_info_form":  {"label": "Vendor information form", "owner": "chordential", "generator": "vendor_info",
                          "category": "Onboarding", "cues": ["vendor information form", "vendor info form", "vendor form", "new vendor form", "vendor setup form"]},
    "nda":               {"label": "NDA", "owner": "shared", "generator": None,
                          "category": "Legal", "cues": ["nda", "non-disclosure", "nondisclosure", "confidentiality agreement"]},
    "msa":               {"label": "Master Services Agreement (MSA)", "owner": "shared", "generator": None,
                          "category": "Legal", "cues": ["msa", "master services agreement", "master service agreement"]},
    "po":                {"label": "Purchase Order before work", "owner": "client", "generator": None,
                          "category": "Payment", "cues": ["purchase order", " po ", "po before", "po first", "issue the po", "issue a po", "no work without a po"]},
    "net_30":            {"label": "Net 30 payment terms", "owner": "shared", "generator": None,
                          "category": "Payment", "cues": ["net 30", "net-30", "net thirty"]},
    "net_60":            {"label": "Net 60 payment terms", "owner": "shared", "generator": None,
                          "category": "Payment", "cues": ["net 60", "net-60", "net sixty"]},
    "diversity":         {"label": "Diversity / supplier-diversity forms", "owner": "chordential", "generator": None,
                          "category": "Compliance", "cues": ["diversity", "supplier diversity", "minority", "mbe", "wbe", "dbe"]},
    "banking_verification": {"label": "Banking verification", "owner": "chordential", "generator": "banking",
                          "category": "Banking", "cues": ["banking verification", "verify banking", "bank verification"]},
    "security_questionnaire": {"label": "Security / cyber questionnaire", "owner": "chordential", "generator": None,
                          "category": "Compliance", "cues": ["security questionnaire", "cyber", "infosec", "security assessment", "vendor security"]},
    "tax_documents":     {"label": "Tax documents", "owner": "chordential", "generator": "w9",
                          "category": "Tax", "cues": ["tax documents", "tax docs", "tax paperwork"]},
    "compliance_review": {"label": "Compliance review", "owner": "client", "generator": None,
                          "category": "Compliance", "cues": ["compliance review", "compliance check", "vendor compliance"]},
    "procurement_contact": {"label": "Procurement contact", "owner": "client", "generator": None,
                          "category": "Contacts", "cues": ["procurement contact", "procurement team", "procurement department"]},
    "ap_contact":        {"label": "AP contact", "owner": "client", "generator": None,
                          "category": "Contacts", "cues": ["ap contact", "accounts payable", "a/p contact"]},
    "legal_contact":     {"label": "Legal contact", "owner": "client", "generator": None,
                          "category": "Contacts", "cues": ["legal contact", "legal team", "legal department"]},
    "company_overview":  {"label": "Company overview", "owner": "chordential", "generator": "company_overview",
                          "category": "Onboarding", "cues": ["company overview", "capabilities statement", "company profile", "about your company"]},
}
# Documents ChordOS can offer to generate proactively even if not explicitly demanded, as a
# convenience packet (the operator opts in). Kept separate from discovery.
STANDALONE_GENERATORS = ["w9", "ach", "remittance", "banking", "vendor_profile",
                         "company_overview", "cover_letter", "vendor_info", "contact_sheet"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(text: str) -> str:
    return " " + re.sub(r"\s+", " ", (text or "").lower()) + " "


def detect_requirements(text: str) -> list:
    """Scan free text (a CI fact value, an evidence line, an RFP clause) and return the
    canonical requirement keys it mentions — discovered, never assigned. Returns [(key, cue)]."""
    hay = _norm(text)
    hits = []
    for key, spec in VOCAB.items():
        for cue in spec["cues"]:
            if cue.strip() and cue in hay:
                hits.append((key, cue.strip()))
                break
    return hits


# --------------------------------------------------------------------------- #
# Discovery — materialize requirements from Campaign Intelligence + captures.
# --------------------------------------------------------------------------- #
def discover_from_ci(conn, opp_id: int, ci_id: Optional[int] = None) -> int:
    """Read this opportunity's Campaign Intelligence (the ``procurement_requirements`` fact,
    plus any procurement signal in engagement/commercial/observed facts and raw captures) and
    materialize discovered requirements. Idempotent: re-running updates evidence/confidence,
    never duplicates. Returns the count of requirements now present. Never hardcodes — a client
    who mentioned nothing gets an empty checklist."""
    from . import campaign_intelligence as ci
    if ci_id is None:
        row = db.get_opportunity(conn, opp_id)
        if row is None:
            return 0
        ci_id = ci.ensure_for_opportunity(conn, row)["id"]
    scanned = []  # (text, source, confidence)
    for f in db.list_ci_fields(conn, ci_id):
        key = (f["key"] or "")
        val = (f["value"] or "").strip()
        if not val:
            continue
        if "procure" in key or key in ("procurement_requirements",) or f["facet"] in ("commercial", "observed"):
            scanned.append((val, "Campaign Intelligence", f["confidence"] or 80))
        else:
            # a passing procurement mention inside any other fact still counts
            if detect_requirements(val):
                scanned.append((val, "Campaign Intelligence", f["confidence"] or 70))
    # raw captures (the transcript/RFP text) — the richest evidence source
    for cap in db.list_captures_for_opp(conn, opp_id) if hasattr(db, "list_captures_for_opp") else []:
        raw = (cap["raw_text"] or "").strip()
        if raw and detect_requirements(raw):
            scanned.append((raw, _source_label(cap["lane"]), 90))
    seen = set()
    for text, source, conf in scanned:
        for key, cue in detect_requirements(text):
            if key in seen:
                continue
            seen.add(key)
            evidence = _evidence_sentence(text, cue)
            upsert_requirement(conn, opp_id, key, source=source, evidence=evidence,
                               confidence=conf, discovered=True)
    return len(db.list_procurement_requirements(conn, opp_id))


def _source_label(lane: str) -> str:
    return {"discovery_call": "Discovery Call", "rfp": "RFP", "email": "Email",
            "notes": "Notes", "debrief": "Producer Debrief"}.get(lane or "", "Conversation")


def _evidence_sentence(text: str, cue: str) -> str:
    """Pull the sentence containing the cue — the client's own words as the citation."""
    for sent in re.split(r"(?<=[.!?])\s+", text):
        if cue in sent.lower():
            return sent.strip()[:280]
    return text.strip()[:280]


def upsert_requirement(conn, opp_id: int, key: str, *, source: str = "", evidence: str = "",
                       confidence=None, owner: str = "", status: str = "needed",
                       discovered: bool = False) -> int:
    """Create or refresh a requirement for this opportunity. Discovery refreshes evidence but
    never downgrades a status the operator has already advanced."""
    spec = VOCAB.get(key, {"label": key.replace("_", " ").title(),
                           "owner": "chordential", "generator": None, "category": "Other"})
    existing = db.get_procurement_requirement(conn, opp_id, key)
    if existing is not None:
        if discovered:
            db.update_procurement_requirement(
                conn, existing["id"],
                evidence=evidence or existing["evidence"],
                confidence=confidence if confidence is not None else existing["confidence"],
                source=source or existing["source"])
        return existing["id"]
    rid = db.add_procurement_requirement(
        conn, opp_id=opp_id, req_key=key, label=spec["label"],
        owner=owner or spec["owner"], category=spec.get("category", "Other"),
        status=status, source=source, evidence=evidence, confidence=confidence,
        generatable=1 if spec.get("generator") else 0)
    add_event(conn, opp_id, "discovered" if discovered else "added",
              f"{spec['label']} — {STATUS_LABEL.get(status, status)}")
    return rid


# --------------------------------------------------------------------------- #
# Readiness + the adaptive checklist view.
# --------------------------------------------------------------------------- #
def readiness(conn, opp_id: int) -> dict:
    reqs = db.list_procurement_requirements(conn, opp_id)
    active = [r for r in reqs if r["status"] != "na"]
    done = [r for r in active if r["status"] == "complete"]
    pct = round(100 * len(done) / len(active)) if active else 100
    portal = next((r for r in reqs if r["req_key"] in ("vendor_portal",) and r["status"] != "na"), None)
    return {
        "total": len(active), "complete": len(done), "pct": pct,
        "outstanding": [r for r in active if r["status"] not in ("complete",)],
        "awaiting_client": [r for r in active if r["owner"] == "client" and r["status"] != "complete"],
        "awaiting_chordential": [r for r in active if r["owner"] == "chordential" and r["status"] not in ("complete", "uploaded")],
        "ready_for_onboarding": bool(active) and all(r["status"] in ("complete", "uploaded", "generated") for r in active),
        "has_portal": portal is not None,
        "all_done": bool(active) and len(done) == len(active),
    }


def checklist(conn, opp_id: int) -> list:
    """The adaptive checklist — assembled from the requirements that actually exist, grouped
    by category, each row carrying the actions it supports. No two clients need be alike."""
    reqs = db.list_procurement_requirements(conn, opp_id)
    groups: dict = {}
    for r in reqs:
        spec = VOCAB.get(r["req_key"], {})
        item = dict(r)
        item["status_label"] = STATUS_LABEL.get(r["status"], r["status"])
        item["can_generate"] = bool(r["generatable"]) and not (r["artifact_ref"] or "")
        item["can_regenerate"] = bool(r["generatable"]) and bool(r["artifact_ref"])
        groups.setdefault(spec.get("category", "Other"), []).append(item)
    return [{"category": cat, "items": items} for cat, items in sorted(groups.items())]


# --------------------------------------------------------------------------- #
# The Document Generation Engine — deterministic artifacts from the ONE Company Profile.
# --------------------------------------------------------------------------- #
def company_profile(conn) -> dict:
    return db.get_company_profile(conn)


def _missing(profile: dict, fields: list) -> list:
    return [f for f in fields if not (profile.get(f) or "").strip()]


def generate_document(conn, opp_id: int, req_key: str) -> dict:
    """Generate the artifact for a requirement from the Company Profile. Returns
    {ok, text, missing, placeholder}. When ChordOS can't legally auto-produce the document
    (COI, MSA, NDA, security questionnaire), returns a professional placeholder requesting the
    remaining information from the operator — never a fake official form."""
    profile = company_profile(conn)
    spec = VOCAB.get(req_key, {})
    gen = spec.get("generator")
    label = spec.get("label", req_key)
    if not gen:
        text = _placeholder(label, profile, req_key)
        _store_artifact(conn, opp_id, req_key, text, status_to="requested")
        return {"ok": True, "placeholder": True, "text": text, "missing": []}
    builder = _GENERATORS.get(gen)
    if builder is None:
        text = _placeholder(label, profile, req_key)
        _store_artifact(conn, opp_id, req_key, text, status_to="requested")
        return {"ok": True, "placeholder": True, "text": text, "missing": []}
    text, missing = builder(profile)
    _store_artifact(conn, opp_id, req_key, text, status_to="generated")
    return {"ok": True, "placeholder": False, "text": text, "missing": missing}


def _store_artifact(conn, opp_id, req_key, text, *, status_to):
    ref = f"procurement/{opp_id}/{req_key}.txt"
    db.save_procurement_artifact(conn, opp_id, req_key, text, artifact_ref=ref)
    r = db.get_procurement_requirement(conn, opp_id, req_key)
    if r is not None and r["status"] in ("needed", "requested"):
        db.update_procurement_requirement(conn, r["id"], status=status_to, artifact_ref=ref)
    add_event(conn, opp_id, "generated", f"Generated {VOCAB.get(req_key, {}).get('label', req_key)}")


def _hdr(profile) -> str:
    name = profile.get("legal_name") or "Chordential"
    dba = f" (DBA {profile['dba']})" if (profile.get("dba") or "").strip() else ""
    return f"{name}{dba}"


def _gen_w9(profile) -> tuple:
    miss = _missing(profile, ["legal_name", "ein", "business_address"])
    text = (f"FORM W-9 — Request for Taxpayer Identification Number\n"
            f"(Substitute — for vendor onboarding; sign the official IRS Form W-9 for filing)\n\n"
            f"Legal name: {profile.get('legal_name') or '[LEGAL COMPANY NAME]'}\n"
            f"Business name / DBA: {profile.get('dba') or '—'}\n"
            f"Federal tax classification: {profile.get('tax_class') or 'S-Corporation'}\n"
            f"Address: {profile.get('business_address') or '[BUSINESS ADDRESS]'}\n"
            f"EIN: {profile.get('ein') or '[EIN]'}\n\n"
            f"Under penalties of perjury, the TIN above is correct and this entity is a U.S. person.\n"
            f"Signature: __________________________   Date: __________\n")
    return text, miss


def _gen_ach(profile) -> tuple:
    miss = _missing(profile, ["legal_name", "bank_name", "routing", "account"])
    text = (f"ACH / DIRECT-DEPOSIT AUTHORIZATION — {_hdr(profile)}\n\n"
            f"Please remit payment via ACH to:\n"
            f"  Beneficiary: {profile.get('legal_name') or '[LEGAL NAME]'}\n"
            f"  Bank: {profile.get('bank_name') or '[BANK NAME]'}\n"
            f"  Routing (ABA): {profile.get('routing') or '[ROUTING]'}\n"
            f"  Account: {profile.get('account') or '[ACCOUNT]'}\n"
            f"  Account type: {profile.get('account_type') or 'Checking'}\n"
            f"  Remittance advice to: {profile.get('finance_contact') or profile.get('primary_contact') or '[FINANCE CONTACT]'}\n\n"
            f"Authorized by: __________________________   Date: __________\n")
    return text, miss


def _gen_remittance(profile) -> tuple:
    miss = _missing(profile, ["legal_name", "remittance_address"])
    text = (f"REMITTANCE INFORMATION — {_hdr(profile)}\n\n"
            f"Make payments payable to: {profile.get('legal_name') or '[LEGAL NAME]'}\n"
            f"Remittance address: {profile.get('remittance_address') or profile.get('mailing_address') or '[REMITTANCE ADDRESS]'}\n"
            f"EIN: {profile.get('ein') or '[EIN]'}\n"
            f"Preferred method: {profile.get('preferred_payment') or 'ACH (see ACH authorization)'}\n"
            f"AP questions to: {profile.get('finance_contact') or '[FINANCE CONTACT]'}\n")
    return text, miss


def _gen_banking(profile) -> tuple:
    miss = _missing(profile, ["legal_name", "bank_name", "routing", "account"])
    text = (f"BANKING VERIFICATION — {_hdr(profile)}\n\n"
            f"This confirms the banking details for {profile.get('legal_name') or '[LEGAL NAME]'}:\n"
            f"  Bank: {profile.get('bank_name') or '[BANK NAME]'}\n"
            f"  Routing (ABA): {profile.get('routing') or '[ROUTING]'}\n"
            f"  Account: {profile.get('account') or '[ACCOUNT]'}\n\n"
            f"For a bank-issued verification letter or voided check, contact "
            f"{profile.get('finance_contact') or '[FINANCE CONTACT]'}.\n")
    return text, miss


def _gen_vendor_profile(profile) -> tuple:
    miss = _missing(profile, ["legal_name", "ein", "business_address"])
    text = (f"VENDOR PROFILE — {_hdr(profile)}\n\n"
            f"Legal name: {profile.get('legal_name') or '[LEGAL NAME]'}\n"
            f"DBA: {profile.get('dba') or '—'}\n"
            f"EIN: {profile.get('ein') or '[EIN]'}\n"
            f"Address: {profile.get('business_address') or '[ADDRESS]'}\n"
            f"Website: {profile.get('website') or '—'}\n"
            f"Primary contact: {profile.get('primary_contact') or '[PRIMARY CONTACT]'}\n"
            f"Finance/AP contact: {profile.get('finance_contact') or '—'}\n"
            f"NAICS: {profile.get('naics') or '—'}   UEI/SAM: {profile.get('uei_sam') or '—'}   DUNS: {profile.get('duns') or '—'}\n\n"
            f"Capabilities: {profile.get('capabilities') or 'Original, clearance-certified campaign music — composition through delivery.'}\n")
    return text, miss


def _gen_company_overview(profile) -> tuple:
    miss = _missing(profile, ["legal_name"])
    text = (f"COMPANY OVERVIEW — {_hdr(profile)}\n\n"
            f"{profile.get('capabilities') or 'Chordential is a procurement-grade music studio producing original, clearance-certified campaign music — from composition through cleared, delivery-ready masters.'}\n\n"
            f"Website: {profile.get('website') or '—'}\n"
            f"Primary contact: {profile.get('primary_contact') or '[PRIMARY CONTACT]'}\n")
    return text, miss


def _gen_cover_letter(profile) -> tuple:
    text = (f"To the procurement team,\n\n"
            f"Please find enclosed the vendor-onboarding documents for {_hdr(profile)}. "
            f"We've included everything required to set us up as an approved vendor; if any "
            f"additional forms are needed, our finance contact "
            f"({profile.get('finance_contact') or '[FINANCE CONTACT]'}) will turn them around "
            f"promptly.\n\nThank you,\n{profile.get('primary_contact') or 'Chordential'}\n")
    return text, _missing(profile, ["legal_name"])


def _gen_vendor_info(profile) -> tuple:
    return _gen_vendor_profile(profile)


def _gen_contact_sheet(profile) -> tuple:
    text = (f"CONTACT SHEET — {_hdr(profile)}\n\n"
            f"Primary: {profile.get('primary_contact') or '[PRIMARY CONTACT]'}\n"
            f"Finance / AP: {profile.get('finance_contact') or '—'}\n"
            f"Procurement: {profile.get('procurement_contact') or '—'}\n"
            f"Website: {profile.get('website') or '—'}\n")
    return text, _missing(profile, ["primary_contact"])


_GENERATORS = {
    "w9": _gen_w9, "ach": _gen_ach, "remittance": _gen_remittance, "banking": _gen_banking,
    "vendor_profile": _gen_vendor_profile, "company_overview": _gen_company_overview,
    "cover_letter": _gen_cover_letter, "vendor_info": _gen_vendor_info,
    "contact_sheet": _gen_contact_sheet,
}


def _placeholder(label: str, profile: dict, req_key: str) -> str:
    """A professional request-for-information when ChordOS can't legally auto-generate."""
    ask = {
        "coi": "the certificate holder's exact name/address and required coverage limits, so we can request the COI from our insurance carrier",
        "msa": "the client's MSA template (or their preferred terms) for legal review",
        "nda": "the client's NDA (or confirmation ChordOS's mutual NDA is acceptable)",
        "security_questionnaire": "the security/cyber questionnaire link or document",
        "vendor_portal": "the vendor-portal URL and any invitation/registration code",
        "vendor_code": "the vendor code once the client's system issues it",
    }.get(req_key, f"the details needed to complete the {label}")
    return (f"{label.upper()} — INFORMATION REQUEST\n\n"
            f"ChordOS cannot auto-generate this document — it requires input we don't hold. "
            f"To proceed, we need {ask}.\n\n"
            f"Once provided, ChordOS will prepare and track it toward completion. "
            f"Carrier on file: {profile.get('insurance_carrier') or '—'}; "
            f"limits: {profile.get('insurance_limits') or '—'}.\n")


# --------------------------------------------------------------------------- #
# Audit timeline.
# --------------------------------------------------------------------------- #
def add_event(conn, opp_id: int, verb: str, detail: str) -> None:
    db.add_procurement_event(conn, opp_id, verb, detail)


def timeline(conn, opp_id: int) -> list:
    return db.list_procurement_events(conn, opp_id)


# --------------------------------------------------------------------------- #
# Portal onboarding action (no integration — a guided task).
# --------------------------------------------------------------------------- #
def portal_action(conn, opp_id: int) -> Optional[dict]:
    """When a vendor portal is required, produce the guided upload task — required docs,
    what's still missing, recommended order — never an integration."""
    r = readiness(conn, opp_id)
    if not r["has_portal"]:
        return None
    reqs = db.list_procurement_requirements(conn, opp_id)
    have = [x for x in reqs if x["artifact_ref"] and x["status"] in ("generated", "uploaded", "complete")]
    missing = [x for x in reqs if x["owner"] == "chordential" and not x["artifact_ref"] and x["status"] != "na"]
    order = ["company_overview", "vendor_profile", "w9", "ach", "remittance", "banking_letter", "coi"]
    ready_docs = sorted([x["label"] for x in have],
                        key=lambda lbl: next((i for i, k in enumerate(order)
                                              if VOCAB.get(k, {}).get("label") == lbl), 99))
    return {
        "ready_docs": ready_docs,
        "missing_docs": [x["label"] for x in missing],
        "recommended_order": ready_docs,
        "eta_minutes": max(10, 5 * len(ready_docs)),
        "progress_pct": r["pct"],
    }


# --------------------------------------------------------------------------- #
# Learning — client-scoped procurement history (Relationship Intelligence).
# --------------------------------------------------------------------------- #
def complete_and_learn(conn, opp_id: int) -> dict:
    """Mark procurement complete and snapshot what this client required to a client-scoped
    history, so a future campaign for the same client pre-loads it (onboarding compounds)."""
    row = db.get_opportunity(conn, opp_id)
    if row is None:
        return {}
    client = row["client"]
    reqs = db.list_procurement_requirements(conn, opp_id)
    keys = [r["req_key"] for r in reqs if r["status"] != "na"]
    unnecessary = [r["req_key"] for r in reqs if r["status"] == "na"]
    started = db.first_procurement_event_at(conn, opp_id)
    snapshot = {"required": keys, "unnecessary": unnecessary,
                "completed_at": _now(), "started_at": started}
    db.save_client_procurement_history(conn, client, snapshot)
    add_event(conn, opp_id, "complete", "Procurement complete — learned for future campaigns")
    return snapshot


def seed_from_history(conn, opp_id: int) -> int:
    """Pre-load a new campaign's checklist from this client's prior procurement history — the
    onboarding effort ChordOS already paid once. Discovered requirements still override."""
    row = db.get_opportunity(conn, opp_id)
    if row is None:
        return 0
    hist = db.get_client_procurement_history(conn, row["client"])
    if not hist:
        return 0
    n = 0
    for key in hist.get("required", []):
        if db.get_procurement_requirement(conn, opp_id, key) is None:
            upsert_requirement(conn, opp_id, key, source="Prior campaign (this client)",
                               evidence="Required in a previous engagement", confidence=85)
            n += 1
    if n:
        add_event(conn, opp_id, "seeded", f"Pre-loaded {n} requirement(s) from this client's history")
    return n
