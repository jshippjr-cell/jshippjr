"""The supply side — the creator roster and what they get paid.

ADR-0044, third slice. `/talent` (11 routes) and `/payouts` (4): the console's own
**Supply** nav section, minus the Match Board, which reaches into the opportunity
helpers and waits for that pass.

Both groups turned out to be **contiguous blocks** — `/talent` at one place in the file
and `/payouts` at another. An earlier note in this project called them "scattered across
4,000 lines"; that was the *gap between* the two groups, not scatter within them, and the
correction is why this pass was a straightforward cut rather than the fiddly gather it
was billed as.

The rate helpers came too. `_parse_rate` and `_clean_rate_unit` were defined inside the
talent block, and `_parse_rate` is also used by `/opportunity` and `/proposal` — so
`app.py` imports it back from here, the same direction `_profile_from_row` travels in
`agencies_routes.py`. `app.py` → route module → `shell.py`, never the reverse.
"""

from __future__ import annotations

from typing import List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from .. import composer_agreement, mailer, recruiting, signing
from ..models import MusicDiscipline
from ..talent import Talent, normalize_url, profile_completeness
from . import actor, db
from .shell import public_base as _public_base, render, safe_local as _safe_local

router = APIRouter(tags=["talent"])


# Disciplines offered in talent forms (exclude the disqualified NON_CRAFT bucket).
FORM_DISCIPLINES = [d for d in MusicDiscipline if d is not MusicDiscipline.NON_CRAFT]

_SOURCE_CHANNELS = ["applied", "sourced", "referral", "manual"]


@router.get("/talent", response_class=HTMLResponse)
def talent_roster(
    request: Request,
    discipline: Optional[str] = None,
    review: Optional[str] = None,
    invite: Optional[str] = None,
    source: Optional[str] = None,
    sort: str = "name",
):
    conn = db.connect()
    try:
        rows = db.list_talent(conn, discipline=discipline, review=review, invite=invite)
        talents = [db.talent_from_row(r) for r in rows]
        # The reel-review queue is the gate only Jon can clear — show every
        # pending creator regardless of the current filter, with completeness.
        review_queue = [
            {"t": t, "completeness": profile_completeness(t)}
            for t in (db.talent_from_row(r) for r in db.list_talent(conn, review="Pending"))
        ]
        # Roster-wide counts (independent of the active filter).
        all_talents = [db.talent_from_row(r) for r in db.list_talent(conn)]
    finally:
        conn.close()
    # Origin-channel filter (applied | sourced | referral | manual) — answers
    # "where's my sourced channel?" by making each intake lane visible/filterable.
    if source in _SOURCE_CHANNELS:
        talents = [t for t in talents if t.source_channel == source]
    cards = [{"t": t, "completeness": profile_completeness(t)} for t in talents]
    sorters = {
        "name": lambda c: c["t"].name.lower(),
        "completeness": lambda c: -c["completeness"],
        "matchable": lambda c: (not c["t"].matchable, -c["completeness"]),
        "discipline": lambda c: (c["t"].discipline_labels[0] if c["t"].discipline_labels else "~"),
    }
    cards.sort(key=sorters.get(sort, sorters["name"]))
    counts = {
        "total": len(all_talents),
        "approved": sum(1 for t in all_talents if t.is_approved),
        "pending": sum(1 for t in all_talents if t.review_status.value == "Pending"),
        "matchable": sum(1 for t in all_talents if t.matchable),
        "sourced": sum(1 for t in all_talents if t.source_channel == "sourced"),
    }
    active = {
        "discipline": discipline or "", "review": review or "",
        "invite": invite or "", "source": source if source in _SOURCE_CHANNELS else "",
        "sort": sort,
    }
    return render(
        request, "talent_roster.html", nav="talent", cards=cards, counts=counts,
        disciplines=FORM_DISCIPLINES, review_states=db.REVIEW_STATES,
        invite_states=db.INVITE_STATES, source_channels=_SOURCE_CHANNELS,
        active=active, review_queue=review_queue,
    )


_ADD_SOURCES = {"manual", "sourced", "referral"}


@router.get("/talent/new", response_class=HTMLResponse)
def talent_new(request: Request, source: str = "manual"):
    # ?source=sourced renders the "log a candidate I found myself" variant — the
    # human-in-the-loop workaround for bot-blocked sites: browse the site in your
    # own signed-in browser, then log the worth-reviewing creators here.
    preset = source if source in _ADD_SOURCES else "manual"
    return render(
        request, "talent_form.html", nav="talent", talent=None,
        disciplines=FORM_DISCIPLINES, source_preset=preset,
    )


