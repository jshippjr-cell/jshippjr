"""Email-alert intake — turn a forwarded saved-search alert into opportunities.

This is the first *live* intake path (per the strategy: ~95% of A-tier value
arrives through agency/email-alert channels, not gov scraping). Saved-search
alerts from Mandy, ProductionHub, Hitmarker, etc. are forwarded to an intake
inbox; this module parses the (semi-structured) email text into
:class:`Opportunity` records that flow straight into qualify → rank.

The parser is deliberately heuristic and provider-agnostic: it handles labeled
digests (``Title:`` / ``Company:`` / ``Budget:`` / ``Location:``) and splits a
multi-job email into one ``Opportunity`` per posting. Unset scoring signals are
left to the engines' text inference; only signals we can read confidently
(buyer type, music requirement, budget, location) are stamped here.
"""

from __future__ import annotations

import os
import re
from typing import List, Optional, Tuple

from .models import BuyerType, MusicRequirement, Opportunity

# Lines of 3+ dashes/equals/underscores separate postings in a digest.
_SEPARATOR_RE = re.compile(r"^\s*[-=_]{3,}\s*$")
# A posting starts at one of these labels.
_TITLE_LABELS = ("title", "role", "job", "position", "gig")
_CLIENT_LABELS = ("company", "client", "posted by", "employer", "studio", "organization")
_BUDGET_LABELS = ("budget", "rate", "comp", "compensation", "pay", "fee")
_LOCATION_LABELS = ("location", "based in", "where")

_EMAIL_HEADER_LABELS = ("from", "to", "subject", "date", "reply-to", "cc")
_FOOTER_MARKERS = (
    "unsubscribe", "manage alerts", "you are receiving this", "you have ",
    "manage your", "view in browser",
)

# Provider detection from the raw email (for provenance).
_PROVIDERS = {
    "mandy": "Mandy Network",
    "productionhub": "ProductionHUB",
    "hitmarker": "Hitmarker",
    "staffmeup": "Staff Me Up",
    "staff me up": "Staff Me Up",
}

# Keyword inference (kept here so intake can stamp confident signals).
_AGENCY_KW = ("agency", "advertis", "creative shop")
_BRAND_KW = ("brand", "marketing team", "(brand)", "cpg", "beverage co", "consumer")
_PRODUCTION_KW = (
    "production", "productions", "pictures", "films", "film", "studio", "games",
    "media", "entertainment",
)
_GOVERNMENT_KW = (
    "city of", "county", "federal", "department of", "municipal", "state of",
    "gov", "public affairs",
)
_ORIGINAL_KW = (
    "original", "compose", "composer", "score", "custom music", "write music",
    "anthem", "jingle", "underscore", "sonic logo", "sonic brand", "audio identity",
)
_LICENSED_KW = (
    "license", "licensed", "pre-existing", "existing track", "library", "stock",
    "needle drop", "sync placement", "supervisor",
)


def _label_value(block: str, labels: Tuple[str, ...]) -> Optional[str]:
    """Return the value of the first matching ``Label: value`` line in a block."""
    for label in labels:
        m = re.search(
            rf"^\s*{re.escape(label)}\s*[:\-]\s*(.+?)\s*$",
            block,
            re.IGNORECASE | re.MULTILINE,
        )
        if m:
            return m.group(1).strip()
    return None


def _parse_money(text: str) -> Tuple[Optional[float], Optional[float]]:
    """Pull a min/max budget out of free text. Handles ``$8,000-$15,000``,
    ``$20k``, ``$4,000``."""
    if not text:
        return None, None

    def _num(token: str) -> Optional[float]:
        token = token.strip().lower().replace(",", "").replace("$", "")
        if not token:
            return None
        mult = 1.0
        if token.endswith("k"):
            mult, token = 1000.0, token[:-1]
        try:
            return float(token) * mult
        except ValueError:
            return None

    amounts = re.findall(r"\$?\s?(\d[\d,]*(?:\.\d+)?\s?k?)", text, re.IGNORECASE)
    nums = [n for n in (_num(a) for a in amounts) if n is not None]
    # Ignore stray small integers that aren't money (e.g. ":30").
    nums = [n for n in nums if n >= 100]
    if not nums:
        return None, None
    if len(nums) == 1:
        return nums[0], None
    return min(nums), max(nums)


def _infer_buyer(text: str) -> BuyerType:
    t = text.lower()
    if any(k in t for k in _GOVERNMENT_KW):
        return BuyerType.GOVERNMENT
    if any(k in t for k in _AGENCY_KW):
        return BuyerType.AGENCY
    if any(k in t for k in _BRAND_KW):
        return BuyerType.BRAND
    if any(k in t for k in _PRODUCTION_KW):
        return BuyerType.PRODUCTION_COMPANY
    return BuyerType.UNKNOWN


