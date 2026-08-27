"""One room, capability-gated by who holds the link.

The decision (operator, 2026-08-18): *"one room, capability-gated by who holds the link,
published versions only."*

Until now the same engagement had three surfaces — the composer's Session Room, the
client's delivery portal, the operator's console — each with its own template, its own
idea of what a version is, and its own copy of the picture. Three renderings of one
thing is how they drift, and it is why a creator with three hats got three rooms and a
client got a page that looked nothing like the room the work happens in.

So: **one derivation, many reporters** (the rule ADR-0029/0033/0057 already apply to the
queue, the price and the relationship), applied to the room itself. `room_view` builds
the engagement ONCE. `CAPS` decides what a given role is handed. A surface renders what
it is given and asks no further questions.

The gate is server-side and subtractive: content a role may not see is **absent from the
dict**, not hidden in the template. A template that forgets an `{% if %}` then leaks
nothing, which is the only arrangement worth trusting — the client's copy is built by
never putting the pending take in it.

Roles
-----
``operator``  the studio. Sees everything, including what is still pending.
``talent``    the people doing the work. See the brief, the picture, the client's notes,
              their OWN pending submission, and who else played.
``client``    the buyer. Sees the picture, **published versions only**, the notes
              conversation, and the deliverables they are signing off.
"""

from __future__ import annotations

from typing import Optional

OPERATOR, TALENT, CLIENT = "operator", "talent", "client"
ROLES = (OPERATOR, TALENT, CLIENT)

# What each role may do or see. Read as: everything absent is denied.
CAPS = {
    OPERATOR: {
        # The studio's verdict is PUBLISH — the buffer between a submitted take and the
        # client hearing it. It is deliberately NOT `client_verdict`: the creative
        # sign-off, and the revision round it governs, belong to the buyer who is paying
        # for them. "the studio's approval is just a buffer, it comes before the client's
        # approval" (operator, 2026-08-19).
        #
        # `see_contributors` is gone too: naming who played is the COMPOSER's obligation
        # under clause 6A, and the control belongs where the obligation is. The studio
        # still sees who is outstanding — on the delivery console, where the clearance
        # certificate is signed.
        # NOT `upload_take`. Submitting a take is the CREATOR's channel and its door is
        # the creator's token — rendered in the studio's room it produced
        # `/creator//project/N/version`, an upload that could only fail. The studio's own
        # path to the ladder is the delivery console, which is where publishing happens
        # anyway; a second one here would be a second way to do one thing, through a
        # door the studio does not hold.
        "see_pending", "see_internal", "see_captures",
        "see_deliverable_specs", "see_money", "see_invoice", "comment",
        "download_source", "publish", "see_who", "address_note",
    },
    TALENT: {
        # Their own pending submission — they uploaded it; hiding it made the portal
        # look like nothing had happened (reported live, and fixed once already).
        "see_pending", "see_internal", "see_contributors", "see_captures",
        "see_deliverable_specs", "upload_take", "comment", "download_source",
        "see_who", "address_note", "ask_studio", "capture",
    },
    CLIENT: {
        # PUBLISHED VERSIONS ONLY. A client who can hear an unreviewed take makes the
        # taste gate decorative, and the gate is the thing that protects them from a
        # first impression nobody chose.
        #
        # `client_verdict` is theirs alone. Approving locks the master; requesting
        # changes spends one of THEIR rounds. Neither is a decision the studio can take
        # on their behalf from inside the room.
        #
        # No `see_who`: the buyer bought music from Chordential, not a roster. They see
        # that the studio is in the room and what the studio said — never which
        # freelancer said it, nor that a freelancer exists. The exec review made this
        # the condition on putting the room in front of a real client, and they were
        # right: the roster is the business, and it walks out of the door with the name.
        # No `address_note`: "addressed" is OUR working state — this note is dealt with
        # in the take being submitted. The buyer holds `resolved`, which they set after
        # HEARING the take. One button that closes a note nobody has worked yet, sitting
        # on the buyer's own screen, is how a round gets spent on nothing.
        # No `ask_studio` either: the talk-back channel is composer↔studio and internal
        # by definition — a client asking the studio just leaves a note.
        #
        # `see_invoice` is theirs because it is THEIR invoice: what is outstanding, and
        # the button that clears it. `see_money` — what the work cost us — is not the
        # same thing and stays with the studio.
        "comment", "client_verdict", "see_invoice", "sign_off_asset",
    },
}

# What the studio speaks as, to a buyer. One voice, whoever is holding the pen.
STUDIO_VOICE = "Chordential"


