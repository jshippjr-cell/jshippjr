"""The press that never left the browser.

Reported seven times across three days, in the operator's words each time some version of:
*"I approved it once again inside 'the room' and nothing pushed to the clients side of
'the room'"* — and finally, the question that got it found: *"are you making the changes
inside 'the room'?"*

Six reproductions had been built and all six passed, because every one of them posted to
the route directly. **The bug was never in the route. It was in the click.**

A ``<button name="action">`` shadows the form's own ``action`` property. The publish gate
carries two of them (publish / send back), so ``f.action`` did not return the URL — it
returned a ``RadioNodeList``. Driven in a real browser, the press did this::

    POST /room/[object%20RadioNodeList]  →  405 Method Not Allowed

Nothing reached the server. And because the handler updates the row optimistically —
removing the gate and re-counting what is left — the lane went "3 files under review" to
"2", so the press *looked* like it worked. Every symptom followed from that: the studio
saw progress, the client saw nothing, and the server had no record of a request.

This is a sitewide hazard, not one form: seven templates carry two or more controls named
``action``, and ``live.js`` handles forms on every page. So the rule is enforced by
reading the source, not by trusting that the next author remembers.
"""
import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from chordential_oia.web import app as app_mod  # noqa: E402

WEB = Path(app_mod.__file__).parent
TEMPLATES = sorted((WEB / "templates").glob("*.html"))
SCRIPTS = sorted((WEB / "static").glob("*.js"))

#: `<x>.action` read off something that is almost certainly a form, in a request call.
_SHADOWED = re.compile(r"(?:fetch\(|xhr\.open\(\s*[\"']POST[\"']\s*,\s*)\s*([A-Za-z_$][\w$]*)\.action\b")


def _offenders(text):
    return sorted({m.group(1) for m in _SHADOWED.finditer(text)})


@pytest.mark.parametrize("path", TEMPLATES + SCRIPTS, ids=lambda p: p.name)
def test_no_request_reads_a_forms_action_property(path):
    """``form.action`` is unsafe wherever a control may be named "action" — and it is
    unsafe to *assume* it is not, because the control is added by whoever edits the
    template later, not by whoever wrote the fetch.

    ``getAttribute("action")`` cannot be shadowed, costs nothing, and is correct on every
    form. So the property read is banned outright rather than allowed "where it is fine".
    """
    text = path.read_text(encoding="utf-8")
    bad = _offenders(text)
    assert bad == [], (
        f"{path.name} posts to `{bad[0]}.action` — a control named \"action\" shadows "
        f"that property and the request goes to `[object HTMLButtonElement]` (or a "
        f"RadioNodeList). Use formURL(...) / getAttribute(\"action\").")


def test_the_room_has_the_helper_and_uses_it():
    text = (WEB / "templates" / "creator_portal.html").read_text(encoding="utf-8")
    assert "function formURL(" in text
    assert 'getAttribute("action")' in text
    assert "fetch(formURL(" in text


def test_the_sitewide_layer_has_it_too():
    text = (WEB / "static" / "live.js").read_text(encoding="utf-8")
    assert "function formURL(" in text and "fetch(formURL(" in text


def test_the_helper_is_declared_at_script_top_level():
    """It was first inserted INSIDE another function, where its hoisting reaches only
    that function — every other handler would still have thrown. Cheap to get wrong,
    invisible until a press fails."""
    text = (WEB / "templates" / "creator_portal.html").read_text(encoding="utf-8")
    i = text.index("function formURL(")
    before = text[:i]
    assert before.count("<script") == before.count("</script>") + 1, (
        "formURL is not inside a script block")
    # the line before it must not be inside an open function body: the helper sits at
    # the top of its script, immediately after the tag or another top-level statement.
    head = before[before.rindex("<script"):]
    depth = head.count("{") - head.count("}")
    assert depth == 0, (
        f"formURL is nested {depth} block(s) deep — handlers outside that block cannot "
        f"see it")


def test_the_publish_gate_really_does_carry_two_controls_named_action():
    """The condition that made this fire. If the gate ever stops carrying two, the bug
    stops being reachable there — but the ban above still stands, because the next
    template will."""
    text = (WEB / "templates" / "creator_portal.html").read_text(encoding="utf-8")
    gate = text[text.index('action="/project/{{ a.project_id }}/delivery/asset/publish"'):]
    gate = gate[:gate.index("</form>")]
    assert gate.count('name="action"') >= 2
