"""The console nav carries only destinations that earn a permanent slot.

The launch review found 21 links in the sidebar. Measured on the seeded book, five
of them were not destinations at all:

* **`/lanes`** rendered the **identical** row set to `/inbox` (18 = 18, same ids) —
  the same table in different clothes, with the same one-click advance. Its only
  unique control was a "Won" button that POSTed ``status=Won`` with no
  ``outcome_value``, booking a won deal at **$0** and contradicting the rule
  documented at ``app.py``'s ``_NEXT_STATUS``: *"Won is intentionally omitted —
  closing a deal goes through the win/loss form so the value is captured."*
  Closing two deals that way summed to $13,325; through the form, $25,325.
* the four **quick-links** (`?action=Pursue`, `?action=Review`, `?status=Won`, and a
  `#followups` anchor) were saved searches over pages already in the nav — every one
  reproducible from `/inbox`'s own filter dropdowns.

ADR-0035. The same blind-Won path existed on the detail page's stepper and is closed
here too, so no surface can record a win without its value.
"""

import importlib
import re

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def app_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "nav.db"))
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as mod
    importlib.reload(mod)
    with TestClient(mod.app):
        pass
    return mod


def _nav_links(html: str):
    body = html.split('<div class="side-nav-wrap">')[1].split('<div class="sidebar-foot">')[0]
    return re.findall(r'href="([^"]+)"', body)


# --------------------------------------------------------------------------- #
# The diet
# --------------------------------------------------------------------------- #
def test_the_retired_board_is_gone(app_mod):
    with TestClient(app_mod.app) as c:
        assert c.get("/lanes").status_code == 404


def test_no_nav_slot_is_a_saved_search(app_mod):
    """A permanent nav slot is the scarcest thing on the screen. A pre-filtered URL
    into a page that is already in the nav does not earn one."""
    with TestClient(app_mod.app) as c:
        links = _nav_links(c.get("/dashboard").text)
    offenders = [h for h in links if "?" in h and h.split("?")[0] in
                 {l.split("?")[0] for l in links if "?" not in l}]
    assert offenders == [], f"these nav links are filters over another nav page: {offenders}"
    assert not [h for h in links if "#" in h], "an in-page anchor is not a destination"


def test_the_nav_has_no_duplicate_destinations(app_mod):
    with TestClient(app_mod.app) as c:
        links = _nav_links(c.get("/dashboard").text)
    paths = [h.split("?")[0] for h in links]
    assert len(paths) == len(set(paths)), f"duplicate nav destinations: {paths}"
    # Raised 16 → 17 (2026-08-21) for the Outbox (ADR-0086). Held to the same bar the
    # diet sets: it is not a saved search or a filter over a page already in the nav —
    # it is a destination that exists nowhere else, and it is where the client's own
    # experience gets read. Raise this again only for something that clears that bar.
    #
    # Raised 17 → 18 (2026-08-26) for /pricing, against the same bar. Every pricing
    # surface in the product hangs off ONE opportunity — the estimate, the proposal, the
    # prep sheet's guide — so the model itself had no home, and the model is what has to
    # be in the operator's head while a client is talking. It is not a filter over a page
    # already here (there is no such page), and it is read BETWEEN deals rather than
    # inside one, which is exactly what a permanent slot is for. Anything reachable from a
    # deal you are already looking at still does not earn one.
    assert len(links) <= 18, f"the nav is growing again ({len(links)} links)"


def test_the_deal_list_still_does_everything_the_board_did(app_mod):
    """The board is only safe to delete because nothing was lost with it: the same
    rows, the same advance control, plus search and filters it never had."""
    with TestClient(app_mod.app) as c:
        inbox = c.get("/inbox").text
    assert 'name="status"' in inbox and 'name="action"' in inbox   # filters
    assert 'name="q"' in inbox or 'type="search"' in inbox         # search
    assert "/opportunity/" in inbox
    assert re.search(r'action="/opportunity/\d+/status"', inbox), "no advance control"