def attribute(role: str, author_role: str, name: str) -> str:
    """The name a viewer in ``role`` may see against a note written by ``author_role``.

    A client's own side keeps its names — they know who their people are, and stripping
    them would make their own conversation unreadable. Everything on our side of the
    room is the studio, and anything whose side is not RECORDED is treated as ours: an
    unattributed row is the one case where guessing wrong costs a relationship rather
    than a little readability.
    """
    if can(role, "see_who"):
        return name
    return name if (author_role or "") == CLIENT else STUDIO_VOICE


def caps_for(role: str) -> frozenset:
    """The capability set for a role. An unknown role gets nothing, deliberately —
    a typo must fail closed, not open."""
    return frozenset(CAPS.get(role, frozenset()))


def can(role: str, capability: str) -> bool:
    return capability in caps_for(role)


def client_url(conn, db, opp_id: int, base: str = "", flag: str = "") -> str:
    """The client's ONE destination for this deal — absolute when ``base`` is given.

    THE ROOM once a project exists; the workspace only before one does. *"any new links
    sent out after a countersign should send them to 'the room'"* (operator, 2026-08-27).

    ONE derivation, because there were five places minting this URL by hand and they are
    the places a link reaches a real buyer: the countersignature, the receipt, the "your
    composer is on board" note, the payment return. `/workspace/{token}` redirects here
    anyway, so a stale one is not broken — but a redirect is a repair the client watches
    happen, and the next hand-written one would have been written before anybody
    remembered the redirect existed.

    Returns "" when there is no token at all, so a caller can decide between a linkless
    email and no email — never a dead href.
    """
    token = db.ensure_share_token(conn, opp_id)
    if not token:
        return ""
    project = db.project_for_opp(conn, opp_id)
    path = (f"/room/{project['id']}?k={token}" if project is not None
            else f"/workspace/{token}")
    if flag:
        path += ("&" if "?" in path else "?") + flag
    return (base.rstrip("/") + path) if base else path


def priced_notes_only(feedback: dict) -> dict:
    """The composer's list, with everything a human has not yet priced removed.

    ADR-0069. "Request changes" cost a revision round and a plain note cost nothing —
    and both reached the composer and both got worked on. That is an unpriced revision
    channel running beside a counter that says "Round 1 of 2", and the buyer learns which
    lane is free within one project. A note becomes WORK only once the studio has called
    it a conform (picture moved — free), a revision (counts a round), or out of scope
    (quoted separately, never actioned for nothing).

    This is "the machine proposes, Jon disposes" applied to feedback rather than to
    buttons — the same rule, one layer deeper.
    """
    fb = dict(feedback or {})
    kept = [n for n in (fb.get("notes") or [])
            if (n.get("disposition") or "") in ("conform", "revision")]
    fb["notes"] = kept
    # The earlier takes' notes obey the same rule. They are the same notes, one
    # version back; an unpriced one does not become work by being old.
    fb["archive"] = [n for n in (fb.get("archive") or [])
                     if (n.get("disposition") or "") in ("conform", "revision")]
    fb["open_count"] = sum(1 for n in kept
                           if n.get("kind") in ("comment", "change_request")
                           and not (n.get("resolved") or n.get("addressed")))
    return fb


#: Where uploaded media lives, and the reason a client may not fetch it directly.
_UPLOADS = "/uploads/"


def _streamable(name: str) -> bool:
    """Is this something a browser plays in place?

    The flag is decided per FILE, not per room. Stamping `stream=1` on everything sent
    the paid client's "Download everything" button to `…/pkg.zip?stream=1`, and the
    download route refuses a streamed ZIP by design — so fixing the buyer's silence broke
    the buyer's download. Same door either way; the flag is what differs.
    """
    import mimetypes
    guess = mimetypes.guess_type(name or "")[0] or ""
    return (guess.split("/")[0] in ("audio", "video", "image")
            and not guess.endswith("svg+xml"))


def _client_media(url: str, project_id: int, token: str, kind: str) -> str:
    """One `/uploads/…` URL, rewritten to the door a client actually holds."""
    if not url.startswith(_UPLOADS):
        return url
    base = url[len(_UPLOADS):].split("?")[0].split("/")[-1]
    if not base:
        return url
    q = f"?{kind}={token}"
    return f"/project/{project_id}/dl/{base}{q}" + ("&stream=1" if _streamable(base) else "")