_RATE_UNITS = {"hourly", "day", "project"}


def _clean_rate_unit(unit: str) -> str:
    unit = (unit or "hourly").strip().lower()
    return unit if unit in _RATE_UNITS else "hourly"


def _parse_rate(raw: str) -> Optional[float]:
    """Blank rate → None (no rate set); otherwise a float, ignoring bad input."""
    raw = (raw or "").strip().replace("$", "").replace(",", "")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


@router.post("/talent")
def talent_create(
    name: str = Form(...),
    email: str = Form(""),
    disciplines: List[str] = Form([]),
    credits: str = Form(""),
    location: str = Form(""),
    demo_reel_url: str = Form(""),
    notes: str = Form(""),
    rate: str = Form(""),
    rate_unit: str = Form("hourly"),
    source: str = Form("manual"),
):
    valid = [MusicDiscipline(d) for d in disciplines if d in {m.value for m in MusicDiscipline}]
    origin = source if source in _ADD_SOURCES else "manual"
    reel_url = normalize_url(demo_reel_url)
    t = Talent(
        name=name.strip(), email=email.strip() or None, disciplines=valid,
        credits=credits.strip(), location=location.strip() or None,
        demo_reel_url=reel_url, notes=notes.strip(),
        rate=_parse_rate(rate), rate_unit=_clean_rate_unit(rate_unit),
        source=origin, source_url=reel_url,
    )
    conn = db.connect()
    try:
        new_id = db.insert_talent(conn, t)
    finally:
        conn.close()
    return RedirectResponse(f"/talent/{new_id}", status_code=303)


@router.get("/talent/{talent_id}", response_class=HTMLResponse)
def talent_detail(request: Request, talent_id: int, invite: str = "", agr: str = ""):
    invite_result = invite  # ?invite=<send-status> flash; renamed to avoid shadowing
    conn = db.connect()
    try:
        row = db.get_talent(conn, talent_id)
        if row is None:
            return HTMLResponse("Talent not found", status_code=404)
        t = db.talent_from_row(row)
        portal_token = row["portal_token"] if "portal_token" in row.keys() else None
        w9_at = row["w9_received_at"] if "w9_received_at" in row.keys() else None
        agreement_at = (row["agreement_executed_at"]
                        if "agreement_executed_at" in row.keys() else None)
        agreement_ref = (row["agreement_ref"]
                         if "agreement_ref" in row.keys() else "") or ""
        assignment_blockers = db.talent_assignment_blockers(row)
        # The signed agreement itself, not just the date someone typed about one.
        # NOT named `agr` — that is the query parameter carrying the send status, and a
        # local of the same name shadowed it, so the page rendered a dataclass repr where
        # the operator expected "sent to dale@example.com".
        _agreement = composer_agreement.build_agreement(row)
        agreement_text = _agreement.signable_text()
        composer_sig = db.latest_talent_signature(
            conn, talent_id, signing.DOC_COMPOSER_AGREEMENT)
        composer_counter = db.latest_talent_signature(
            conn, talent_id, signing.DOC_COMPOSER_COUNTERSIGN)
    finally:
        conn.close()
    sig_state = signing.verify(
        composer_sig["digest"] if composer_sig is not None else "", agreement_text)
    portal_url = f"{_public_base()}/creator/{portal_token}" if portal_token else None
    # Recruiting composer: a personalized, deterministic invite draft Jon can copy,
    # edit, and send to a prospect (machine proposes, Jon disposes).
    base = _public_base()
    invite = recruiting.compose_invite(
        t, apply_url=f"{base}/apply", artists_url=f"{base}/for-artists")
    return render(
        request, "talent_detail.html", nav="talent", t=t,
        completeness=profile_completeness(t), disciplines=FORM_DISCIPLINES,
        review_states=db.REVIEW_STATES, invite_states=db.INVITE_STATES,
        portal_token=portal_token, portal_url=portal_url, w9_received_at=w9_at,
        agreement_executed_at=agreement_at, agreement_ref=agreement_ref,
        assignment_blockers=assignment_blockers,
        agreement_text=agreement_text, composer_sig=composer_sig,
        composer_counter=composer_counter,
        composer_sig_note=signing.verdict_note(
            sig_state, dict(composer_sig) if composer_sig is not None else None),
        composer_sig_valid=(sig_state == signing.VALID),
        invite=invite, mail_configured=mailer.mail_configured(),
        invite_result=invite_result, agr_result=agr,
    )


