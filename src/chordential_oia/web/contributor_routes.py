"""The session player's release — the one surface nobody in this system has an account for.

`/contributor/{token}` and its sign POST. Separate from `creator_routes` because a
contributor is not a creator: they have no portal, no assignments, no profile, and no
reason to ever come back. The tripwire in `test_app_structure` caught them living under
the wrong router, which is exactly the signal it exists to give.

Their token IS the credential (the same model as the client workspace and the composer
portal), so both paths are exempt from the admin gate in `app._CONTRIBUTOR_RE` and each
route validates the token itself.
"""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import contributor_release, signing
from . import db
from .creator_routes import _mail_signed_copy
from .shell import render

router = APIRouter(tags=["contributor"])


@router.get("/contributor/{token}", response_class=HTMLResponse)
def contributor_page(request: Request, token: str):
    """One session player's release. Their token IS the credential — they have no
    account here and never will."""
    conn = db.connect()
    try:
        row = db.contributor_by_token(conn, token)
        if row is None:
            return HTMLResponse("Not found", status_code=404)
        sig = db.latest_contributor_signature(
            conn, row["id"], signing.DOC_CONTRIBUTOR_RELEASE)
        rel = contributor_release.build_release(row)
    finally:
        conn.close()
    text = rel.signable_text()
    state = signing.verify(sig["digest"] if sig is not None else "", text)
    return render(
        request, "contributor_release.html", nav="", token=token, release=rel,
        release_text=text, signature=sig,
        signature_note=signing.verdict_note(state, dict(sig) if sig is not None else None),
        signature_valid=(state == signing.VALID),
        sign_url=f"/contributor/{token}/sign" if state != signing.VALID else "",
        acceptance_text=contributor_release.ACCEPTANCE_TEXT,
        consent_text=signing.CONSENT_TEXT,
    )


@router.post("/contributor/{token}/sign")
def contributor_sign(request: Request, token: str, typed_name: str = Form(""),
                     signer_email: str = Form(""), consent: str = Form(""),
                     drawn_signature: str = Form("")):
    """They sign. Same machinery as everyone else — one deterministic text, a digest of
    exactly what they read, an optional drawn mark."""
    conn = db.connect()
    try:
        row = db.contributor_by_token(conn, token)
        if row is None:
            return HTMLResponse("Not found", status_code=404)
        if not consent.strip() or not typed_name.strip():
            return RedirectResponse(f"/contributor/{token}?flag=incomplete",
                                    status_code=303)
        rel = contributor_release.build_release(row)
        text = rel.signable_text()
        prior = db.latest_contributor_signature(
            conn, row["id"], signing.DOC_CONTRIBUTOR_RELEASE)
        if prior is not None and signing.verify(
                prior["digest"], text) == signing.VALID:
            return RedirectResponse(f"/contributor/{token}", status_code=303)
        try:
            sig = signing.build_signature(
                doc_kind=signing.DOC_CONTRIBUTOR_RELEASE,
                contributor_id=row["id"],
                project_id=row["project_id"],
                document_text=text,
                signer_name=(row["name"] or "").strip(),
                signer_email=(signer_email.strip() or (row["email"] or "")),
                typed_name=typed_name.strip(),
                ip=(request.client.host if request.client else ""),
                user_agent=request.headers.get("user-agent", ""),
                token=token,
                drawn_mark=drawn_signature,
                certified_version=rel.version,
                terms_snapshot={"role": rel.role, "work": rel.work},
            )
        except ValueError as exc:
            return HTMLResponse(str(exc), status_code=400)
        db.record_signature(conn, sig)
        signer_mail = sig.signer_email
    finally:
        conn.close()
    _mail_signed_copy(signer_mail, sig, text, row_name=sig.signer_name)
    return RedirectResponse(f"/contributor/{token}", status_code=303)
