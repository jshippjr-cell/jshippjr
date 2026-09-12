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
    """The bookmark that READS the page, not just its address.

    The first version sent `location.href`, `document.title` and the selection, which
    on a forum thread means the thread's title and nothing else — while the member's
    name sits in the markup two elements away. The founder's verdict on that was
    "kinda useless" (2026-09-11) and it was correct: saving one paste is not worth a
    bookmark.

    So this pulls the person out of the page. In order of confidence:

    * **XenForo** (VI-Control and most music forums): `.memberHeader-name` on a member
      profile, else the author of the post the selection is inside, else the first post's
      author. The name a forum renders is the name to write down.
    * **Reddit**: the username from the URL on a profile, else the first `/user/` link
      on the page, which on a comment permalink is its author.
    * Anything else: `og:title`, and only when the page looks like a profile.
    * **An email**, from the first `mailto:` on the page.
    * **Reel candidates** — links to SoundCloud, Bandcamp, Spotify, Apple Music, YouTube,
      Vimeo and Linktree. `talent.matchable` needs an approved reel, so the link to the
      work is the field that decides whether the row is ever usable, and it is almost
      always already on the page as a signature or a profile field.

    Everything it finds is a PROPOSAL on a form the operator looks at. Nothing here is
    written without a human seeing it, which is why guessing is safe: a wrong guess costs
    a glance, and the alternative costs the capture.
    """
    target = f"{base.rstrip('/')}/capture/creator?k={quote(token)}"
    js = (
        "javascript:(function(){"
        "var d=document,L=location.href,T=function(e){return e?(e.textContent||'').trim():''};"
        "var n='',em='',R=[];"
        # XenForo: member profile header, then the post the selection sits in
        "var h=d.querySelector('.memberHeader-name .username,.memberHeader-name,h1.memberHeader-name');"
        "if(h)n=T(h);"
        "var sel='';try{sel=String(window.getSelection()||'')}catch(e){}"
        "if(!n){var a=null;try{var r=window.getSelection();"
        "if(r&&r.rangeCount){var p=r.getRangeAt(0).startContainer;"
        "p=p.nodeType===1?p:p.parentNode;"
        "while(p&&p!==d.body){if(p.querySelector&&p.querySelector('.message-name .username,.message-name'))"
        "{a=p.querySelector('.message-name .username,.message-name');break}p=p.parentNode}}}catch(e){}"
        "if(a)n=T(a);}"
        "if(!n){var f=d.querySelector('.message-name .username,.message-name');if(f)n=T(f);}"
        # Reddit
        "if(!n){var m=L.match(/\\/(?:user|u)\\/([A-Za-z0-9_\\-]{2,30})/);if(m)n=m[1];}"
        "if(!n){var ru=d.querySelector('a[href*=\"/user/\"]');"
        "if(ru){var m2=ru.getAttribute('href').match(/\\/user\\/([A-Za-z0-9_\\-]{2,30})/);if(m2)n=m2[1];}}"
        # an email, if the page states one
        "var ml=d.querySelector('a[href^=\"mailto:\"]');"
        "if(ml)em=ml.getAttribute('href').slice(7).split('?')[0];"
        # where the work lives
        "var as=d.querySelectorAll('a[href]');"
        "for(var i=0;i<as.length&&R.length<5;i++){var u=as[i].href||'';"
        "if(/soundcloud\\.com|bandcamp\\.com|open\\.spotify\\.com|music\\.apple\\.com"
        "|youtube\\.com\\/(?:c|channel|user|@)|vimeo\\.com|linktr\\.ee/i.test(u)"
        "&&R.indexOf(u)<0)R.push(u);}"
        "var E=encodeURIComponent;"
        "window.open('" + target + "'"
        "+'&url='+E(L)+'&title='+E(d.title||'')+'&name='+E(n)"
        "+'&email='+E(em)+'&note='+E(sel.slice(0,600))"
        "+'&reels='+E(R.join('|')),'_blank');})()"
    )
    return js


def capture_url(base: str, token: str) -> str:
    """The plain form, for a phone shortcut that appends &url=… itself."""
    return f"{base.rstrip('/')}/capture/creator?k={quote(token)}"