@router.post("/talent/{talent_id}")
def talent_edit(
    talent_id: int,
    name: str = Form(...),
    email: str = Form(""),
    disciplines: List[str] = Form([]),
    credits: str = Form(""),
    location: str = Form(""),
    demo_reel_url: str = Form(""),
    notes: str = Form(""),
    rate: str = Form(""),
    rate_unit: str = Form("hourly"),
    pro: str = Form(""),
    publisher: str = Form(""),
):
    conn = db.connect()
    try:
        db.update_talent_profile(
            conn, talent_id, name.strip(), email, disciplines, credits.strip(),
            location, normalize_url(demo_reel_url) or "", notes.strip(),
            rate=_parse_rate(rate), rate_unit=_clean_rate_unit(rate_unit),
            pro=pro, publisher=publisher,
        )
    finally:
        conn.close()
    return RedirectResponse(f"/talent/{talent_id}", status_code=303)


@router.post("/talent/{talent_id}/delete")
def talent_delete(talent_id: int):
    """Remove a creator from the roster permanently — chiefly for clearing demo rows.

    Refuses, with a reason, when the delete would leave a real record pointing at
    nobody: an assignment on a live project, or a signature. See
    ``db.talent_delete_block`` — the refusals are the feature, not obstacles to it.
    """
    conn = db.connect()
    try:
        out = db.delete_talent(conn, talent_id)
    finally:
        conn.close()
    if out["deleted"]:
        return RedirectResponse(f"/talent?removed={quote(out['name'] or 'creator')}",
                                status_code=303)
    if out["reason"] == "missing":
        return RedirectResponse("/talent", status_code=303)
    return RedirectResponse(f"/talent/{talent_id}?delete={out['reason']}",
                            status_code=303)


@router.post("/talent/{talent_id}/review")
def talent_review(talent_id: int, review_status: str = Form(...), return_to: str = Form("")):
    """The reel-review verdict. An applicant left hearing nothing after
    applying is the exact gap reported live — a real transition INTO
    Approved or Declined (never a re-click of the state it's already in)
    emails them the outcome, with role/rate for an acceptance."""
    conn = db.connect()
    try:
        before = db.get_talent(conn, talent_id)
        was = before["review_status"] if before is not None else None
        db.update_talent_review(conn, talent_id, review_status)
        t = db.talent_from_row(db.get_talent(conn, talent_id)) if before is not None else None
    finally:
        conn.close()
    if (
        t is not None and was != review_status
        and review_status in ("Approved", "Declined")
        and t.email and mailer.mail_configured()
    ):
        base = _public_base()
        dec = recruiting.compose_review_decision(
            t, accepted=(review_status == "Approved"), artists_url=f"{base}/for-artists",
        )
        mailer.send_email(
            t.email, dec["subject"], dec["body"], html=mailer.branded_html(base, dec["body"]),
        )
    return RedirectResponse(
        _safe_local(return_to, f"/talent/{talent_id}"), status_code=303
    )


@router.post("/talent/{talent_id}/invite")
def talent_invite(talent_id: int, invite_status: str = Form(...)):
    conn = db.connect()
    try:
        db.update_talent_invite(conn, talent_id, invite_status)
    finally:
        conn.close()
    return RedirectResponse(f"/talent/{talent_id}", status_code=303)


@router.post("/talent/{talent_id}/invite/send")
def talent_send_invite(talent_id: int):
    """Email the personalized recruiting invite to the creator and advance them to
    Invited. Falls back gracefully: with no email on file or mail unconfigured, it
    just flags 'copy it manually' (the draft is always on the page)."""
    conn = db.connect()
    try:
        row = db.get_talent(conn, talent_id)
        if row is None:
            return RedirectResponse("/talent", status_code=303)
        t = db.talent_from_row(row)
    finally:
        conn.close()
    email = (t.email or "").strip()
    if not email or not mailer.mail_configured():
        return RedirectResponse(f"/talent/{talent_id}?invite=manual#invite", status_code=303)
    base = _public_base()
    inv = recruiting.compose_invite(
        t, apply_url=f"{base}/apply", artists_url=f"{base}/for-artists")
    status = mailer.send_email(
        email, inv["subject"], inv["body"],
        html=mailer.branded_html(base, inv["body"]),
    )
    if status == "sent":
        conn = db.connect()
        try:
            db.update_talent_invite(conn, talent_id, "Invited")  # funnel advances
        finally:
            conn.close()
    return RedirectResponse(f"/talent/{talent_id}?invite={status}#invite", status_code=303)


