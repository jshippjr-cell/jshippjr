"""Console uploads show real bytes moving.

The delivery console carries the largest files in the system — a picture cut or a stem
package is hundreds of MB — and its four upload forms were naked synchronous multipart
POSTs: a blank tab, no feedback, and no way to tell a stalled upload from a slow one.
Both *client-facing* surfaces already had XHR byte progress (the portal's Drop and the
creator portal's master upload); the operator, moving the biggest files, had none.

ADR-0038 adds ONE declarative behaviour (`data-upload` in `live.js`) rather than a third
copy of the same twenty lines. Honest liveness: the bar tracks `ev.loaded/ev.total` and
nothing else — no indeterminate crawl, no minimum duration.

Browser-driven proof (a throttled 24 MB upload reporting `0 of 24 MB` → `13% · 3.1 MB of
24 MB`, the failure note, and the no-JS fallback) lives in the commit message; these
tests pin the contract that keeps it true.
"""

import re
from pathlib import Path

import pytest

from chordential_oia.web import app as app_mod

TPL = Path(app_mod.__file__).parent / "templates"
STATIC = Path(app_mod.__file__).parent / "static"
LIVE_JS = (STATIC / "live.js").read_text(encoding="utf-8")
CONSOLE = (TPL / "delivery_console.html").read_text(encoding="utf-8")


def _forms_with_file_input(html: str):
    """Every <form> in the template that takes a file."""
    return [m.group(0) for m in re.finditer(r"<form\b[^>]*>", html)
            if "multipart/form-data" in m.group(0)]


# --------------------------------------------------------------------------- #
# The console's uploads are covered
# --------------------------------------------------------------------------- #
def test_every_console_upload_form_reports_progress():
    forms = _forms_with_file_input(CONSOLE)
    assert len(forms) >= 4, f"expected the console's four upload forms, found {len(forms)}"
    missing = [f for f in forms if "data-upload" not in f]
    assert missing == [], (
        "these console uploads still post naked, with no byte feedback:\n  "
        + "\n  ".join(missing))


def test_the_four_console_uploads_are_the_expected_ones():
    """Named so a new upload surface has to be considered, not silently added."""
    for action in ("delivery/picture", "delivery/reference",
                   "delivery/asset", "delivery/version"):
        # Several forms post to the same action (e.g. /delivery/asset is both an
        # upload and a per-asset action bar). Only the multipart one carries a file.
        uploads = [f for f in _forms_with_file_input(CONSOLE)
                   if re.search(re.escape(action) + r'"', f)]
        assert uploads, f"the {action} upload form is gone — was it moved?"
        for f in uploads:
            assert "data-upload" in f, f"{action} posts with no progress"


# --------------------------------------------------------------------------- #
# What the behaviour may and may not do
# --------------------------------------------------------------------------- #
def test_progress_is_driven_by_real_bytes():
    """The Living OS rule: motion communicates real state. A bar that animates on a
    timer while bytes may not be moving is decoration, and worse than none."""
    assert "xhr.upload.addEventListener" in LIVE_JS
    assert "ev.loaded / ev.total" in LIVE_JS
    assert "lengthComputable" in LIVE_JS, (
        "no guard for a browser that cannot report a total")


def test_no_indeterminate_animation_stands_in_for_progress():
    """The Living OS rule, guarded at the BAR rather than the file.

    This used to ban timers everywhere after the first mention of `data-upload`, which
    was a fine proxy while the only thing down there was the bar. It stopped being one
    when the success acknowledgement arrived: that banner fades in and dismisses itself
    on a clock, and correctly so — it reports a finished fact, it does not animate an
    unfinished one. Rather than punch a hole in the rule, the scope narrows to the
    region that actually draws progress, and gains the assertion that matters more —
    the bar's width can only ever come from bytes.
    """
    bar_region = LIVE_JS.split('xhr.upload.addEventListener("progress"')[1] \
                        .split('xhr.upload.addEventListener("load"')[0]
    for banned in ("setInterval", "setTimeout", "Math.random"):
        assert banned not in bar_region, (
            f"{banned} while the bar is being drawn — progress must come from bytes")

    # Every width the bar is ever given, and where each one comes from.
    widths = re.findall(r"fill\.style\.width\s*=\s*([^;]+);", LIVE_JS)
    assert widths, "the bar is never given a width — has it been renamed?"
    for w in widths:
        assert "pct" in w or "100%" in w, (
            f"the bar's width comes from {w.strip()!r}, which is not a byte count")


def test_a_failure_says_so_and_keeps_the_file():
    """Re-picking a 300 MB file because the UI silently reset is the worst outcome."""
    assert "still chosen" in LIVE_JS
    assert "Connection lost" in LIVE_JS
    assert 'classList.add("failed")' in LIVE_JS


def test_the_upload_never_fights_the_thinking_veil():
    """`data-think` and `data-upload` are both capture-phase submit handlers that call
    preventDefault. The AI intake form is data-think — its wait is the 10-agent
    extraction, not the voice memo's bytes — and must keep its veil."""
    assert 'if (form.hasAttribute("data-think")) return;' in LIVE_JS
    detail = (TPL / "detail.html").read_text(encoding="utf-8")
    m = re.search(r"<form\b[^>]*intelligence/analyze[^>]*>", detail, re.S)
    assert m and "data-think" in m.group(0)
    assert "data-upload" not in m.group(0)


