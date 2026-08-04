"""The client portal answers the court question first, and orders itself by it.

ADR-0019 ratified that "the client-facing production experience must always answer the
court question first". `production.court_state()` has computed that answer — including
the client-voice sentence — since then; the portal rendered **none** of it.

Measured on the seeded book before this change:

* **Lumen Health** (court=`studio`, nothing needed from the client) and **Vance
  Athletic** (court=`client`, v2 genuinely waiting) rendered the *identical* page —
  card order `[picture, review, brief]` on both, the same "Review & approve" call to
  action, differing only in a hero chip reading our internal state machine
  ("In production · v1 Concept" vs "In review · v2 Direction-lock").
* Lumen has **zero versions**. Its portal still said *"v1 Concept — leave time-stamped
  notes, then approve or request changes"* and offered a Request-changes form. That
  label is `revision_status`'s **default**, not a fact: the page named a version that
  had never been delivered, and invited a contractual revision round (ADR-0019's
  `round_log`) against work that did not exist.

ADR-0036. One engine, one sentence, rendered where the client reads it.
"""

import html as H
import importlib
import re

import pytest

from chordential_oia.web import production

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def app_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "portal.db"))
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as mod
    importlib.reload(mod)
    with TestClient(mod.app):
        pass
    return mod


def _portals(app_mod):
    """Every seeded project with a share token → (id, client, court, portal html)."""
    from chordential_oia.web import db

    conn = db.connect()
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM projects ORDER BY id")]
        courts, tokens = {}, {}
        for r in rows:
            tokens[r["id"]] = r["share_token"] or db.ensure_project_share_token(conn, r["id"])
            courts[r["id"]] = production.court_state(r, db.get_delivery(conn, r["id"]) or {})
    finally:
        conn.close()

    out = []
    with TestClient(app_mod.app) as c:
        for r in rows:
            resp = c.get(f"/project/{r['id']}/delivery-portal?k={tokens[r['id']]}")
            if resp.status_code == 200:
                out.append((r["id"], r["client"], courts[r["id"]], resp.text))
    return out


def _cards(html):
    return re.findall(r'<div class="(?:card|ready)[^"]*" id="([^"]+)"', html)


def _badge(html):
    m = re.search(r'<span class="court-badge">([^<]*)</span>', html)
    return m.group(1).strip() if m else None


def _says(html, sentence):
    """The rendered page carries `sentence` — compared through unescaping, since
    Jinja escapes the apostrophes the concierge voice is full of."""
    return sentence in H.unescape(html)


# --------------------------------------------------------------------------- #
# It answers the question
# --------------------------------------------------------------------------- #
def test_every_portal_states_whose_court_the_ball_is_in(app_mod):
    portals = _portals(app_mod)
    assert len(portals) >= 3, "not enough seeded portals to prove anything"
    for pid, client, court, html in portals:
        assert _badge(html), f"project {pid} ({client}) never says whose court it is in"
        assert _says(html, court["line"]), (
            f"project {pid}: the portal does not render the engine's own sentence")


def test_the_hero_speaks_the_clients_language_not_our_state_machine(app_mod):
    """The slot used to read "In production · v1 Concept" — a delivery state and a
    version label, neither of which answers "what do I need to do?"."""
    for pid, client, court, html in _portals(app_mod):
        hero = html.split("</section>")[0]
        assert "court-badge" in hero, f"project {pid}: the court answer is not in the hero"
        assert _says(hero, court["line"]), f"project {pid}: the answer is not in the hero"


def test_the_badge_comes_from_the_engine(app_mod):
    """One home for the wording, so the portal and the workspace cannot drift."""
    for pid, client, court, html in _portals(app_mod):
        assert _badge(html) == court["badge"]


def test_two_courts_do_not_render_the_same_page(app_mod):
    """The headline finding: a project needing nothing from the client and a project
    with a version waiting were indistinguishable apart from an internal chip."""
    seen = {}
    for pid, client, court, html in _portals(app_mod):
        seen.setdefault(court["court"], []).append((pid, _badge(html), tuple(_cards(html))))
    assert len(seen) >= 2, "the seed no longer covers two court states"
    signatures = {c: {(b, cards) for _pid, b, cards in v} for c, v in seen.items()}
    for a in signatures:
        for b in signatures:
            if a < b:
                assert not (signatures[a] & signatures[b]), (
                    f"courts {a!r} and {b!r} render an identical page")


