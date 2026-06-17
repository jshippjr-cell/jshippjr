"""Live web-crawl talent source — fetches creators from an APPROVED target.

This is the connector behind Jon's human-gated crawler. It only ever runs against
a target Jon has explicitly approved (see :mod:`chordential_oia.web.discovery`),
and the network call is additionally gated by an environment flag so it is OFF in
the egress-blocked sandbox and in CI, ON only where it can be operationally
supported (Render).

Design that keeps it testable and safe:
- ``parse_talent_html`` is a **pure function** (HTML string → Talent list) with no
  network, unit-tested against fixture HTML — the same trick the intake parser
  uses on sample email text.
- The actual fetch is isolated in ``_fetch_url`` and only reached when the flag is
  on, so tests never touch the network.
- Parsing reads a documented, structured listing format using the stdlib HTML
  parser (no ``beautifulsoup4`` dependency — keeps the Render install lean). Real
  per-site connectors extend this by mapping their markup onto the same contract.
- Fails soft: a malformed record is skipped, a failed fetch yields ``[]`` — a
  broken crawl never raises into the app.
"""

from __future__ import annotations

import os
from html.parser import HTMLParser
from typing import List, Optional

from ..models import MusicDiscipline
from ..talent import Talent
from .base import TalentSource

#: Env flag that must be truthy for any network fetch to happen.
SCRAPE_FLAG = "CHORDENTIAL_ENABLE_SCRAPE"


def scrape_enabled() -> bool:
    return os.environ.get(SCRAPE_FLAG, "").strip().lower() in {"1", "true", "yes", "on"}


def _disciplines(raw: str) -> List[MusicDiscipline]:
    out: List[MusicDiscipline] = []
    for token in (raw or "").split(","):
        token = token.strip().lower()
        if not token:
            continue
        try:
            out.append(MusicDiscipline(token))
        except ValueError:
            continue
    return out


class _CreatorListingParser(HTMLParser):
    """Extracts creator records from a documented listing structure.

    Each candidate is an element carrying ``data-*`` attributes::

        <li class="creator" data-name="Jane Doe"
            data-disciplines="composition,sound_design"
            data-location="Austin, TX" data-url="https://.../jane"
            data-credits="Scored two spots"></li>

    Only elements whose class includes ``creator`` are read, so surrounding page
    chrome is ignored.
    """

    def __init__(self) -> None:
        super().__init__()
        self.records: List[dict] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        if "creator" not in classes:
            return
        name = (a.get("data-name") or "").strip()
        if not name:
            return
        self.records.append(
            {
                "name": name,
                "disciplines": a.get("data-disciplines") or "",
                "location": (a.get("data-location") or "").strip() or None,
                "url": (a.get("data-url") or "").strip() or None,
                "credits": (a.get("data-credits") or "").strip(),
                "email": (a.get("data-email") or "").strip() or None,
            }
        )


def parse_talent_html(html: str, source_url: Optional[str] = None) -> List[Talent]:
    """Pure parser: structured listing HTML → Pending/Prospect Talent records.

    No network. Each creator enters at the review gate with ``source='crawl'`` and
    a link back to the profile it was built from.
    """
    parser = _CreatorListingParser()
    try:
        parser.feed(html or "")
    except Exception:  # malformed markup — yield whatever parsed cleanly
        pass
    out: List[Talent] = []
    for rec in parser.records:
        out.append(
            TalentSource._pending(
                name=rec["name"],
                email=rec["email"],
                disciplines=_disciplines(rec["disciplines"]),
                credits=rec["credits"],
                location=rec["location"],
                demo_reel_url=rec["url"],
                source="crawl",
                source_url=rec["url"] or source_url,
                notes="Discovered via approved crawl target.",
            )
        )
    return out


def _fetch_url(url: str, timeout: float = 10.0) -> str:
    """Fetch a URL's text. Only reached when the scrape flag is on (Render)."""
    import urllib.request

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "ChordentialDiscoveryBot/1.0 (+https://chordential.com)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


class ScrapedTalentSource(TalentSource):
    """Fetch + parse creators from a single approved target URL.

    Network is double-gated: the target must be Approved (enforced by the caller)
    AND the ``CHORDENTIAL_ENABLE_SCRAPE`` flag must be on. Off → returns ``[]``.
    """

    key = "crawl"
    name = "Approved Web Crawl"
    category = "crawl"

    def __init__(self, target_url: str) -> None:
        self.target_url = target_url

    def fetch(self, limit: int = 50) -> List[Talent]:
        if not scrape_enabled():
            return []
        try:
            html = _fetch_url(self.target_url)
        except Exception:  # fail soft — a failed fetch is never fatal
            return []
        return parse_talent_html(html, source_url=self.target_url)[:limit]