def test_it_degrades_to_a_plain_post():
    """No JS, no XHR, or no file chosen → the form submits normally. The console must
    never depend on the enhancement to work at all."""
    assert "if (!window.XMLHttpRequest || !window.FormData) return;" in LIVE_JS
    assert "if (!input || !input.files || !input.files.length) return;" in LIVE_JS
    for form in _forms_with_file_input(CONSOLE):
        assert 'method="post"' in form, "an upload form relies on JS to submit at all"
        assert "action=" in form


def test_the_rail_is_styled_for_both_outcomes():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    for cls in (".lv-up", ".lv-up.on", ".lv-up-bar", ".lv-up-note", ".lv-up.failed"):
        assert cls in css, f"{cls} has no styling — the rail would be invisible"


def test_one_implementation_not_a_third_copy():
    """The console reaches the shared behaviour through base.html. Adding a fourth
    inline uploader would be the pattern this ADR removed."""
    assert "live.js" in (TPL / "base.html").read_text(encoding="utf-8")
    assert "{% extends \"base.html\" %}" in CONSOLE
    assert "XMLHttpRequest" not in CONSOLE, (
        "the console grew its own uploader instead of using data-upload")


@pytest.mark.parametrize("template", ["_brief_document.html", "compose.html"])
def test_the_other_large_file_attachments_are_covered_too(template):
    """Both accept `audio/*` — a WAV master is the same order of magnitude as the
    console's own uploads, and neither carried any feedback either."""
    html = (TPL / template).read_text(encoding="utf-8")
    audio_forms = [f for f in _forms_with_file_input(html)]
    assert audio_forms, f"{template} no longer has a file upload — was it moved?"
    assert any("data-upload" in f for f in audio_forms), (
        f"{template} posts an audio attachment with no progress")


# --------------------------------------------------------------------------- #
# …and then say what HAPPENED
# --------------------------------------------------------------------------- #
def test_every_upload_form_says_what_landed():
    """The bar was honest about the bytes and then said nothing about the result.

    On success the handler called `window.location.reload()`, which throws away the
    redirect the server just issued — anchor and all — and drops the operator wherever
    they happened to be. On the delivery console that is three full screens from the
    card the upload produces (measured in a browser: form at y=2858, card at y=288,
    800px viewport). Reported verbatim during a live session: *"I uploaded a new
    version twice, it went nowhere, I don't know where to go to play it back."* The
    upload had worked both times.

    Every `data-upload` form must therefore declare what to say. A silent success is
    the failure this fixes, and a new form that forgets is the same bug again.
    """
    silent = []
    for path in sorted(TPL.rglob("*.html")):
        html = path.read_text(encoding="utf-8")
        for m in re.finditer(r"<form[^>]*\bdata-upload\b[^>]*>", html, re.S):
            if "data-note=" not in m.group(0):
                silent.append(f"{path.name}: {m.group(0)[:90]}…")
    assert silent == [], (
        "these uploads succeed without telling the operator anything:\n  "
        + "\n  ".join(silent))


def test_the_console_uploads_point_at_the_card_they_produce():
    """`data-after` is the anchor the operator is taken to. It has to name a section
    that actually exists, or the reload lands nowhere and we are back to hunting."""
    missing = []
    for m in re.finditer(r"<form[^>]*\bdata-upload\b[^>]*>", CONSOLE, re.S):
        tag = m.group(0)
        after = re.search(r'data-after="#([\w-]+)"', tag)
        if not after:
            missing.append(f"no data-after: {tag[:80]}…")
        elif f'id="{after.group(1)}"' not in CONSOLE:
            missing.append(f'data-after="#{after.group(1)}" but no such id in the page')
    assert missing == [], "\n  ".join(missing)


def test_the_version_upload_does_not_claim_the_client_has_it():
    """Every upload lands as a PENDING submission and waits for an explicit publish
    ("the machine proposes, Jon disposes"). An acknowledgement that let the operator
    believe the client already had it would be worse than the silence it replaces."""
    form = re.search(r'<form[^>]*/delivery/version"[^>]*>', CONSOLE, re.S).group(0)
    note = re.search(r'data-note="([^"]*)"', form).group(1)
    assert "nothing has gone to the client" in note.lower(), note


def test_the_acknowledgement_survives_the_reload_and_then_leaves():
    """It is written before the reload and read after it, because the page the
    operator needs to be told about is the one that has not loaded yet. And it sits
    over the page, so it dismisses itself — the card it points at is the durable
    record; this is only the pointer."""
    assert "sessionStorage.setItem(ACK" in LIVE_JS
    assert "sessionStorage.getItem(ACK)" in LIVE_JS
    assert "sessionStorage.removeItem(ACK)" in LIVE_JS, "it would fire on every later page"
    assert "setTimeout(dismiss," in LIVE_JS, "a banner that never leaves covers the page"
    assert 'role", "status"' in LIVE_JS, "an acknowledgement nobody announces is half of one"


def test_the_bare_reload_is_gone():
    """The regression is literally one line coming back."""
    assert "window.location.reload(); return;" not in LIVE_JS
    assert "landed(form, input.files[0].name)" in LIVE_JS
