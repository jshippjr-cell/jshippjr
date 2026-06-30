"""Recruiting composer — the supply-side analog of the client first-touch composer.

Assembles a **personalized creator invite** from deterministic blocks (no LLM):
who we are, why *them* specifically, what we honestly offer creators, and a soft
link. Mirrors the client outreach pattern so the same "machine proposes, Jon
disposes" discipline applies — the composer drafts; Jon reads, edits, and sends.

The pitch follows the council's ruling (``docs/talent-recruiting-council.md`` §2):
promise **respect, fair terms, and first-look** — never volume or a salary. A new
studio that over-promises a paycheck churns creators angry; under-promising volume
and over-delivering on how we treat people is the honest, durable recruit.
"""

from __future__ import annotations

from typing import List, Optional


def _first_name(name: str) -> str:
    return (name or "there").strip().split(" ")[0] or "there"


def _why_them(t) -> str:
    """The personalized line — leads with a real credit when we have one, else the
    craft we want them for. Never generic flattery we can't back up."""
    credit = (getattr(t, "credits", "") or "").strip()
    disciplines = getattr(t, "discipline_labels", []) or []
    if credit:
        snippet = credit.rstrip(".")
        if len(snippet) > 140:
            snippet = snippet[:137].rstrip() + "…"
        return (f"Your work caught my eye — {snippet[0].lower()}{snippet[1:]}. "
                f"That's exactly the kind of craft we want on our roster.")
    if disciplines:
        craft = disciplines[0].lower()
        return (f"We're building a small, curated roster of {craft} talent, and "
                f"your profile is the kind of work we want to bring real briefs to.")
    return ("We're building a small, curated roster of music creators, and you're "
            "the kind of artist we'd want to bring real briefs to.")


def invite_blocks(
    t,
    *,
    apply_url: str,
    artists_url: str,
    from_name: str = "Jon",
) -> List[dict]:
    """The ordered blocks of the invite. Each is ``{"key", "text"}`` so the UI can
    show/skip them; joined with blank lines they form the default draft."""
    return [
        {"key": "greeting", "text": f"Hi {_first_name(t.name)},"},
        {"key": "who",
         "text": (f"I'm {from_name}, founder of Chordential — a small studio making "
                  "original, clearance-certified music for ad campaigns.")},
        {"key": "why", "text": _why_them(t)},
        {"key": "offer",
         "text": ("What I can honestly offer: real, paid briefs (never spec), clean "
                  "rights and prompt payment, and first-look when a brief fits your "
                  "craft. I won't pretend we have a flood of work — we're early — but "
                  "you'd be chosen, not bidding against a marketplace, and we treat "
                  "creators with respect and pay fast.")},
        {"key": "cta",
         "text": (f"If that resonates, here's how we work with artists: {artists_url}\n"
                  f"And you can send your reel whenever you like: {apply_url}")},
        {"key": "signoff", "text": f"— {from_name}, Chordential"},
    ]


def compose_invite(
    t,
    *,
    apply_url: str,
    artists_url: str,
    from_name: str = "Jon",
    skip: Optional[List[str]] = None,
) -> dict:
    """Assemble the invite into ``{"subject", "body"}``. ``skip`` drops blocks by key."""
    skip = set(skip or [])
    blocks = [b for b in invite_blocks(
        t, apply_url=apply_url, artists_url=artists_url, from_name=from_name)
        if b["key"] not in skip]
    body = "\n\n".join(b["text"] for b in blocks)
    subject = f"A curated invite from Chordential, {_first_name(t.name)}"
    return {"subject": subject, "body": body}
