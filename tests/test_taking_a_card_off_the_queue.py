"""A queue you can actually clear, and a list that still tells the truth about it.

    "i want a way to delete things from the queue. also when i click 'open' on one of the
     things it doesnt take away from things that are pending even though i reacted to it"
                                                            — the operator, 2026-08-27

TWO THINGS, and only one of them is a bug.

**Open is navigation, and that is right.** Queue cards are COMPUTED — a card exists because
a REVIEW-tier opportunity is still flagged, or a signature is still uncountersigned. Making
Open clear a card would make the queue a liar: the decision would still be unmade and the
list would say otherwise, which is the single thing this surface must never do. A card
leaves when the thing it names actually happens.

**But there was no way to say "not mine".** The only button that made a card go away was
Snooze, which is temporary by design and returns everything. So it was being used as a
delete — fourteen cards "snoozed" on a queue reading two pending. That is the real gap: an
operator disposing of a decision by hiding it for a week, over and over.

Dismiss is that decision, made once. It does not expire, it does not touch what the card
pointed at, and it stays counted and reversible on the queue — because a list that hides
things without saying how many is the failure Dismiss exists to fix, not a smaller one.
"""
import importlib

import pytest

pytest.importorskip("fastapi")


@pytest.fixture()
def q(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "q.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "passphrase")
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    for m in ("db", "campaigns", "uploads", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod, db, queue as queue_mod
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    with TestClient(app_mod.app):
        pass
    c = TestClient(app_mod.app)
    c.cookies.set(ADMIN_COOKIE, admin_cookie_value("passphrase"))

    def view(**kw):
        conn = db.connect()
        try:
            return queue_mod.queue_view(conn, db, **kw)
        finally:
            conn.close()

    return c, view


def _first_key(view):
    v = view()
    assert v["groups"], "the seeded queue is empty; nothing to dismiss"
    return v["groups"][0]["cards"][0]["key"]


def test_a_dismissed_card_leaves_the_list(q):
    c, view = q
    before = view()["total"]
    c.post("/queue/dismiss", data={"key": _first_key(view), "next": "/queue"},
           follow_redirects=False)
    assert view()["total"] == before - 1


def test_a_dismissal_does_not_expire(q):
    """The whole difference from a snooze. Snoozing says "not now"; this says "not mine",
    and a decision that quietly un-decides itself in seven days is why snooze was being
    used as a delete in the first place."""
    c, view = q
    key = _first_key(view)
    c.post("/queue/dismiss", data={"key": key, "next": "/queue"}, follow_redirects=False)
    # Even asking to see everything the queue is holding back does not bring it out: that
    # switch is about SNOOZED cards, which is a different question.
    assert key not in {card["key"] for g in view(include_snoozed=True)["groups"]
                       for card in g["cards"]}


def test_the_queue_says_how_many_it_is_hiding(q):
    """A list that hides things without saying how many reads "2 pending" while nine
    decisions sit somewhere nobody can find them."""
    c, view = q
    c.post("/queue/dismiss", data={"key": _first_key(view), "next": "/queue"},
           follow_redirects=False)
    assert view()["dismissed"] == 1
    page = c.get("/queue").text
    assert "dismissed — off this list for good" in page
    assert "Bring them back" in page


def test_dismissed_and_snoozed_are_counted_apart(q):
    """Pooling them is how fourteen deferrals came to look like fourteen decisions. Two
    statements, two counts."""
    c, view = q
    v = view()
    keys = [card["key"] for g in v["groups"] for card in g["cards"]][:2]
    c.post("/queue/snooze", data={"key": keys[0], "days": "7", "next": "/queue"},
           follow_redirects=False)
    c.post("/queue/dismiss", data={"key": keys[1], "next": "/queue"},
           follow_redirects=False)
    after = view()
    assert after["snoozed"] == 1 and after["dismissed"] == 1


def test_everything_dismissed_can_come_back(q):
    c, view = q
    before = view()["total"]
    c.post("/queue/dismiss", data={"key": _first_key(view), "next": "/queue"},
           follow_redirects=False)
    c.post("/queue/undismiss", data={"next": "/queue"}, follow_redirects=False)
    assert view()["total"] == before and view()["dismissed"] == 0


def test_dismissing_changes_nothing_it_pointed_at(q):
    """It is a statement about the DECISION, not about the record. A REVIEW-tier
    opportunity dismissed here is still REVIEW-tier — it has just stopped being asked
    about, and an operator who later brings it back finds it exactly as it was."""
    from chordential_oia.web import db
    c, view = q
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT id, needs_review, status FROM opportunities "
            "WHERE needs_review = 1 LIMIT 1").fetchone()
    finally:
        conn.close()
    if row is None:
        pytest.skip("no REVIEW-tier opportunity in the seed")
    c.post("/queue/dismiss", data={"key": f"review_opp:/opportunity/{row['id']}",
                                   "next": "/queue"}, follow_redirects=False)
    conn = db.connect()
    try:
        after = conn.execute("SELECT needs_review, status FROM opportunities WHERE id=?",
                             (row["id"],)).fetchone()
    finally:
        conn.close()
    assert after["needs_review"] == row["needs_review"]
    assert after["status"] == row["status"]


def test_every_card_offers_the_button(q):
    c, view = q
    page = c.get("/queue").text
    shown = sum(len(g["cards"]) for g in view()["groups"])
    assert page.count(">Dismiss<") == shown


def test_a_blank_key_dismisses_nothing(q):
    """A hand-posted empty key must not create a row that hides nothing and counts as
    one — the count is what makes the hiding honest."""
    c, view = q
    before = view()["total"]
    c.post("/queue/dismiss", data={"key": "  ", "next": "/queue"}, follow_redirects=False)
    assert view()["total"] == before and view()["dismissed"] == 0


# ── the half that is not a bug ──────────────────────────────────────────────────────
def test_open_is_a_link_and_does_not_dispose_of_anything(q):
    """Reported as a fault and kept as behaviour. Cards are computed: a REVIEW card exists
    because `needs_review` is still 1. Clearing it on Open would leave the flag set and the
    list claiming otherwise — a queue that reads clear when it is not is the one thing this
    surface must never do. Dismiss is the way to say "I looked, and it is not mine"."""
    c, view = q
    v = view()
    card = next((card for g in v["groups"] for card in g["cards"]
                 if card["key"].startswith("review_opp:")), None)
    if card is None:
        pytest.skip("no REVIEW card in the seed")
    c.get(card["url"])
    assert card["key"] in {x["key"] for g in view()["groups"] for x in g["cards"]}


def test_a_card_leaves_when_the_decision_it_names_is_actually_made(q):
    """The other half of the same point: the queue is not stuck, it is honest. Clear the
    flag the card is computed from and the card goes."""
    from chordential_oia.web import db
    c, view = q
    v = view()
    card = next((card for g in v["groups"] for card in g["cards"]
                 if card["key"].startswith("review_opp:")), None)
    if card is None:
        pytest.skip("no REVIEW card in the seed")
    opp_id = int(card["url"].rsplit("/", 1)[1])
    conn = db.connect()
    try:
        conn.execute("UPDATE opportunities SET needs_review = 0 WHERE id = ?", (opp_id,))
        conn.commit()
    finally:
        conn.close()
    assert card["key"] not in {x["key"] for g in view()["groups"] for x in g["cards"]}


# ── what shipped, and what it cost ──────────────────────────────────────────────────
#
#     "dismissing gives an error, and a prompt asking me to click 'ok' get rid of it"
#                                                     — the operator, 2026-08-28
#
# Two faults from one press. The 500 is the interesting one: `INSERT OR REPLACE` is
# SQLite-only syntax, and PRODUCTION IS POSTGRES — so every Dismiss press answered
# `/queue/dismiss` with an Internal Server Error while all ten tests above stayed green,
# because the suite runs on SQLite. Nothing in the harness could see it.
def test_no_sqlite_only_insert_syntax_reaches_the_shared_db_layer():
    """The tripwire for the whole class, not just the line that broke.

    `_pg_translate` rewrites what it knows about — AUTOINCREMENT, BLOB, COLLATE NOCASE,
    IFNULL, GROUP_CONCAT, PRAGMA table_info, the placeholder. `INSERT OR REPLACE` and
    `INSERT OR IGNORE` are not in that list and cannot sensibly be added: the faithful
    translation depends on WHICH unique key you meant to conflict on, which a regex
    cannot know. So they are banned at the source instead, and the portable
    `ON CONFLICT(...) DO UPDATE/NOTHING` — which both engines accept, and which eleven
    other statements in `db.py` already use — is the only way to upsert here.

    Scanned over STRING LITERALS via the AST rather than by grepping lines, so the prose
    explaining the rule (this docstring, the comments at both fixed call sites) cannot
    trip it. A tripwire that fires on its own documentation gets deleted.
    """
    import ast
    import pathlib
    import re
    banned = re.compile(r"\bINSERT\s+OR\s+(REPLACE|IGNORE|ABORT|FAIL|ROLLBACK)\b"
                        r"|\bREPLACE\s+INTO\b", re.I)
    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "chordential_oia"
    offenders = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc is not None:
                    docstrings.add(id(node.body[0].value))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in docstrings and banned.search(node.value)):
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, (
        "SQLite-only INSERT syntax — Postgres rejects it and production is Postgres. "
        "Use ON CONFLICT(<unique key>) DO UPDATE SET … / DO NOTHING: " + ", ".join(offenders))


