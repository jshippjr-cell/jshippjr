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
    block = LIVE_JS.split("data-upload")[1]
    for banned in ("setInterval", "setTimeout", "Math.random"):
        assert banned not in block, (
            f"{banned} in the upload path — progress must come from bytes, not a clock")


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