# --------------------------------------------------------------------------- #
# The KPI and its destination
# --------------------------------------------------------------------------- #
def test_in_flight_lands_on_exactly_the_deals_it_counts(app_mod):
    """The KPI used to open the kanban, which showed every deal — Won and Closed
    included — so the number and the list under it disagreed by construction."""
    from chordential_oia.web import db

    with TestClient(app_mod.app) as c:
        dash = c.get("/dashboard").text
        m = re.search(r'href="([^"]+)"[^>]*>\s*<div class="kpi-cell-val">(\d+)</div>\s*'
                      r'<div class="kpi-cell-lbl">in flight', dash)
        assert m, "the in-flight KPI is not on the dashboard"
        href, counted = m.group(1), int(m.group(2))
        listed = len(set(re.findall(r"/opportunity/(\d+)", c.get(href).text)))
    assert listed == counted, (
        f"'in flight' counts {counted} but {href} lists {listed}")

    conn = db.connect()
    try:
        expected = conn.execute(
            "SELECT COUNT(*) FROM opportunities WHERE status IN ('Pursuing','Submitted')"
        ).fetchone()[0]
    finally:
        conn.close()
    assert counted == expected


def test_the_open_filter_is_the_pipeline_definition(app_mod):
    """`?status=open` reuses OPEN_PIPELINE_STATES (ADR-0030) rather than restating
    which stages count as in flight."""
    from chordential_oia.web import db

    conn = db.connect()
    try:
        rows = db.list_opportunities(conn, status="open")
        assert rows, "no in-flight deals on the seeded book — test proves nothing"
        assert {r["status"] for r in rows} <= set(db.OPEN_PIPELINE_STATES)
        every = {r["id"] for r in db.list_opportunities(conn)
                 if r["status"] in db.OPEN_PIPELINE_STATES}
        assert {r["id"] for r in rows} == every
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# The data hole the board carried
# --------------------------------------------------------------------------- #
def test_no_surface_marks_a_deal_won_without_its_value(app_mod):
    """The board's Won button, and the detail stepper's, both POSTed status=Won with
    no outcome_value — a won deal worth $0 in every revenue read. Neither ships a
    blind Won control now; the win/loss form, which carries the value field, does."""
    from pathlib import Path

    tpl = Path(app_mod.__file__).parent / "templates"
    for path in sorted(tpl.rglob("*.html")):
        src = path.read_text(encoding="utf-8")
        for form in re.findall(r"<form[^>]*/status\"[^>]*>.*?</form>", src, re.S):
            if 'value="Won"' in form:
                assert "outcome_value" in form, (
                    f"{path.name} can mark a deal Won without capturing its value")


def test_the_stepper_routes_a_win_to_the_form(app_mod):
    """Marking Won is a decision with a number attached, so the stepper hands off to
    the win/loss card rather than silently recording it."""
    with TestClient(app_mod.app) as c:
        opp_id = None
        for i in range(1, 25):
            r = c.post(f"/opportunity/{i}/status", data={"status": "Submitted"},
                       follow_redirects=False)
            if r.status_code == 303:
                opp_id = i
                break
        assert opp_id, "could not stage a Submitted deal"
        page = c.get(f"/opportunity/{opp_id}").text

    assert 'href="#winloss"' in page, "the stepper does not hand off to the win/loss form"
    assert 'id="winloss"' in page, "the win/loss card has no anchor to land on"
    winloss = page.split('id="winloss"')[1]
    assert 'name="outcome_value"' in winloss


def test_a_win_recorded_through_the_form_reaches_the_revenue_read(app_mod):
    """End to end: the value the operator types is what the won-value sum counts."""
    from chordential_oia.web import db

    with TestClient(app_mod.app) as c:
        c.post("/opportunity/3/status", data={"status": "Submitted"})
        c.post("/opportunity/3/status", data={"status": "Won", "outcome_value": "12000"})

    conn = db.connect()
    try:
        row = db.get_opportunity(conn, 3)
        won = conn.execute(
            "SELECT outcome_value FROM opportunities WHERE status = 'Won'").fetchall()
    finally:
        conn.close()
    assert row["status"] == "Won"
    assert row["outcome_value"] == 12000.0
    assert sum((r["outcome_value"] or 0) for r in won) >= 12000.0
