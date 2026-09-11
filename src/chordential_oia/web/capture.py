"""Capture a creator from wherever you found them, in one tap.

The supply-side list has a rule the demand-side list also has: **a name enters only
with a public source beside it** (`docs/marketing/deliverables/09-composer-track.md`
§6 — *ten rows, each with a link*). That rule is easy to state and annoying to keep,
because the moment you find someone good you are on a phone, inside Reddit, three
threads deep, and the honest thing to do costs six fields of typing. So it does not
get done, and a week later there is a name in a notebook with no link under it.

This module is the one-tap version. A bookmarklet (desktop) or a Share-sheet shortcut
(phone) hands `/capture/creator` the page's URL, title and any selected text; the form arrives
already filled in; one tap writes a `talent` row with `source_url` set. The link is
captured by construction rather than by discipline.

**Why a form and not a fire-and-forget POST.** A bookmarklet running on reddit.com
cannot POST to chordential.com without either CORS or a GET that writes, and a GET that
writes is a link a crawler can fire. Opening a prefilled form is the version that works
identically on iOS Safari and on a desktop, needs no cross-origin permission, and gives
the one thing a scrape cannot: a human glance before the row exists. Roughly two seconds
more, and the row is right.

**The token is the access control.** `/capture/creator` is exempt from the admin gate in
`publicpaths.py` because a share-sheet shortcut carries no session cookie; the route
checks `?k=` against `CHORDENTIAL_CAPTURE_TOKEN` itself and 404s without it. Unset means
**capture is off** — the same null-by-default seam the mail and payment providers use.
Nothing here is reachable on an instance that has not opted in.
"""

from __future__ import annotations

import os
import re
from typing import Optional
from urllib.parse import quote, urlparse

# Where a capture came from. Kept short and closed: it feeds `talent.source`, which
# the Friday sheet groups by, and a free-text field there becomes nine spellings of
# "reddit" inside a month.
SOURCES = ("reddit", "vi-control", "discord", "soundbetter", "linkedin", "web")

_HOSTS = {
    "reddit.com": "reddit",
    "vi-control.net": "vi-control",
    "discord.com": "discord",
    "soundbetter.com": "soundbetter",
    "linkedin.com": "linkedin",
}

# /user/<name> and /u/<name> on Reddit; /members/<name>.<id> on XenForo (VI-Control).
_REDDIT_USER_RE = re.compile(r"/(?:user|u)/([A-Za-z0-9_\-]{2,30})")
_XF_MEMBER_RE = re.compile(r"/members/([A-Za-z0-9_\-]{2,40})")


def capture_token() -> str:
    """The shared secret the bookmarklet and the shortcut carry. Blank = capture off."""
    return (os.environ.get("CHORDENTIAL_CAPTURE_TOKEN") or "").strip()


def capture_enabled() -> bool:
    return bool(capture_token())


def token_ok(supplied: Optional[str]) -> bool:
    """Constant-ish comparison against the configured token. Never true when unset —
    an instance that has not opted in must not have an open write door."""
    tok = capture_token()
    if not tok:
        return False
    got = (supplied or "").strip()
    if len(got) != len(tok):
        return False
    same = 0
    for a, b in zip(got, tok):
        same |= ord(a) ^ ord(b)
    return same == 0


def source_for(url: str) -> str:
    """Which room this came from, from the host alone. Unknown hosts are 'web' rather
    than a guess — the URL is still recorded, which is the part that matters."""
    try:
        host = (urlparse(url or "").hostname or "").lower()
    except ValueError:
        return "web"
    host = host[4:] if host.startswith("www.") else host
    for known, key in _HOSTS.items():
        if host == known or host.endswith("." + known):
            return key
    return "web"


def handle_for(url: str, source: Optional[str] = None) -> str:
    """The platform username, where the URL states it. Never invented: a thread URL
    with no /user/ in it returns blank, and the operator types the name they can see."""
    src = source or source_for(url)
    if src == "reddit":
        m = _REDDIT_USER_RE.search(url or "")
        return m.group(1) if m else ""
    if src == "vi-control":
        m = _XF_MEMBER_RE.search(url or "")
        return (m.group(1) if m else "").replace("-", " ").strip()
    return ""


def reddit_compose_url(handle: str, subject: str, body: str) -> str:
    """Reddit's own compose screen, addressed and filled in, for the operator to send.

    Deliberately NOT the API. Reddit's API would let the studio send this without a
    human, and unsolicited automated messages are the fastest way to lose the account
    — which would cost exactly the rooms the composer track depends on. This opens the
    message already written; he reads it and presses send. Same seconds, no risk, and
    the message is his.
    """
    h = (handle or "").lstrip("/u").lstrip("/").strip()
    return ("https://www.reddit.com/message/compose"
            f"?to={quote(h)}&subject={quote(subject[:100])}&message={quote(body[:10000])}")


def bookmarklet(base: str, token: str) -> str:
    """The one-line bookmark that opens a prefilled capture form from any page.

    Sends the page URL, its title and the current selection. Kept to one statement and
    no dependencies because it has to survive being pasted into a phone's bookmark
    field, where a newline ends it.
    """
    target = f"{base.rstrip('/')}/capture/creator?k={quote(token)}"
    return (
        "javascript:(function(){var s='';try{s=String(window.getSelection()||'')}"
        "catch(e){};window.open('" + target + "&url='+encodeURIComponent(location.href)"
        "+'&title='+encodeURIComponent(document.title||'')"
        "+'&note='+encodeURIComponent(s.slice(0,600)),'_blank');})()"
    )


def capture_url(base: str, token: str) -> str:
    """The plain form, for a phone shortcut that appends &url=… itself."""
    return f"{base.rstrip('/')}/capture/creator?k={quote(token)}"
