"""The writer's half of the chain of title, signed rather than asserted.

Reported live: *"Where do I find the composer agreement in the talent section?"* — and
the answer was that there wasn't one. `talent.agreement_executed_at` was a date an
operator typed to record that an agreement existed *somewhere else*, and `agreement_ref`
was free text for where the paper lived. The assignment gate (ADR-0024) turned on a
checkbox about a document the system had never seen.

That is a weak spot in the thing this business sells. The Clearance Certificate warrants
to a BUYER that the work is "100% original & cleared: no samples, no third-party masters"
— and the only thing that can make that true is the writer having warranted it first. A
certificate whose backing is a tickbox is backed by a memory of a conversation.

So the composer signs the way the client does (ADR-0059/0065): one deterministic text, a
digest of exactly what they read, an optional drawn mark, a countersignature — and the
signature IS the gate.
"""
import importlib

import pytest

from chordential_oia import compensation, composer_agreement
from chordential_oia.signing import (
    DOC_COMPOSER_AGREEMENT, DOC_COMPOSER_COUNTERSIGN, document_digest,
)

pytest.importorskip("fastapi")


# ── the document says what the engine says ───────────────────────────────────────────
LAW = "the State of Tennessee"


def _agr(name=None):
    return composer_agreement.build_agreement(
        {"name": name} if name else None, law=LAW)


def test_every_number_comes_from_policy_not_from_prose():
    """If a term here and a number in `compensation` disagree, the engine is right and
    this document is a bug — so the figures are READ from it (ADR-0061)."""
    text = _agr().signable_text()
    assert f"{compensation.COMPOSER_SHARE * 100:.0f}%" in text
    assert f"{compensation.COMPOSER_SHARE_WITH_SESSION * 100:.0f}%" in text
    assert f"${compensation.DEMO_FEE:,.0f}" in text
    assert compensation.HOUSE_PUBLISHER in text


def test_it_grants_the_composition_and_not_only_the_recording():
    """The finding that failed v1.0, and the one that mattered most.

    Clause 4 assigned "the master recording". Clause 5 SAID the publisher's share "is
    held by Chordential Music" — indicative mood, no verb of grant, nothing transferred.
    Meanwhile `delivery.DEFAULT_LICENSE` sells every client a perpetual SYNC licence,
    which is a licence of the COMPOSITION. We were licensing a copyright we did not own,
    under a certificate warranting clean title, while the writer stayed free to license
    the same cue to a competitor.
    """
    text = _agr().signable_text()
    assert "assigns to Chordential Music the whole of the copyright in the composition" \
        in text, "the composition is still not granted"
    assert "assigns to the studio" in text, "the master grant lost its verb"
    # And the master grant now has scope words — an assignment of unstated interest,
    # territory, term and media is not an assignment of anything checkable.
    for word in ("full term of copyright", "throughout the world",
                 "all media now known or later invented"):
        assert word in text


def test_the_writer_keeps_performance_income_and_half_the_publisher_share():
    text = _agr().signable_text()
    assert "writer keeps the writer's share of public performance income" in text
    assert "50% of the publisher's share belongs to the writers" in text
    # The condition the CODE enforces must appear in the document the writer signs:
    # `publisher_rows` gives them nothing without a registered entity, and v1.0 promised
    # "50/50" unconditionally. That gap is a clean misrepresentation argument.
    assert "holds that half FOR the writer" in text
    assert "does not keep it by default and does not keep it by silence" in text


def test_it_warrants_the_music_is_human_made():
    """The entire market positioning — "never AI-generated" in the outreach copy — was
    unwarranted anywhere. And it is a validity gate, not hygiene: AI-generated material
    is uncopyrightable, so there is nothing to assign and nothing to certify."""
    text = _agr().signable_text()
    assert "created by a human being" in text
    assert "Suno" in text and "Udio" in text
    assert "not owned by anybody under US copyright law" in text
    # Ordinary studio tools must stay allowed or no working composer can sign it.
    assert "pitch correction" in text and "AI-assisted mastering" in text


