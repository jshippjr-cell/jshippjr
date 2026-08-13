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
        return (f"Your work caught my eye: {snippet[0].lower()}{snippet[1:]}. "
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
         "text": (f"I'm {from_name}, founder of Chordential, a small studio making "
                  "original, clearance-certified music for ad campaigns.")},
        {"key": "why", "text": _why_them(t)},
        {"key": "offer",
         "text": ("What I can honestly offer: real, paid briefs (never spec), clean "
                  "rights and prompt payment, and first-look when a brief fits your "
                  "craft. I won't pretend we have a flood of work; we're early, but "
                  "you'd be chosen, not bidding against a marketplace, and we treat "
                  "creators with respect and pay fast.")},
        {"key": "cta",
         "text": (f"If that resonates, here's how we work with artists: {artists_url}\n"
                  f"And you can send your reel whenever you like: {apply_url}")},
        {"key": "signoff", "text": f"{from_name}, Chordential"},
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


def _money(value: Optional[float]) -> str:
    if value is None:
        return ""
    return f"${value:,.0f}"


def compose_review_decision(
    t, *, accepted: bool, artists_url: str, from_name: str = "Jon",
) -> dict:
    """The reel-review verdict, sent to an applicant so they're never left
    wondering. ``t.disciplines``/``t.rate``/``t.rate_unit`` (already on
    every Talent record) fill in capacity + rate for an accepted creator —
    never a promise of steady volume, matching the invite's honesty rule."""
    name = _first_name(t.name)
    if accepted:
        crafts = ", ".join(t.discipline_labels) or "your craft"
        rate_line = ""
        if t.rate:
            unit = {"hourly": "/hr", "day": "/day", "project": "/project"}.get(
                t.rate_unit, "")
            rate_line = f"\n\nFor reference, our standing rate for this work is {_money(t.rate)}{unit}. We'll confirm specifics on any brief before it starts."
        body = (
            f"Hi {name},\n\n"
            f"Good news: I reviewed your reel and you're in. You're on the roster "
            f"for {crafts}, first-look on real, paid briefs when one fits your "
            f"craft (never spec, never a promise of volume; we're early, and "
            f"honest about that).{rate_line}\n\n"
            f"Here's how we work with artists, if you haven't already seen it: "
            f"{artists_url}\n\n"
            f"{from_name}, Chordential"
        )
        subject = f"You're on the roster, {name}"
    else:
        body = (
            f"Hi {name},\n\n"
            f"Thanks for sending your reel. I gave it a real listen. It's not a "
            f"fit for what we're building right now, so I won't add you to the "
            f"roster. That's a read on current fit, not a judgment on the work.\n\n"
            f"{from_name}, Chordential"
        )
        subject = "Following up on your Chordential application"
    return {"subject": subject, "body": body}


def compose_project_assignment(
    t, *, role: str, client: str, need: str,
    deadline: str = "", from_name: str = "Jon",
) -> dict:
    """Sent the moment a creator is signed onto a project (the ONLY assign
    path — Jon's explicit decision), so they hear the scope from us before
    anything else. Rate reference comes from the creator's own standing
    rate; a fixed-scope/clean-rights terms line matches the recruiting
    invite's promise. The project's BUDGET is never shown — a creator is
    paid their own rate, and the client's budget isn't theirs to see."""
    name = _first_name(t.name)
    brief = (need or "this project").strip()
    deadline_line = f"\nDeadline: {deadline}" if deadline else ""
    rate_line = ""
    if t.rate:
        unit = {"hourly": "/hr", "day": "/day", "project": "/project"}.get(t.rate_unit, "")
        rate_line = f"\nYour rate: {_money(t.rate)}{unit}"
    body = (
        f"Hi {name},\n\n"
        f"You're signed on. Here's the scope.\n\n"
        f"Client: {client or 'Chordential'}\n"
        f"Role: {role}\n"
        f"Brief: {brief}"
        f"{deadline_line}{rate_line}\n\n"
        f"Original, cleared work, fixed scope, clean rights, same terms as always. "
        f"I'll follow up with anything else you need to get started.\n\n"
        f"{from_name}, Chordential"
    )
    subject = f"You're signed on: {client or 'a new project'} ({role})"
    return {"subject": subject, "body": body}


def compose_client_assignment_update(
    *, role: str, creator_name: str, need: str,
    contact_name: str = "", workspace_url: str = "", from_name: str = "Jon",
) -> dict:
    """Client-facing update sent when a creator is signed onto their project — so the
    buyer hears their team is coming together, from us, the moment it happens. Never
    mentions the creator's rate or the internal cost; it's a warm status note, not a
    back-office leak."""
    greeting = f"Hi {_first_name(contact_name)}," if contact_name.strip() else "Hi there,"
    brief = (need or "your project").strip()
    creator = _first_name(creator_name) or "a specialist"
    body = (
        f"{greeting}\n\n"
        f"Good news: {creator} is on board as the {role} for {brief}. Your team is "
        f"coming together and the work is moving.\n\n"
        f"Your workspace has everything: the brief, new versions as they land, and "
        f"where to weigh in" + (f":\n{workspace_url}" if workspace_url else ".") + "\n\n"
        f"{from_name}, Chordential"
    )
    subject = f"Your {role} is on board · {brief}"
    return {"subject": subject, "body": body}