def _infer_music(text: str) -> MusicRequirement:
    t = text.lower()
    # Original wins when both appear (e.g. "original score" + "license stems").
    if any(k in t for k in _ORIGINAL_KW):
        return MusicRequirement.ORIGINAL
    if any(k in t for k in _LICENSED_KW):
        return MusicRequirement.LICENSED
    return MusicRequirement.IMPLIED


def _split_postings(body: str) -> List[str]:
    """Split a digest body into one text block per posting."""
    lines = body.splitlines()
    # Strip leading email headers and trailing footer chatter.
    cleaned: List[str] = []
    for line in lines:
        low = line.strip().lower()
        if any(low.startswith(f"{h}:") for h in _EMAIL_HEADER_LABELS):
            continue
        if any(low.startswith(m) for m in _FOOTER_MARKERS):
            continue
        cleaned.append(line)

    # Prefer explicit separators; otherwise split at each Title/Role label.
    if any(_SEPARATOR_RE.match(l) for l in cleaned):
        blocks, current = [], []
        for line in cleaned:
            if _SEPARATOR_RE.match(line):
                if current:
                    blocks.append("\n".join(current))
                    current = []
            else:
                current.append(line)
        if current:
            blocks.append("\n".join(current))
    else:
        blocks, current = [], []
        for line in cleaned:
            is_title = any(
                re.match(rf"^\s*{lbl}\s*[:\-]", line, re.IGNORECASE)
                for lbl in _TITLE_LABELS
            )
            if is_title and current:
                blocks.append("\n".join(current))
                current = [line]
            else:
                current.append(line)
        if current:
            blocks.append("\n".join(current))

    # Keep only blocks that actually look like a posting (have a title or body).
    return [b for b in blocks if b.strip()]


def _block_to_opportunity(block: str, source_name: str) -> Optional[Opportunity]:
    title = _label_value(block, _TITLE_LABELS)
    if title is None:
        # No label — take the first substantive line as the title.
        for line in block.splitlines():
            if len(line.strip()) >= 8:
                title = line.strip()
                break
    if not title:
        return None

    client = _label_value(block, _CLIENT_LABELS) or "Unknown (from alert)"
    location = _label_value(block, _LOCATION_LABELS)
    budget_text = _label_value(block, _BUDGET_LABELS) or ""
    budget_min, budget_max = _parse_money(budget_text)

    # Description = the block minus the label lines we already consumed.
    desc_lines = []
    for line in block.splitlines():
        low = line.strip().lower()
        if any(
            re.match(rf"^\s*{lbl}\s*[:\-]", line, re.IGNORECASE)
            for lbl in (
                _TITLE_LABELS + _CLIENT_LABELS + _BUDGET_LABELS
                + _LOCATION_LABELS + ("posted",)
            )
        ):
            continue
        if low:
            desc_lines.append(line.strip())
    description = " ".join(desc_lines).strip()

    blob = f"{title} {client} {description}"
    sonic = True if any(
        k in blob.lower() for k in ("sonic", "audio logo", "audio identity")
    ) else None

    return Opportunity(
        client=client,
        need=title,
        source=source_name,
        description=description,
        buyer_type=_infer_buyer(blob),
        music_requirement=_infer_music(blob),
        sonic_branding=sonic,
        budget_min=budget_min,
        budget_max=budget_max,
        location=location,
        tags=["email-alert"],
    )


def detect_provider(raw: str) -> str:
    low = raw.lower()
    for needle, name in _PROVIDERS.items():
        if needle in low:
            return name
    return "Email Alert"


def parse_alert_email(raw: str, source_name: Optional[str] = None) -> List[Opportunity]:
    """Parse one forwarded alert email into a list of opportunities."""
    name = source_name or detect_provider(raw)
    opportunities: List[Opportunity] = []
    for block in _split_postings(raw):
        opp = _block_to_opportunity(block, name)
        if opp is not None:
            opportunities.append(opp)
    return opportunities


def parse_email_path(path: str) -> List[Opportunity]:
    """Parse a single alert file or every ``.txt``/``.eml`` file in a directory."""
    if os.path.isdir(path):
        opportunities: List[Opportunity] = []
        for entry in sorted(os.listdir(path)):
            if entry.lower().endswith((".txt", ".eml")):
                with open(os.path.join(path, entry), "r", encoding="utf-8") as fh:
                    opportunities.extend(parse_alert_email(fh.read()))
        return opportunities
    with open(path, "r", encoding="utf-8") as fh:
        return parse_alert_email(fh.read())