# --------------------------------------------------------------------------- #
# It orders itself by the answer
# --------------------------------------------------------------------------- #
def test_when_it_is_the_clients_move_the_review_leads(app_mod):
    checked = 0
    for pid, client, court, html in _portals(app_mod):
        if court["court"] != "client":
            continue
        cards = _cards(html)
        assert "review" in cards, f"project {pid}: nothing to act on despite YOUR MOVE"
        assert cards.index("review") == 0, (
            f"project {pid}: the client owes a review but {cards[0]!r} leads the page")
        checked += 1
    assert checked, "no seeded project is in the client's court"


def test_while_we_compose_the_useful_thing_leads(app_mod):
    """Nothing is owed, so the page leads with what actually helps — sending us the
    cut — rather than a review call-to-action for work that isn't ready."""
    checked = 0
    for pid, client, court, html in _portals(app_mod):
        if court["court"] != "studio":
            continue
        cards = _cards(html)
        if "picture" in cards and "review" in cards:
            assert cards.index("picture") < cards.index("review"), (
                f"project {pid}: a review CTA leads while the ball is with the studio")
            checked += 1
    assert checked, "no seeded project is in the studio's court with both cards"


def test_a_delivered_campaign_leads_with_the_package(app_mod):
    checked = 0
    for pid, client, court, html in _portals(app_mod):
        if court["court"] != "scheduled":
            continue
        cards = _cards(html)
        if "package" in cards:
            assert cards.index("package") == 0
            checked += 1
    assert checked, "no seeded project is delivered"


# --------------------------------------------------------------------------- #
# It does not invite a reaction to work that does not exist
# --------------------------------------------------------------------------- #
def test_a_project_with_no_versions_names_none(app_mod):
    """`revision_status`'s default is "v1 Concept". Rendering it on a project with an
    empty version ladder told the client a version had been delivered."""
    from chordential_oia.web import db
    from chordential_oia import delivery as D

    conn = db.connect()
    try:
        empty = [r["id"] for r in conn.execute("SELECT * FROM projects")
                 if not D.versions_list(db.get_delivery(conn, r["id"]) or {})]
    finally:
        conn.close()
    assert empty, "no seeded project has an empty version ladder — test proves nothing"

    for pid, client, court, html in _portals(app_mod):
        if pid not in empty:
            continue
        assert "v1 Concept" not in html, (
            f"project {pid} names a version it has never delivered")
        assert "approve or request changes" not in html


def test_no_revision_round_can_be_opened_against_nothing(app_mod):
    """Request-changes writes to the round ledger, which has contractual meaning
    (ADR-0019). It may not be offered before a version exists."""
    from chordential_oia.web import db
    from chordential_oia import delivery as D

    conn = db.connect()
    try:
        empty = [r["id"] for r in conn.execute("SELECT * FROM projects")
                 if not D.versions_list(db.get_delivery(conn, r["id"]) or {})]
    finally:
        conn.close()

    for pid, client, court, html in _portals(app_mod):
        if pid in empty:
            assert "/review/changes" not in html, (
                f"project {pid} offers a revision round with no version to revise")


def test_the_empty_room_claims_nothing_it_cannot_back(app_mod):
    """Narrow the removal to what was actually wrong: the phantom version label, the
    round counter, and the decision controls. (The timecoded comment form was already
    gated on a track before this change — a note needs a timeline to land on.)"""
    from chordential_oia.web import db
    from chordential_oia import delivery as D

    conn = db.connect()
    try:
        empty = [r["id"] for r in conn.execute("SELECT * FROM projects")
                 if not D.versions_list(db.get_delivery(conn, r["id"]) or {})]
    finally:
        conn.close()

    checked = 0
    for pid, client, court, html in _portals(app_mod):
        if pid not in empty or "review" not in _cards(html):
            continue
        card = html.split('id="review"')[1]
        assert "listening room" in card.lower(), "the section still claims something to approve"
        assert "Round" not in card.split("</h2>")[0], (
            "a round counter is shown for a version that was never delivered")
        assert "rc-approve" not in card, "an Approve control with nothing to approve"
        checked += 1
    assert checked, "no empty-ladder portal rendered the listening room"