def route_media(value, project_id: int, token: str, kind: str = "k"):
    """Rewrite EVERY media URL in a room to the token-scoped, streamable door.

    `/uploads/{name}` sits behind the ADMIN gate — client media is meant to travel the
    per-project `/dl/` road instead. The room handed the client `/uploads/…` anyway, so a
    buyer's `<audio>` fetched a login page and played silence: they could hear neither
    the master they were reviewing nor the stems they were being asked to sign off
    (operator, 2026-08-21).

    Done as a BLANKET WALK of the room rather than field by field, for the same reason
    `send_email` wraps the branded shell centrally: the surfaces that carry media keep
    multiplying — versions, the picture, the master, every file in every deliverable lane
    — and a per-field rewrite is a list someone has to remember to extend. A new surface
    cannot forget this one.

    Only the plain ``url`` key is rewritten. ``dl_url`` is the real download and stays
    exactly as it was: payment-gated, and not something streaming may quietly open.
    """
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k == "url" and isinstance(v, str):
                out[k] = _client_media(v, project_id, token, kind)
            else:
                out[k] = route_media(v, project_id, token, kind)
        return out
    if isinstance(value, list):
        return [route_media(v, project_id, token, kind) for v in value]
    return value


def room_view(conn, db, project_id: int, role: str, *,
              talent_id: Optional[int] = None, build,
              media_token: str = "", media_kind: str = "k") -> Optional[dict]:
    """THE engagement, shaped for one role.

    ``build`` is the existing per-project builder (``creator_routes._room_for_project``)
    passed in rather than imported, because that module imports this one — the dependency
    runs one way. This function's whole job is the SUBTRACTION: take the full room and
    remove what this role may not have.

    ``media_token`` is the caller's own credential. Given one, every media URL in the
    finished room is rewritten to the door that credential opens (:func:`route_media`) —
    AFTER the subtraction, so a URL that was removed cannot be routed back in.
    """
    room = build(conn, project_id)
    if room is None:
        return None
    allowed = caps_for(role)
    room = dict(room)
    room["role_in_room"] = role
    room["caps"] = allowed

    if "see_pending" not in allowed:
        # The published ladder, and nothing else. Not hidden — absent.
        room["pending"] = None
    if "see_contributors" not in allowed:
        room["contributors"] = []
    if "see_captures" not in allowed:
        room["captures"] = []
    if "see_deliverable_specs" not in allowed:
        room["deliverables"] = []
    if "publish" not in allowed:
        # Whether OUR storage keeps files is a studio problem, not the buyer's and not
        # the creator's. They would be able to do nothing with it but worry.
        room["storage_warn"] = ""
    if "see_invoice" not in allowed:
        # A creator has no business with the buyer's balance, and the package is not
        # theirs to hand out.
        room["invoice_balance"] = None
        room["delivery_zip"] = None
        room["download_unlocked"] = False
    if "download_source" not in allowed:
        # The source master is the working file, not the deliverable. A client receives
        # what they signed off, in the package, once it is paid for — and the same is
        # true of the individual deliverable files a craft downloads to work from.
        room["master"] = None
        room["deliverables"] = [dict(d, files=[], waiting_files=[])
                                for d in (room.get("deliverables") or [])]
    if role == TALENT:
        # A creator is handed only what has been priced (ADR-0069).
        room["feedback"] = priced_notes_only(room.get("feedback") or {})
    if "see_internal" not in allowed:
        # Studio-side replies on a client note are internal by definition.
        fb = dict(room.get("feedback") or {})
        for key in ("notes", "archive"):
            fb[key] = [
                dict(n, replies=[r for r in (n.get("replies") or [])
                                 if not r.get("internal")])
                for n in (fb.get(key) or [])
            ]
        room["feedback"] = fb
    if "see_who" not in allowed:
        # AUTHORSHIP. The note stays — a client must read what the studio said back to
        # them — but it is signed by the studio. Rewritten here rather than in the
        # template for the same reason as everything above it: a template that forgets
        # an `{% if %}` should leak nothing.
        fb = dict(room.get("feedback") or {})
        for key in ("notes", "archive"):
            fb[key] = [
                dict(n,
                     author=attribute(role, n.get("author_role"), n.get("author") or ""),
                     replies=[dict(r, author=attribute(role, r.get("author_role"),
                                                       r.get("author") or ""))
                              for r in (n.get("replies") or [])])
                for n in (fb.get(key) or [])
            ]
        room["feedback"] = fb
        # And the take's provenance. `from_creator` names the composer on every row of
        # the version ladder. No client-facing template reads it TODAY — this closes it
        # before one does, because the next person adding a "delivered by" line to the
        # Takes sheet will find the name already sitting in the dict.
        room["versions"] = [dict(v, from_creator="") for v in (room.get("versions") or [])]
    if media_token:
        # Last, and deliberately: subtract first, then route what survived. Routing
        # before the subtraction would mint a working client URL for a take the client
        # is not allowed to have.
        room = route_media(room, project_id, media_token, media_kind)
    return room