def test_it_captures_everyone_else_who_played():
    """Chain of title is a graph. A composer who books a violinist creates a rights
    holder the studio has never heard of — and in the UK performers' rights are a
    separate property right the composer cannot assign on their behalf."""
    text = _agr().signable_text()
    assert "contributor release" in text
    assert "singers, session players" in text
    assert "AFM" in text and "SAG-AFTRA" in text, "union exposure is unaddressed"


def test_the_library_warranty_is_one_a_working_composer_can_sign():
    """v1.0 banned "library material" outright, which no composer using Kontakt or
    Spitfire can honestly sign — and was silent on the actual risk, which is delivering
    a solo stem of a licensed patch."""
    text = _agr().signable_text()
    assert "Licensed virtual instruments and sample libraries are fine" in text
    assert "heard on its own" in text, "the stems risk is what the EULA turns on"
    assert "Telling the studio honestly is never itself a breach" in text


def test_the_warranty_is_backed_by_a_capped_indemnity():
    text = _agr().signable_text()
    assert "cover the studio's reasonable, documented losses" in text
    assert "$25,000" in text and "3 times the fees" in text
    assert "does not apply where the writer knew the warranty was untrue" in text
    assert "seven years" in text, "no evidence retention — the files win the dispute"


def test_payment_has_a_date_the_composer_can_rely_on():
    """Pay-when-paid with no backstop was the clearest below-market term: if the client
    never paid, the composer never got paid, ever."""
    text = _agr().signable_text()
    assert "within 120 days of the client accepting delivery, whether or not the " \
        "client has paid" in text
    assert "the writer is paid as though it had" in text, "no duty to invoice"


def test_the_composer_shares_licence_and_renewal_income():
    """The fee base is the CREATIVE fee — so the licence fee, which is consideration for
    exclusivity and term the writer assigned, needs its own share or they get nothing
    when a client extends."""
    text = _agr().signable_text()
    assert "It does not include the licence fee" in text, "the base is still ambiguous"
    assert "extend the term, widen the territory, add media" in text
    assert "for as long as the work earns" in text


def test_it_has_the_furniture_a_contract_needs():
    text = _agr().signable_text()
    for clause in ("waives their moral rights", "independent contractor",
                   "governed by the law of", "unenforceable, the rest still stands",
                   "showreel", "materially similar cue for a competing brand"):
        assert clause in text, f"missing: {clause}"


def test_credit_is_a_promise_the_studio_can_actually_keep():
    """v1.0 promised the client would credit the composer — an obligation performable
    only by a third party the studio does not control."""
    text = _agr().signable_text()
    assert "a promise to ask, not a promise that it happens" in text
    assert "credits the writer as composer on the cue sheet it files, every time" in text


def test_it_refuses_to_be_signed_without_a_governing_law():
    """No honest default exists — inventing a jurisdiction for a document someone signs
    is the same class of error as inventing a price. So it refuses rather than degrading,
    the rule `signing_providers` already follows."""
    blank = composer_agreement.build_agreement({"name": "Dale"}, law="")
    assert not composer_agreement.is_signable(blank)
    assert "CHORDENTIAL_GOVERNING_LAW" in composer_agreement.blocked_reason(blank)
    assert composer_agreement.is_signable(_agr())


def test_survival_includes_the_duty_to_pay():
    """v1.0 survived clauses 4, 5, 6 and 8 — the rights assignment survived termination
    and the duty to PAY for it did not."""
    text = _agr().signable_text()
    survival = text.split("9. ENDING IT")[1].split("10.")[0]
    for clause in ("3,", "3B", "3C", "10", "11"):
        assert clause in survival
    assert "Clause 5 survives for the life of copyright" in text


def test_it_says_plainly_that_it_books_no_work():
    """A composer reading "agreement" reasonably assumes it commits them to a job. It
    does not, and saying so is cheaper than the conversation where they find out."""
    assert "not a booking" in composer_agreement.ACCEPTANCE_LIMITS
    assert "guarantees you none" in composer_agreement.ACCEPTANCE_LIMITS


