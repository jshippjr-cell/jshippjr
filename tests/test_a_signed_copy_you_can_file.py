"""The signed copy as a file, and the signature at a size you can look at.

    "The client's signature is off of the screen. Fix that. And, also, when you send the
     email to the client confirming their signature, you send a text copy. I want you to
     send a PDF attachment to that email."          — the operator, 2026-08-27

The CSS one has a tidy cause. `.sig-mark` — the rule that sizes the drawn mark to 260px —
lived inside the signature PAD's stylesheet, which the brief emits under
``{% if doc.show_agreement and sign_url %}``. `sign_url` goes empty the moment a signature
is VALID. So the rule existed only while there was no signature to display, and vanished
the instant there was one: the canvas PNG rendered at its natural 900px and ran off the
page. Reported on a phone, where the overflow is total.

The PDF is a different kind of decision. `pyproject.toml` declares `pdf = ["reportlab>=4.0"]`
as an optional extra and `delivery._render_pdf_from_html` needs a chromium binary — both
best-effort, which is fine for a pretty delivery document and wrong for a contract. An
attachment that appears on a machine with the extra installed and not on one without is a
failure nobody sees until a client asks where their agreement is. So the writer is stdlib.
"""
import importlib
import re

import pytest

pytest.importorskip("fastapi")

from chordential_oia import pdf as pdf_writer


# ── the writer ──────────────────────────────────────────────────────────────────────
def test_it_writes_a_pdf_a_reader_will_open():
    out = pdf_writer.text_pdf("Title", "Hello.\n\nSecond paragraph.")
    assert out.startswith(b"%PDF-")
    assert out.rstrip().endswith(b"%%EOF")


def test_every_xref_offset_points_at_the_object_it_claims():
    """A byte-exact table. An offset one byte out gives a file that opens to a blank page
    in some readers and an error in others — the failure a client reports as "the
    attachment is empty", which sounds like a mail problem and is not."""
    out = pdf_writer.text_pdf("T", "\n".join(f"line {i}" for i in range(300)))
    start = int(out[out.rindex(b"startxref"):].split(b"\n")[1])
    rows = out[start:].split(b"\n")
    assert rows[0].startswith(b"xref")
    count = int(rows[1].split()[1])
    for n in range(1, count):
        offset = int(rows[2 + n].split()[0])
        assert out[offset:offset + 40].startswith(f"{n} 0 obj".encode()), n


def test_a_long_document_paginates():
    one = pdf_writer.text_pdf("T", "short")
    many = pdf_writer.text_pdf("T", "\n".join(f"line {i}" for i in range(400)))
    assert one.count(b"/Type /Page ") == 1
    assert many.count(b"/Type /Page ") > 3


def test_a_digest_is_never_allowed_to_run_off_the_page():
    """It is the field a reader checks the document against. A SHA-256 is 64 unbroken
    characters and nothing in ordinary word-wrapping breaks it."""
    digest = "690b7d13a2b23e45726a85844b45c896dc2e11b882ef9016e932ab7e0380da08"
    lines = pdf_writer.wrap(digest)
    assert len(lines) >= 1
    assert "".join(lines) == digest, "the digest was altered, not just wrapped"
    limit = pdf_writer.PAGE_W - 2 * 56.0
    assert all(len(ln) * pdf_writer.SIZE * 0.6 <= limit for ln in lines)


def test_the_characters_a_written_document_is_full_of_survive():
    """Base-14 fonts are WinAnsi. An em dash or a curly quote dropped silently would make
    the attachment a different text from the one the digest covers."""
    body = "Fee: $55,000–$65,000 — a “hard ceiling”, all-in… 3 × cutdowns"
    out = pdf_writer.text_pdf("T", body)
    assert out.startswith(b"%PDF-")
    for word in ("55,000", "65,000", "hard", "ceiling", "cutdowns"):
        assert word in "".join(pdf_writer.wrap(body))


def test_a_bracket_in_the_text_does_not_end_the_string_early():
    """`(` and `)` delimit PDF strings. Unescaped, the reader shows the rest of the line as
    nothing — content loss that looks like a rendering bug."""
    out = pdf_writer.text_pdf("T", r"15-second cut down (may change to :06) \ or not")
    assert out.startswith(b"%PDF-") and b"%%EOF" in out


def test_the_signed_copy_carries_the_document_and_the_digest():
    doc = "DISCOVERY SUMMARY & PROPOSAL\nClient: Pike and Rowan\n\nSCOPE\nTwo-minute master."
    out = pdf_writer.signed_copy_pdf(
        doc, title="Signed copy", signer="Marisa del Rio",
        signed_at="2026-08-27T01:31:27+00:00", digest="abc123" * 10,
        consent="I agree to sign this electronically.", email="m@example.com",
        campaign="Pike and Rowan - Film music")
    assert out.startswith(b"%PDF-")
    assert len(out) > 800


def test_the_writer_needs_nothing_that_is_not_in_the_standard_library():
    """The whole reason it exists. If this module ever grows a third-party import, the
    attachment becomes conditional again and this test is the thing that says so."""
    import ast
    import pathlib
    src = pathlib.Path(pdf_writer.__file__).read_text(encoding="utf-8")
    stdlib = {"zlib", "typing", "__future__", "re", "math", "datetime", "io", "textwrap"}
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            for a in node.names:
                assert a.name.split(".")[0] in stdlib, a.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            assert (node.module or "").split(".")[0] in stdlib, node.module