def test_the_dismiss_statement_is_an_upsert_that_both_engines_accept(q):
    """Pressing Dismiss twice on the same card must be a no-op, not a PRIMARY KEY
    violation — that is the behaviour `INSERT OR REPLACE` was buying, and the reason a
    bare `INSERT` is not the fix."""
    c, view = q
    key = view()["groups"][0]["cards"][0]["key"]
    for _ in range(2):
        r = c.post("/queue/dismiss", data={"key": key, "next": "/queue"},
                   follow_redirects=False)
        assert r.status_code == 303, f"Dismiss answered {r.status_code}"
    assert view()["dismissed"] == 1, "the second press wrote a second row"


def test_dismiss_does_not_stop_to_ask(q):
    """No `confirm()`. A modal is the guard for something that cannot be undone, and this
    can: the dismissed line counts every card and brings them back, and nothing the card
    points at is touched either way. On a 28-card queue the prompt turned clearing the
    list into 56 clicks."""
    c, _view = q
    page = c.get("/queue").text
    assert "confirm(" not in page, "the queue still stops to ask before a reversible press"
    # …and the way back is on the page, which is what makes asking unnecessary.
    assert "/queue/undismiss" in c.post(
        "/queue/dismiss",
        data={"key": _view()["groups"][0]["cards"][0]["key"], "next": "/queue"},
        follow_redirects=True).text