def test_the_document_is_deterministic():
    """A digest is worth nothing over a text that rebuilds differently."""
    a = _agr().signable_text()
    b = _agr().signable_text()
    assert a == b and document_digest(a) == document_digest(b)


def test_a_named_writer_appears_in_their_own_agreement():
    assert "Dale Malleh" in _agr("Dale Malleh").signable_text()
    assert _agr().signable_text().count("the writer") >= 1


# ── the writer signs it, on their own token-gated page ───────────────────────────────
@pytest.fixture()
def gated(tmp_path, monkeypatch):
    """The admin gate ON — the configuration where a missing exemption bounces a
    composer to the internal login on their own page."""
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "ca.db"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "passphrase")
    monkeypatch.setenv("CHORDENTIAL_GOVERNING_LAW", "the State of Tennessee")
    for m in ("db", "campaigns", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod
    with TestClient(app_mod.app) as c:
        yield c, app_mod


def _writer(app_mod, name="Dale Malleh"):
    from chordential_oia.models import MusicDiscipline
    from chordential_oia.talent import Talent
    db = app_mod.db
    conn = db.connect()
    try:
        tid = db.insert_talent(conn, Talent(name=name, email="dale@example.com",
                                            disciplines=[MusicDiscipline.COMPOSITION]))
        return tid, db.ensure_talent_portal_token(conn, tid)
    finally:
        conn.close()


def _as_operator(c):
    """The operator pages are gated (that is the point of the fixture) — sign in."""
    c.post("/admin/login", data={"email": "", "password": "passphrase"},
           follow_redirects=False)
    return c


def _sign(c, token, name="Dale Malleh", **extra):
    data = {"typed_name": name, "signer_email": "dale@example.com", "consent": "1"}
    data.update(extra)
    return c.post(f"/creator/{token}/agreement/sign", data=data, follow_redirects=False)


def test_the_composer_reads_and_signs_without_meeting_the_login(gated):
    """The bug that bit a client at exactly this moment: the GET was exempt from the
    admin gate and the POST was not, so the page rendered and the button bounced them to
    "Procurement OS — internal"."""
    c, app_mod = gated
    tid, token = _writer(app_mod)
    page = c.get(f"/creator/{token}/agreement")
    assert page.status_code == 200
    assert "Password or passphrase" not in page.text
    assert "COMPOSER AGREEMENT" in page.text

    r = _sign(c, token)
    assert r.status_code == 303
    assert "/admin/login" not in r.headers.get("location", "")
    conn = app_mod.db.connect()
    try:
        sig = app_mod.db.latest_talent_signature(conn, tid, DOC_COMPOSER_AGREEMENT)
    finally:
        conn.close()
    assert sig is not None and sig["typed_name"] == "Dale Malleh"


def test_the_signature_is_bound_to_the_text_they_read(gated):
    c, app_mod = gated
    tid, token = _writer(app_mod)
    _sign(c, token)
    conn = app_mod.db.connect()
    try:
        row = app_mod.db.get_talent(conn, tid)
        sig = app_mod.db.latest_talent_signature(conn, tid, DOC_COMPOSER_AGREEMENT)
    finally:
        conn.close()
    assert sig["digest"] == document_digest(
        composer_agreement.build_agreement(row, law=LAW).signable_text())


def test_signing_is_the_assignment_gate(gated):
    """ADR-0024's gate used to turn on a date an operator typed. What unblocks putting
    someone on paid work is now their own signature over a text we can still produce."""
    c, app_mod = gated
    tid, token = _writer(app_mod)
    conn = app_mod.db.connect()
    try:
        before = app_mod.db.talent_assignment_blockers(app_mod.db.get_talent(conn, tid))
    finally:
        conn.close()
    assert "agreement" in before
    _sign(c, token)
    conn = app_mod.db.connect()
    try:
        row = app_mod.db.get_talent(conn, tid)
    finally:
        conn.close()
    assert "agreement" not in app_mod.db.talent_assignment_blockers(row)
    assert (row["agreement_ref"] or "").startswith("Signed in portal")


def test_a_drawn_mark_is_kept_and_a_hostile_one_is_not(gated):
    import base64
    import zlib

    def png():
        raw = b"".join(b"\x00" + b"\xff\xff\xff" * 4 for _ in range(4))
        def chunk(tag, data):
            return (len(data).to_bytes(4, "big") + tag + data
                    + zlib.crc32(tag + data).to_bytes(4, "big"))
        blob = (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", (4).to_bytes(4, "big") + (4).to_bytes(4, "big")
                        + bytes([8, 2, 0, 0, 0]))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
        return "data:image/png;base64," + base64.b64encode(blob).decode()

    c, app_mod = gated
    tid, token = _writer(app_mod)
    _sign(c, token, drawn_signature=png())
    conn = app_mod.db.connect()
    try:
        assert app_mod.db.latest_talent_signature(
            conn, tid, DOC_COMPOSER_AGREEMENT)["drawn_mark"].startswith("data:image/png")
    finally:
        conn.close()

    tid2, token2 = _writer(app_mod, name="Other Writer")
    _sign(c, token2, name="Other Writer",
          drawn_signature="data:text/html;base64,PHNjcmlwdD4=")
    conn = app_mod.db.connect()
    try:
        sig = app_mod.db.latest_talent_signature(conn, tid2, DOC_COMPOSER_AGREEMENT)
    finally:
        conn.close()
    assert sig is not None, "the signature stands; only the drawing was refused"
    assert (sig["drawn_mark"] or "") == ""


def test_signing_twice_does_not_stack_signatures(gated):
    c, app_mod = gated
    tid, token = _writer(app_mod)
    _sign(c, token)
    _sign(c, token)
    conn = app_mod.db.connect()
    try:
        rows = app_mod.db.list_talent_signatures(conn, tid, DOC_COMPOSER_AGREEMENT)
    finally:
        conn.close()
    assert len(rows) == 1


def test_consent_is_required(gated):
    c, app_mod = gated
    tid, token = _writer(app_mod)
    c.post(f"/creator/{token}/agreement/sign",
           data={"typed_name": "Dale Malleh", "signer_email": "d@e.com", "consent": ""},
           follow_redirects=False)
    conn = app_mod.db.connect()
    try:
        assert app_mod.db.latest_talent_signature(
            conn, tid, DOC_COMPOSER_AGREEMENT) is None
    finally:
        conn.close()


def test_a_bad_portal_token_is_not_found(gated):
    c, _app_mod = gated
    assert c.get("/creator/nope/agreement").status_code == 404
    assert c.post("/creator/nope/agreement/sign",
                  data={"typed_name": "X", "consent": "1"},
                  follow_redirects=False).status_code == 404


# ── the operator sees it, and countersigns ───────────────────────────────────────────
def test_the_talent_page_shows_the_signed_agreement(gated):
    """The reported question, answered: it is on the talent page, and it is the document
    rather than a date about one."""
    c, app_mod = gated
    _as_operator(c)
    tid, token = _writer(app_mod)
    before = c.get(f"/talent/{tid}").text
    assert "not signed yet" in before.lower()
    assert f"/creator/{token}/agreement" in before, "the operator can send them the link"
    _sign(c, token)
    page = c.get(f"/talent/{tid}").text
    assert "Composer Agreement SIGNED" in page
    assert "Dale Malleh" in page
    assert "The signed agreement" in page and "WHAT THE WRITER WARRANTS" in page


def test_the_operator_countersigns_the_same_document(gated):
    c, app_mod = gated
    _as_operator(c)
    tid, token = _writer(app_mod)
    _sign(c, token)
    r = c.post(f"/talent/{tid}/agreement/countersign",
               data={"typed_name": "Jon Shipp"}, follow_redirects=False)
    assert r.status_code == 303
    conn = app_mod.db.connect()
    try:
        theirs = app_mod.db.latest_talent_signature(conn, tid, DOC_COMPOSER_AGREEMENT)
        ours = app_mod.db.latest_talent_signature(conn, tid, DOC_COMPOSER_COUNTERSIGN)
    finally:
        conn.close()
    assert ours is not None and ours["digest"] == theirs["digest"], (
        "the two parties signed different documents")
    assert "signed by both parties" in c.get(f"/talent/{tid}").text


def test_countersigning_is_refused_before_the_writer_signs(gated):
    c, app_mod = gated
    _as_operator(c)
    tid, _token = _writer(app_mod)
    c.post(f"/talent/{tid}/agreement/countersign", data={"typed_name": "Jon Shipp"},
           follow_redirects=False)
    conn = app_mod.db.connect()
    try:
        assert app_mod.db.latest_talent_signature(
            conn, tid, DOC_COMPOSER_COUNTERSIGN) is None
    finally:
        conn.close()


def test_the_writer_is_offered_the_agreement_on_their_own_portal(gated):
    """A document nobody can find is the same as no document."""
    c, app_mod = gated
    _tid, token = _writer(app_mod)
    page = c.get(f"/creator/{token}").text
    assert f"/creator/{token}/agreement" in page
    assert "Composer Agreement" in page


def test_the_signed_copy_reaches_both_parties(gated, monkeypatch):
    from chordential_oia import mailer
    sent = []
    monkeypatch.setenv("CHORDENTIAL_OPERATOR_EMAIL", "jon@chordential.com")
    monkeypatch.setattr(mailer, "send_email",
                        lambda to, subject, body, **kw: sent.append((to, body)))
    c, app_mod = gated
    _tid, token = _writer(app_mod)
    _sign(c, token)
    assert {t for t, _ in sent} == {"dale@example.com", "jon@chordential.com"}
    for _to, body in sent:
        assert "SIGNED COPY" in body and "COMPOSER AGREEMENT" in body
        assert "WHAT THE WRITER WARRANTS" in body
        assert len(body.split("Document digest (SHA-256): ")[1][:64].strip()) == 64


# ── sending it is one button, not a copy-paste ───────────────────────────────────────
def test_the_operator_emails_the_agreement_rather_than_pasting_a_link(gated, monkeypatch):
    """Reported: "we have the composer's email why are you requiring me to copy paste a
    link". Copying a link out of a page and into a mail client is the step where "I'll do
    it later" happens, and it is exactly the work this product exists to remove."""
    from chordential_oia import mailer
    sent = []
    monkeypatch.setattr(mailer, "mail_configured", lambda: True)
    monkeypatch.setattr(mailer, "send_email",
                        lambda to, subject, body, **kw: (sent.append((to, subject, body))
                                                         or "sent"))
    c, app_mod = gated
    _as_operator(c)
    tid, _token = _writer(app_mod)
    r = c.post(f"/talent/{tid}/agreement/send", follow_redirects=False)
    assert r.status_code == 303 and "agr=sent" in r.headers["location"]
    assert len(sent) == 1
    to, subject, body = sent[0]
    assert to == "dale@example.com"
    assert "Composer Agreement" in subject
    assert "/agreement" in body, "the mail must carry the link they sign at"
    # What a composer needs to know BEFORE opening a contract from a studio they do not
    # know: it books them nothing, and the publishing term is better than most.
    assert "commits you to no work" in body
    assert "writer's share" in body


def test_sending_mints_the_portal_link_so_it_is_one_decision(gated, monkeypatch):
    """Issue a link, then remember to send it, is two steps and one of them gets
    forgotten."""
    from chordential_oia import mailer
    monkeypatch.setattr(mailer, "mail_configured", lambda: True)
    monkeypatch.setattr(mailer, "send_email", lambda *a, **kw: "sent")
    c, app_mod = gated
    _as_operator(c)
    from chordential_oia.models import MusicDiscipline
    from chordential_oia.talent import Talent
    conn = app_mod.db.connect()
    try:
        tid = app_mod.db.insert_talent(conn, Talent(
            name="No Token Yet", email="new@example.com",
            disciplines=[MusicDiscipline.COMPOSITION]))
        assert not (app_mod.db.get_talent(conn, tid)["portal_token"] or "")
    finally:
        conn.close()
    c.post(f"/talent/{tid}/agreement/send", follow_redirects=False)
    conn = app_mod.db.connect()
    try:
        assert (app_mod.db.get_talent(conn, tid)["portal_token"] or ""), (
            "sending should mint the credential it is sending")
    finally:
        conn.close()


def test_a_composer_with_no_email_is_told_not_guessed_at(gated, monkeypatch):
    from chordential_oia import mailer
    sent = []
    monkeypatch.setattr(mailer, "mail_configured", lambda: True)
    monkeypatch.setattr(mailer, "send_email",
                        lambda to, *a, **kw: sent.append(to) or "sent")
    c, app_mod = gated
    _as_operator(c)
    from chordential_oia.models import MusicDiscipline
    from chordential_oia.talent import Talent
    conn = app_mod.db.connect()
    try:
        tid = app_mod.db.insert_talent(conn, Talent(
            name="No Address", email="", disciplines=[MusicDiscipline.COMPOSITION]))
    finally:
        conn.close()
    r = c.post(f"/talent/{tid}/agreement/send", follow_redirects=False)
    assert "agr=manual" in r.headers["location"]
    assert sent == [], "never guess at where a contract should go"
    assert "no email on file" in c.get(f"/talent/{tid}?agr=manual").text


def test_it_will_not_re_send_to_someone_who_already_signed(gated, monkeypatch):
    from chordential_oia import mailer
    sent = []
    monkeypatch.setattr(mailer, "mail_configured", lambda: True)
    monkeypatch.setattr(mailer, "send_email",
                        lambda to, *a, **kw: sent.append(to) or "sent")
    c, app_mod = gated
    tid, token = _writer(app_mod)
    _sign(c, token)
    sent.clear()
    _as_operator(c)
    c.post(f"/talent/{tid}/agreement/send", follow_redirects=False)
    assert sent == [], "asking a composer to sign what they already signed"


def test_the_governing_law_is_the_studios_and_is_set(monkeypatch):
    """Reported as confusing: is this per project? No — one decision for the business. A
    composer signs once and it governs every engagement, so it follows where the STUDIO
    is. It was briefly unset and blocking, which made the document refuse to exist until
    an environment variable was exported — not safer, just stuck."""
    # No env override here: the DEFAULT is what a fresh deploy uses, and that is the
    # thing worth pinning.
    monkeypatch.delenv("CHORDENTIAL_GOVERNING_LAW", raising=False)
    monkeypatch.delenv("CHORDENTIAL_FORUM", raising=False)
    text = composer_agreement.build_agreement({"name": "Dale"}).signable_text()
    assert "governed by the law of" in text
    assert composer_agreement.DEFAULT_GOVERNING_LAW in text
    assert composer_agreement.DEFAULT_FORUM in text
    # Law and forum are separate, or the clause reads "the law of X … the courts of X".
    assert "the law of the State of Florida, and both sides submit to the courts of " \
        "Miami-Dade County" in text


# ── the dashboard finds out, not just the inbox ──────────────────────────────────────
def _png_bytes():
    import base64
    import zlib
    raw = b"".join(b"\x00" + b"\xff\xff\xff" * 4 for _ in range(4))
    def chunk(tag, data):
        return (len(data).to_bytes(4, "big") + tag + data
                + zlib.crc32(tag + data).to_bytes(4, "big"))
    blob = (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", (4).to_bytes(4, "big") + (4).to_bytes(4, "big")
                    + bytes([8, 2, 0, 0, 0]))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return "data:image/png;base64," + base64.b64encode(blob).decode(), blob


def test_a_signed_agreement_lands_on_the_dashboard_queue(gated):
    """Reported: "when the talent signs the composer agreement and sends it back the
    chordential dashboard needs to get a notification." It only ever sent an email, and
    an email is not a queue — a signature is a pending DECISION, which is what the
    Disposition Queue is for."""
    from chordential_oia.web import queue as queue_mod
    c, app_mod = gated
    tid, token = _writer(app_mod)
    conn = app_mod.db.connect()
    try:
        before = [q for q in queue_mod.compute_queue(conn, app_mod.db)
                  if q["kind"] == "composer_countersign"]
    finally:
        conn.close()
    assert before == []

    _sign(c, token)
    conn = app_mod.db.connect()
    try:
        cards = [q for q in queue_mod.compute_queue(conn, app_mod.db)
                 if q["kind"] == "composer_countersign"]
    finally:
        conn.close()
    assert len(cards) == 1
    card = cards[0]
    assert "Dale Malleh" in card["title"]
    assert card["url"] == f"/talent/{tid}#access", "the card must go where the act is"
    assert card["urgency"] == 3, "a person who signed is waiting on us"


def test_the_card_clears_once_it_is_countersigned(gated):
    """A queue that keeps showing a decision already taken is one nobody trusts."""
    from chordential_oia.web import queue as queue_mod
    c, app_mod = gated
    _as_operator(c)
    tid, token = _writer(app_mod)
    _sign(c, token)
    c.post(f"/talent/{tid}/agreement/countersign", data={"typed_name": "Jon Shipp"},
           follow_redirects=False)
    conn = app_mod.db.connect()
    try:
        cards = [q for q in queue_mod.compute_queue(conn, app_mod.db)
                 if q["kind"] == "composer_countersign"]
    finally:
        conn.close()
    assert cards == []


def test_the_queue_page_shows_it(gated):
    c, app_mod = gated
    _as_operator(c)
    _tid, token = _writer(app_mod)
    _sign(c, token)
    page = c.get("/queue").text
    assert "Signed — waiting on your countersignature" in page
    assert "Countersign — Dale Malleh" in page


# ── the drawn signature travels as a file ────────────────────────────────────────────
def test_the_signed_copy_carries_the_drawn_signature_as_an_attachment(gated, monkeypatch):
    """Reported: "it comes back as signed but it comes back as text. I cant see a copy of
    the digital signature." It was plain text with no image — and inline would not have
    worked either, because the mark is stored as a data: URI and Gmail strips those out
    of <img>. A file arrives everywhere."""
    from chordential_oia import mailer
    sent = []
    monkeypatch.setenv("CHORDENTIAL_OPERATOR_EMAIL", "jon@chordential.com")
    monkeypatch.setattr(mailer, "send_email",
                        lambda to, subject, body, **kw: sent.append((to, kw)) or "sent")
    c, app_mod = gated
    _tid, token = _writer(app_mod)
    mark, blob = _png_bytes()
    _sign(c, token, drawn_signature=mark)

    assert len(sent) == 2, "both parties get a copy"
    for _to, kw in sent:
        assert kw.get("html"), "a contract that arrives as a wall of text reads as spam"
        files = kw.get("files") or []
        assert len(files) == 1, "the drawn signature did not travel"
        name, mime, data = files[0]
        assert name == "signature.png" and mime == "image/png"
        assert data == blob, "the attachment is not the mark they drew"


def test_no_drawing_means_no_attachment(gated, monkeypatch):
    """An empty PNG attached to every contract is noise, and it would imply a mark that
    was never made."""
    from chordential_oia import mailer
    sent = []
    monkeypatch.setenv("CHORDENTIAL_OPERATOR_EMAIL", "jon@chordential.com")
    monkeypatch.setattr(mailer, "send_email",
                        lambda to, subject, body, **kw: sent.append(kw) or "sent")
    c, app_mod = gated
    _tid, token = _writer(app_mod)
    _sign(c, token)
    assert sent and all(not (kw.get("files") or []) for kw in sent)


def test_a_hostile_mark_never_becomes_an_attachment(gated, monkeypatch):
    """`clean_drawn_mark` guards what is stored; `drawn_mark_png` guards what is handed
    to a mail client. A row written by hand in the database must not become a file."""
    from chordential_oia import signing
    assert signing.drawn_mark_png("data:text/html;base64,PHNjcmlwdD4=") is None
    assert signing.drawn_mark_png("") is None
    mark, blob = _png_bytes()
    assert signing.drawn_mark_png(mark) == blob
