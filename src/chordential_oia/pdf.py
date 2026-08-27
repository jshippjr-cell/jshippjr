"""A PDF writer, in the standard library.

WHY NOT A LIBRARY. `pyproject.toml` declares `pdf = ["reportlab>=4.0"]` as an OPTIONAL
extra, and `delivery._render_pdf_from_html` renders through Playwright when a chromium
binary happens to be importable. Both are best-effort by design, and best-effort is exactly
what a signed copy cannot be: the client's confirmation email says the agreement is
attached, and an attachment that appears on a machine with the extra installed and not on
one without is the same failure as a delivery package that shipped documents and no audio.
An operator cannot see the difference until a client asks where their contract is.

So this writes the bytes itself. It is deliberately small and dull — the base-14 fonts every
reader has built in (no embedding), one text stream per page, an xref table. That is enough
for a signed record and nothing more; it is not a layout engine and must not grow into one.
If a branded, designed PDF is ever wanted, that is Playwright's job and it can stay
best-effort, because a pretty document failing to render still leaves this one.

WHAT IT MUST CARRY. `agreement.signable_text()` is the document a signature's SHA-256 is
taken over (ADR-0065: never hash rendered HTML). This renders that text verbatim — same
string, wrapped — so the attachment and the digest cannot describe different documents.
Wrapping changes where lines break; it never changes a character.
"""
from __future__ import annotations

import zlib
from typing import List, Optional, Sequence, Tuple

# Base-14. Every conforming reader has these, so nothing is embedded and the file stays a
# few kilobytes — which matters for something attached to every signature email.
_FONT = "Helvetica"
_BOLD = "Helvetica-Bold"
_MONO = "Courier"

# A4 in points, and a margin wide enough that a phone reader does not have to pan.
PAGE_W, PAGE_H = 595.28, 841.89
MARGIN = 56.0
LEADING = 13.2
SIZE = 9.6


def _esc(text: str) -> str:
    """PDF string escaping. A stray backslash or bracket ends the string early and the
    reader shows the rest as nothing — the failure looks like missing content, not a
    malformed file, so it is the one that would be reported as "the PDF is blank"."""
    return (text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)"))


def _latin1(text: str) -> str:
    """The base-14 fonts are WinAnsi. A character outside it is TRANSLITERATED rather than
    dropped: a licence term reading "3 years" where the document said "3 years —
    worldwide" would be a different agreement, so the dashes and quotation marks a written
    document is full of have to survive as something."""
    swaps = {
        "—": "-", "–": "-", "‘": "'", "’": "'",
        "“": '"', "”": '"', "…": "...", " ": " ",
        "•": "*", "×": "x", "→": "->", "✓": "[x]",
        "─": "-", "·": "-",
    }
    for bad, good in swaps.items():
        text = text.replace(bad, good)
    return text.encode("latin-1", "replace").decode("latin-1")


def _width(text: str, size: float, mono: bool) -> float:
    """Close enough to wrap on. Courier is exactly 0.6em; Helvetica varies per glyph and
    0.5em is a deliberate slight over-estimate, so a line errs toward wrapping early rather
    than running off the right edge — which is the failure a reader can see."""
    return len(text) * size * (0.6 if mono else 0.5)


def wrap(text: str, size: float = SIZE, *, mono: bool = True,
         width: float = PAGE_W - 2 * MARGIN) -> List[str]:
    """Break a document into printable lines, preserving its own blank lines.

    Long unbroken tokens (a SHA-256 digest, a URL) are HARD-SPLIT rather than allowed to
    overflow. A digest that runs off the page is not a cosmetic problem: it is the field a
    reader checks the document against."""
    out: List[str] = []
    for raw in _latin1(text).replace("\r", "").split("\n"):
        line = raw.rstrip()
        if not line:
            out.append("")
            continue
        words, current = line.split(" "), ""
        for word in words:
            while _width(word, size, mono) > width:
                cut = max(1, int(width / (size * (0.6 if mono else 0.5))))
                if current:
                    out.append(current)
                    current = ""
                out.append(word[:cut])
                word = word[cut:]
            trial = f"{current} {word}".strip()
            if current and _width(trial, size, mono) > width:
                out.append(current)
                current = word
            else:
                current = trial
        out.append(current)
    return out


def _page_stream(lines: Sequence[Tuple[str, bool]]) -> bytes:
    """One page's content: (text, is_heading) pairs, top-down."""
    parts = ["BT"]
    y = PAGE_H - MARGIN
    font = None
    for text, heading in lines:
        want = (_BOLD, 11.0) if heading else (_MONO, SIZE)
        if font != want:
            parts.append(f"/{'FB' if heading else 'FM'} {want[1]:.1f} Tf {LEADING:.1f} TL")
            font = want
        parts.append(f"1 0 0 1 {MARGIN:.1f} {y:.1f} Tm ({_esc(text)}) Tj")
        y -= LEADING if not heading else LEADING + 4
    parts.append("ET")
    return zlib.compress("\n".join(parts).encode("latin-1", "replace"))