@router.post("/talent/{talent_id}/portal")
def talent_issue_portal(talent_id: int):
    """Mint (or reveal) the creator's portal access token — their only credential
    for /creator/<token>. Jon issues this when a creator is qualified, then sends
    them the link. Idempotent: re-issuing returns the same token. If mail is
    configured and the creator has an email, also send them the link (best-effort)."""
    conn = db.connect()
    try:
        token = db.ensure_talent_portal_token(conn, talent_id)
        row = db.get_talent(conn, talent_id)
        email = (row["email"] or "").strip() if row is not None else ""
    finally:
        conn.close()
    if token and email and mailer.mail_configured():
        url = f"{_public_base()}/creator/{token}"
        mailer.send_email(
            email, "Your Chordential creator workspace",
            "You're set up in Chordential. Your personal workspace — where you'll see "
            f"assigned briefs and submit your work — is here:\n\n{url}\n\n"
            "It's private to you; no password needed. — Chordential")
    return RedirectResponse(f"/talent/{talent_id}#access", status_code=303)


@router.post("/talent/{talent_id}/w9")
def talent_set_w9(talent_id: int, received: str = Form("")):
    """Record/clear the creator's W-9-on-file date (the payout-ledger gate)."""
    from datetime import date as _date
    conn = db.connect()
    try:
        db.set_talent_w9(conn, talent_id,
                         _date.today().isoformat() if received == "1" else None)
    finally:
        conn.close()
    return RedirectResponse(f"/talent/{talent_id}#access", status_code=303)


@router.post("/talent/{talent_id}/agreement/send")
def talent_send_agreement(talent_id: int):
    """Email the composer their agreement. We have their address — asking the operator to
    copy a link out of the page and paste it into a mail client was work the product was
    supposed to remove, and it is the step where "I'll do it later" happens.

    Mints the portal token if there isn't one, so sending is a single decision rather
    than a two-step ritual: issue a link, then remember to send it.
    """
    conn = db.connect()
    try:
        row = db.get_talent(conn, talent_id)
        if row is None:
            return RedirectResponse("/talent", status_code=303)
        name = (row["name"] or "").strip()
        email = ((row["email"] if "email" in row.keys() else "") or "").strip()
        already = db.latest_talent_signature(
            conn, talent_id, signing.DOC_COMPOSER_AGREEMENT) is not None
        token = db.ensure_talent_portal_token(conn, talent_id)
    finally:
        conn.close()
    if already:
        return RedirectResponse(f"/talent/{talent_id}#access", status_code=303)
    if not email or not mailer.mail_configured() or not token:
        # No address or no mail provider → say so; the link is on the page to copy.
        return RedirectResponse(f"/talent/{talent_id}?agr=manual#access", status_code=303)
    base = _public_base()
    url = f"{base}/creator/{token}/agreement"
    first = (name.split(" ")[0] if name else "there")
    body = (
        f"Hi {first},\n\n"
        f"Before we can put you on paid work, we need our Composer Agreement signed. "
        f"It's the standing terms — what you're paid, what you keep, and what you "
        f"warrant about the music.\n\n"
        f"Read and sign it here:\n{url}\n\n"
        f"Two things worth knowing before you open it. It commits you to no work and "
        f"guarantees you none — every engagement is offered and accepted separately. "
        f"And you keep 100% of your writer's share, plus half the publisher's share, "
        f"which is better than most houses will offer you.\n\n"
        f"It takes about five minutes. Any questions, just reply to this.\n\n"
        f"— Chordential"
    )
    status = mailer.send_email(email, "Your Composer Agreement — Chordential", body,
                               html=mailer.branded_html(base, body))
    return RedirectResponse(f"/talent/{talent_id}?agr={status}#access", status_code=303)