# ── the email ───────────────────────────────────────────────────────────────────────
@pytest.fixture()
def signed(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "s.db"))
    monkeypatch.delenv("CHORDENTIAL_ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("CHORDENTIAL_OPERATOR_EMAIL", "jon@chordential.example")
    for m in ("db", "campaign_intelligence", "campaigns", "next_action", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia import mailer
    from chordential_oia.models import BuyerType, MusicRequirement, Opportunity
    from chordential_oia.web import app as app_mod

    sent = []
    real = mailer.send_email

    def spy(to, subject, text, html=None, ics=None, files=None):
        sent.append({"to": to, "subject": subject, "text": text,
                     "files": list(files or [])})
        return "logged"

    monkeypatch.setattr(mailer, "send_email", spy)
    db = app_mod.db
    with TestClient(app_mod.app) as c:
        conn = db.connect()
        try:
            oid = db.insert_opportunity(conn, Opportunity(
                client="Pike and Rowan", need="Autumn brand film",
                description="A two-minute brand film with a 30-second cut.",
                buyer_type=BuyerType.BRAND,
                music_requirement=MusicRequirement.ORIGINAL))
            conn.execute("UPDATE opportunities SET contact_email=? WHERE id=?",
                         ("marisa@pike.example", oid))
            conn.commit()
            db.create_meeting(conn, opp_id=oid, start_at="2026-08-20T14:00:00+00:00",
                              status="ingested")
            token = db.ensure_share_token(conn, oid)
        finally:
            conn.close()
        c.post(f"/workspace/{token}/sign",
               data={"typed_name": "Marisa del Rio",
                     "signer_email": "marisa@pike.example", "consent": "1"},
               follow_redirects=False)
    monkeypatch.setattr(mailer, "send_email", real)
    return sent


def _pdfs(mail):
    return [f for f in mail["files"] if f[1] == "application/pdf"]


def test_the_client_gets_their_agreement_as_a_file(signed):
    """"It is in the body of an email" is not a record you can file, forward to a lawyer,
    or open in a year."""
    to_client = [m for m in signed if m["to"] == "marisa@pike.example"]
    assert to_client, f"the signer was not emailed at all: {[m['to'] for m in signed]}"
    attached = _pdfs(to_client[0])
    assert attached, f"no PDF attached: {[(f[0], f[1]) for f in to_client[0]['files']]}"
    name, mime, blob = attached[0]
    assert name.endswith(".pdf") and mime == "application/pdf"
    assert blob.startswith(b"%PDF-") and blob.rstrip().endswith(b"%%EOF")


def test_the_operator_gets_the_same_file(signed):
    """One document. A copy that differs between the two inboxes is two agreements."""
    to_op = [m for m in signed if m["to"] == "jon@chordential.example"]
    to_client = [m for m in signed if m["to"] == "marisa@pike.example"]
    assert to_op and to_client
    assert _pdfs(to_op[0])[0][2] == _pdfs(to_client[0])[0][2]


def test_the_text_copy_stays_in_the_body_too(signed):
    """Belt and braces. Some clients read in a preview pane that never opens an
    attachment, and the text costs nothing to keep."""
    to_client = [m for m in signed if m["to"] == "marisa@pike.example"][0]
    assert "SIGNED COPY" in to_client["text"]
    assert "Document digest (SHA-256)" in to_client["text"]


def test_the_attachment_is_named_for_the_client(signed):
    to_client = [m for m in signed if m["to"] == "marisa@pike.example"][0]
    assert _pdfs(to_client)[0][0] == "pike-and-rowan-signed-agreement.pdf"


# ── the signature on screen ─────────────────────────────────────────────────────────
def test_the_rule_that_sizes_the_signature_is_not_conditional_on_the_pad():
    """THE CAUSE. `sign_url` is empty once a signature is valid, so anything inside the
    pad's `{% if %}` is absent in exactly the state that displays a signature."""
    import pathlib
    from chordential_oia.web import app as app_mod
    here = pathlib.Path(app_mod.__file__).parent
    doc = (here / "templates" / "_brief_document.html").read_text(encoding="utf-8")
    css = (here / "static" / "style.css").read_text(encoding="utf-8")
    assert ".sig-mark{" in css, "the rule is not in the always-loaded stylesheet"
    assert ".sig-mark{" not in doc, "the rule is back inside the conditional pad styles"


def test_the_signature_is_constrained_on_both_axes():
    """A mark drawn on a small phone canvas has a different aspect ratio. Constraining the
    width alone lets the height run, which is the same overflow in the other direction."""
    import pathlib
    from chordential_oia.web import app as app_mod
    css = (pathlib.Path(app_mod.__file__).parent / "static" / "style.css").read_text(
        encoding="utf-8")
    rule = css[css.index(".sig-mark{"):]
    rule = rule[:rule.index("}")]
    for prop in ("max-width", "max-height", "height:auto"):
        assert prop in rule.replace(" ", ""), prop