def text_pdf(title: str, body: str, *, subtitle: str = "",
             footer: str = "") -> bytes:
    """A plain, readable PDF of ``body``. Returns bytes; never raises on ordinary text.

    ``title``/``subtitle`` head the first page. ``footer`` is stamped at the foot of every
    page — used for the provenance line, so a page separated from the rest still says what
    document it came from and who signed it.
    """
    lines: List[Tuple[str, bool]] = []
    if title:
        lines.append((_latin1(title), True))
    if subtitle:
        lines.append((_latin1(subtitle), False))
        lines.append(("", False))
    lines.extend((ln, False) for ln in wrap(body))

    per_page = int((PAGE_H - 2 * MARGIN - (24 if footer else 0)) // LEADING)
    pages = [lines[i:i + per_page] for i in range(0, len(lines), per_page)] or [[("", False)]]

    foot = _latin1(footer)
    streams = []
    for n, page in enumerate(pages, start=1):
        content = list(page)
        if foot:
            content.append(("", False))
            content.append((f"{foot}  ·  page {n} of {len(pages)}".replace("·", "-"), False))
        streams.append(_page_stream(content))

    # ── objects ──────────────────────────────────────────────────────────────────
    objects: List[bytes] = []

    def add(raw: bytes) -> int:
        objects.append(raw)
        return len(objects)          # 1-based object number

    font_mono = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier "
                    b"/Encoding /WinAnsiEncoding >>")
    font_bold = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
                    b"/Encoding /WinAnsiEncoding >>")
    # The Pages object is written last but must be referenced by every page, so its number
    # is reserved here — a forward reference is legal and this is the ordinary way to do it.
    pages_obj = len(objects) + 2 * len(streams) + 1
    page_ids = []
    for stream in streams:
        sid = add(b"<< /Length " + str(len(stream)).encode() + b" /Filter /FlateDecode >>"
                  b"\nstream\n" + stream + b"\nendstream")
        page_ids.append(add(
            b"<< /Type /Page /Parent " + str(pages_obj).encode() + b" 0 R"
            b" /MediaBox [0 0 " + f"{PAGE_W:.2f} {PAGE_H:.2f}".encode() + b"]"
            b" /Resources << /Font << /FM " + str(font_mono).encode() + b" 0 R"
            b" /FB " + str(font_bold).encode() + b" 0 R >> >>"
            b" /Contents " + str(sid).encode() + b" 0 R >>"))
    kids = b" ".join(str(i).encode() + b" 0 R" for i in page_ids)
    real_pages = add(b"<< /Type /Pages /Count " + str(len(page_ids)).encode()
                     + b" /Kids [" + kids + b"] >>")
    if real_pages != pages_obj:
        # A raise, not an assert: `python -O` strips asserts, and this one guards a
        # forward reference. Wrong, it produces a file that opens to a blank page — the
        # failure a client would report as "the attachment is empty".
        raise RuntimeError(
            f"/Pages reserved as {pages_obj} but written as {real_pages}")
    catalog = add(b"<< /Type /Catalog /Pages " + str(pages_obj).encode() + b" 0 R >>")

    # ── file ─────────────────────────────────────────────────────────────────────
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for num, raw in enumerate(objects, start=1):
        offsets.append(len(out))
        out += str(num).encode() + b" 0 obj\n" + raw + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n"
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += (b"trailer\n<< /Size " + str(len(objects) + 1).encode()
            + b" /Root " + str(catalog).encode() + b" 0 R >>\n"
            b"startxref\n" + str(xref_at).encode() + b"\n%%EOF\n")
    return bytes(out)


def signed_copy_pdf(document: str, *, title: str, signer: str, signed_at: str,
                    digest: str, consent: str, email: str = "",
                    campaign: str = "") -> bytes:
    """The client's signed agreement, as one attachable file.

    ``document`` must be `agreement.signable_text()` — the exact string the digest was
    taken over — so the attachment and the SHA-256 printed on it describe the same
    document. Rendering the HTML instead would produce a file whose digest nobody could
    reproduce, which is the whole failure ADR-0065 was written against.
    """
    block = [
        document.rstrip(),
        "",
        "=" * 66,
        "SIGNATURE",
        "=" * 66,
        f"Signed by:     {signer}" + (f" <{email}>" if email else ""),
        f"Signed at:     {signed_at}",
        "",
        "Consent given:",
        consent,
        "",
        f"Document digest (SHA-256):",
        digest,
        "",
        "This digest is taken over the text above. If the document is altered the",
        "digest no longer matches, and the signature reads as superseded.",
    ]
    return text_pdf(
        title, "\n".join(block),
        subtitle=campaign,
        footer=f"Chordential - signed copy - {signer} - {signed_at[:10]}")


__all__ = ["text_pdf", "signed_copy_pdf", "wrap", "PAGE_W", "PAGE_H"]