@router.post("/talent/{talent_id}/agreement/countersign")
def talent_countersign_agreement(request: Request, talent_id: int,
                                 typed_name: str = Form("")):
    """The studio's half of the Composer Agreement.

    Refused before the writer has signed, and refused once the document has MOVED since
    they signed it — the same two rules the client proposal's countersignature follows.
    Countersigning a text they never read would leave the two parties bound to different
    documents, which is precisely what the digest exists to catch.
    """
    who = actor.identify(request).get("label", "") or ""
    conn = db.connect()
    try:
        row = db.get_talent(conn, talent_id)
        if row is None:
            return HTMLResponse("Talent not found", status_code=404)
        theirs = db.latest_talent_signature(
            conn, talent_id, signing.DOC_COMPOSER_AGREEMENT)
        if theirs is None:
            return RedirectResponse(f"/talent/{talent_id}?flag=not-signed#access",
                                    status_code=303)
        if db.latest_talent_signature(
                conn, talent_id, signing.DOC_COMPOSER_COUNTERSIGN) is not None:
            return RedirectResponse(f"/talent/{talent_id}#access", status_code=303)
        text = composer_agreement.build_agreement(row).signable_text()
        if signing.verify(theirs["digest"], text) != signing.VALID:
            return RedirectResponse(f"/talent/{talent_id}?flag=superseded#access",
                                    status_code=303)
        try:
            sig = signing.build_signature(
                doc_kind=signing.DOC_COMPOSER_COUNTERSIGN,
                talent_id=talent_id,
                document_text=text,
                signer_name=who or "Chordential",
                typed_name=(typed_name.strip() or who or "Chordential"),
                actor=who,
                ip=(request.client.host if request.client else ""),
                user_agent=request.headers.get("user-agent", ""),
                terms_snapshot={"countersigns": theirs["digest"]},
            )
        except ValueError as exc:
            return HTMLResponse(str(exc), status_code=400)
        db.record_signature(conn, sig)
    finally:
        conn.close()
    return RedirectResponse(f"/talent/{talent_id}#access", status_code=303)


@router.post("/talent/{talent_id}/agreement")
def talent_set_agreement(talent_id: int, executed: str = Form(""), ref: str = Form("")):
    """Record/clear the standing Composer Agreement (ADR-0024) — the assignment
    gate's other half alongside the rate. Recording stamps today; clearing wipes
    both date and ref."""
    from datetime import date as _date
    conn = db.connect()
    try:
        db.set_talent_agreement(
            conn, talent_id,
            _date.today().isoformat() if executed == "1" else None, ref)
    finally:
        conn.close()
    return RedirectResponse(f"/talent/{talent_id}#access", status_code=303)


# --------------------------------------------------------------------------- #
# Composer portal — a qualified creator's token-gated home. NOT admin-gated;
# the per-creator portal token IS the credential (same model as the client
# delivery portal). They see their assigned briefs and submit work versions.
# --------------------------------------------------------------------------- #
@router.get("/payouts", response_class=HTMLResponse)
def payouts_ledger(request: Request, err: str = "", paid: str = ""):
    conn = db.connect()
    try:
        owed = db.list_payouts(conn, status="Owed")
        done = db.list_payouts(conn, status="Paid")
        totals = db.payout_totals(conn)
    finally:
        conn.close()
    return render(
        request, "payouts.html", nav="payouts", owed=owed, done=done,
        totals=totals, err=err, paid_id=paid,
    )


@router.post("/payouts/{payout_id}")
def payout_update(
    payout_id: int,
    qty: str = Form(""),
    amount: str = Form(""),
    reference: str = Form(""),
):
    """Edit an Owed payout's hours/days, amount, and payment reference."""
    conn = db.connect()
    try:
        db.update_payout(conn, payout_id, _parse_rate(qty), _parse_rate(amount),
                         reference.strip())
    finally:
        conn.close()
    return RedirectResponse("/payouts", status_code=303)


@router.post("/payouts/{payout_id}/pay")
def payout_pay(payout_id: int, reference: str = Form("")):
    """Mark a payout Paid — GATED on a W-9 being on file for the creator.

    The ledger never moves money; Jon pays off-platform and records it here. The
    W-9 gate is the compliance discipline the council required before a first payout."""
    conn = db.connect()
    try:
        po = db.get_payout(conn, payout_id)
        if po is None:
            return RedirectResponse("/payouts", status_code=303)
        w9 = po["w9_received_at"] if "w9_received_at" in po.keys() else None
        if not w9:
            # Block: surface which creator needs a W-9 first.
            return RedirectResponse(
                f"/payouts?err=w9&paid={payout_id}", status_code=303)
        db.set_payout_paid(conn, payout_id, True, reference.strip())
    finally:
        conn.close()
    return RedirectResponse("/payouts", status_code=303)


@router.post("/payouts/{payout_id}/unpay")
def payout_unpay(payout_id: int):
    """Revert a payout to Owed (correct a mistaken mark-paid)."""
    conn = db.connect()
    try:
        db.set_payout_paid(conn, payout_id, False)
    finally:
        conn.close()
    return RedirectResponse("/payouts", status_code=303)


# --------------------------------------------------------------------------- #
# Discovery Call Simulator — practice against buyer personas; the objection
# library learns from real transcripts (see simulator.py). Admin-gated.
# --------------------------------------------------------------------------- #
