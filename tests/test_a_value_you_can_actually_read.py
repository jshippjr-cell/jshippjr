"""Campaign Intelligence values you can actually read.

The canonical fields render what the extraction engine took from a call, and what it takes
is a SENTENCE, not a token:

    "Two-minute master for the film, 30-second cut down for broadcast, 15-second cut down
     for broadcast (may change to 6 seconds, to be confirmed), four vertical social
     versions, stems on the master only, grouped rather than per instrument"

Each of those sat in a single-line `<input>`, so the operator saw as far as "…may change
to 6 seconds, to be confirme" and no further — *"the text reads off the screen"* (operator,
2026-08-26). Beneath every one of them is a **Confirm** button.

That is the part that matters. The whole governing rule here is "the machine proposes, Jon
disposes", and a disposal is only a decision if the thing being disposed of can be read.
Confirming a value you can only see the first two thirds of is not review; it is assent.
"""
import importlib
import re

import pytest


@pytest.fixture()
def detail(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "d.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "passphrase")
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    for m in ("db", "campaigns", "uploads", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod, campaign_intelligence as ci, db
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    with TestClient(app_mod.app):
        pass
    c = TestClient(app_mod.app)
    c.cookies.set(ADMIN_COOKIE, admin_cookie_value("passphrase"))
    conn = db.connect()
    try:
        opp = int(conn.execute(
            "SELECT id FROM opportunities ORDER BY id LIMIT 1").fetchone()["id"])
        row = db.ci_for_opportunity(conn, opp)
        cid = int(row["id"]) if row is not None else int(
            ci.ensure_for_opportunity(conn, db.get_opportunity(conn, opp))["id"])
        ci.contribute(conn, cid, "engagement", "deliverables", LONG, kind="fact",
                      source="discovery_call", contributed_by="t")
        conn.commit()
    finally:
        conn.close()
    return c, opp


LONG = ("Two-minute master for the film, 30-second cut down for broadcast, 15-second cut "
        "down for broadcast (may change to 6 seconds, to be confirmed), four vertical "
        "social versions, stems on the master only, grouped rather than per instrument")


def test_a_value_is_never_truncated_by_the_box_it_sits_in(detail):
    """A single-line `<input value="...">` shows what fits and hides the rest. A textarea
    holds the whole sentence, and folding it is a matter of height rather than of loss."""
    c, opp = detail
    page = c.get(f"/opportunity/{opp}").text
    assert 'class="ci-val"' in page, "the value box is not a textarea"
    assert re.search(r'<textarea class="ci-val"[^>]*>' + re.escape(LONG) + r'</textarea>',
                     page), "the full value is not in the page"


def test_the_editable_value_still_posts_under_the_same_name(detail):
    """The box changed shape, not contract. Save must keep working, or a page that reads
    better has become a page that cannot be corrected."""
    c, opp = detail
    edited = LONG.replace("four vertical", "FIVE vertical")
    r = c.post(f"/opportunity/{opp}/intelligence/field",
               data={"field_id": "", "facet": "engagement", "key": "deliverables",
                     "kind": "fact", "value": edited}, follow_redirects=True)
    assert r.status_code == 200
    assert "FIVE vertical" in c.get(f"/opportunity/{opp}").text


def test_the_text_is_reachable_without_javascript(detail):
    """The expand button is built by script, because whether a value overflows is a fact
    about the rendered box and not about the data — the same sentence fits on a desktop and
    does not on a phone. So the no-JS floor has to be in the CSS: the box is
    `resize:vertical`, which means the text is folded, never unreachable."""
    c, opp = detail
    page = c.get(f"/opportunity/{opp}").text
    assert "resize:vertical" in page


def test_opening_a_value_grows_the_box_rather_than_raising_a_ceiling(detail):
    """The first version toggled `max-height`, which only caps a box and cannot grow one:
    every value "opened" and every one stayed clipped, because the textarea is `rows="1"`
    and one line tall is what it remained. Height is the property that grows it."""
    c, opp = detail
    page = c.get(f"/opportunity/{opp}").text
    open_fn = page[page.index("function fit(el)"):][:600]
    assert "el.style.height" in open_fn, "the toggle does not set height"
    assert 'el.style.maxHeight' not in open_fn


def test_the_expand_button_never_submits_the_row_it_sits_in(detail):
    """It lives inside the field's own `<form>`, one element away from Save. A button with
    no explicit type submits, so the un-typed version of this would have saved the field
    every time somebody wanted to read it."""
    c, opp = detail
    page = c.get(f"/opportunity/{opp}").text
    made = page[page.index('btn.className = "ci-more"') - 400:][:500]
    assert 'btn.type = "button"' in made
