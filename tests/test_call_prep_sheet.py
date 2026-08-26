"""The prep sheet: the questions, before the call rather than after it.

Phase 0 of `docs/discovery-copilot-plan.md`. The Halden brief closed with fourteen open
questions; every one was findable during the call, and nine were licence and rights terms
that take forty seconds each to ask. The machine's whole contribution arrived after everyone
had hung up, as a list of things it was by then too late to ask.

No live component, no model call, no spend. If a written sheet does not make the next call
better, no amount of real-time streaming would have, and this is the cheapest way to learn
that.
"""
import importlib

import pytest

from chordential_oia.call_prep import coverage, prep_sheet
from chordential_oia.client_voice import _DEFERRABLE_TOPICS
from chordential_oia.models import BuyerType, MusicRequirement, Opportunity
from chordential_oia.web.campaign_intelligence import CANONICAL_FIELDS

pytest.importorskip("fastapi")


# ── the bank covers what actually gets missed ────────────────────────────────────
def test_every_canonical_slot_has_a_question():
    """A slot with no question is a field that can only ever be filled by luck."""
    asked = {ln.key for g in prep_sheet() for ln in g.lines}
    for _facet, key, _kind, label, _ph, _opp in CANONICAL_FIELDS:
        assert key in asked, f"no question on the sheet fills {label} ({key})"


def test_every_recurring_deferred_term_has_a_question():
    """These are the nine that ended up in the client's inbox as a form. They are on the
    sheet precisely so they stop being asked by email.

    This test earned its keep immediately: renewal had been folded into the licence-term
    follow-up, which meant it was only ever asked when the first answer came back partial.
    That is precisely how it was skipped on the live call. It has its own line now."""
    sheet_text = " ".join(
        " ".join((ln.label, ln.key, ln.ask, ln.follow_up)).lower()
        for g in prep_sheet() for ln in g.lines)
    for label, _needles in _DEFERRABLE_TOPICS:
        head = label.split()[0].lower().rstrip(",")
        assert head in sheet_text, f"the sheet never asks about {label}"


def test_the_sheet_runs_the_arc_of_a_call_from_open_to_wrap_up():
    """Ordered as a conversation, not as a schema. A call that starts without a frame gets
    guarded answers to the commercial questions, and one that ends without a read-back
    ships whatever was misheard."""
    titles = [g.title for g in prep_sheet()]
    assert titles == ["Open the call", "The work", "The sound", "The plan",
                      "The people", "The terms", "Wrap up"]


def test_the_terms_are_late_but_not_last():
    """Late because they are what gets dropped when a call runs long; not last, because a
    wrap-up behind them is what catches the cost of dropping them."""
    titles = [g.title for g in prep_sheet()]
    assert titles.index("The terms") > titles.index("The plan")
    assert titles.index("The terms") < titles.index("Wrap up")


def test_conversation_moves_fill_no_intelligence_slot():
    """The opening and the wrap-up are conversation, not fields. Marking them canonical
    would have the sheet claim it captures things it does not.

    "The terms" USED to be listed here too, and is now split down the middle. Four of its
    questions — media, territory, licence term, exclusivity — are PRICED
    (`pricing.licence_from_ci` → `build_quote`), and were made real slots so the operator
    can correct what the call got wrong and have the quote follow. The other five are
    still conversation: renewal, publishing, PRO registration, payment terms and musician
    status change what we agree to, not what we charge, and inventing slots for them would
    be the same overclaim in the other direction."""
    groups = {g.title: g for g in prep_sheet()}
    for title in ("Open the call", "Wrap up"):
        assert all(not ln.canonical for ln in groups[title].lines), title
    for title in ("The work", "The sound", "The plan", "The people"):
        assert all(ln.canonical for ln in groups[title].lines), title
    terms = {ln.key: ln.canonical for ln in groups["The terms"].lines}
    assert {k for k, v in terms.items() if v} == {
        "media", "territory", "license_term", "exclusivity"}, (
        "the priced terms and the conversational ones have drifted apart")


def test_the_call_opens_by_asking_permission_to_record():
    """Out loud, every time. Some places require both sides to agree, and a recording
    nobody consented to is worth less than no recording."""
    opener = prep_sheet()[0]
    assert any("notetaker" in ln.ask.lower() for ln in opener.lines)
    assert any("alright with you" in ln.ask.lower() or "is that ok" in ln.ask.lower()
               for ln in opener.lines)


def test_the_call_closes_by_reading_it_back():
    """The cheapest moment to catch a wrong number is while the person who knows it is
    still on the line."""
    closer = prep_sheet()[-1]
    keys = {ln.key for ln in closer.lines}
    assert {"recap", "unasked", "next_step"} <= keys


def test_every_question_is_a_sentence_you_could_say_out_loud():
    """Not a topic label. A rep reading "Budget" off a sheet asks a worse question than a
    rep reading the sentence we wrote for them."""
    for g in prep_sheet():
        for ln in g.lines:
            assert ln.ask.endswith(("?", ".")), f"{ln.key}: not a sentence"
            assert len(ln.ask.split()) >= 5, f"{ln.key}: that is a label, not a question"
            assert ln.follow_up, f"{ln.key}: no follow-up for a partial answer"
            assert ln.why, f"{ln.key}: no reason a rep can weigh"


# ── what we already hold changes the question, it does not remove it ─────────────
def test_a_known_slot_becomes_a_read_back_rather_than_disappearing():
    """The failure this product keeps having is a value captured confidently and WRONGLY.
    Dropping known slots from the sheet would hide exactly that, and the only cheap moment
    to catch it is while the person who knows is still on the line."""
    sheet = prep_sheet({"budget_band": "$55,000-$65,000 USD, hard ceiling"})
    line = next(ln for g in sheet for ln in g.lines if ln.key == "budget_band")
    assert line.state == "have"
    assert "$55,000-$65,000 USD, hard ceiling" in line.prompt
    assert "Read it back" in line.prompt
    assert line.ask, "and the original question is still there if the read-back is wrong"


def test_an_unknown_slot_asks_the_written_question():
    line = next(ln for g in prep_sheet({}) for ln in g.lines if ln.key == "budget_band")
    assert line.state == "ask"
    assert line.prompt == line.ask
    assert "MUSIC number" in line.why, (
        "the budget question must warn about the distractor that already cost us once")


def test_either_deadline_key_satisfies_the_timeline_question():
    """`critical_deadline` and `deadline` are the same question to a human."""
    line = next(ln for g in prep_sheet({"critical_deadline": "Oct 3"})
                for ln in g.lines if ln.key == "deadline")
    assert line.state == "have" and "Oct 3" in line.prompt


def test_coverage_counts_what_we_hold_not_what_is_true():
    sheet = prep_sheet({"budget_band": "x", "deadline": "y"})
    cover = coverage(sheet)
    assert cover["have"] == 2
    assert cover["ask"] == cover["total"] - 2
    assert cover["total"] == sum(len(g.lines) for g in sheet)
    assert 0 <= cover["pct"] <= 100
    assert coverage(prep_sheet({}))["pct"] == 0


# ── it reaches the operator where the call is ────────────────────────────────────
@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "prep.db"))
    monkeypatch.setenv("CHORDENTIAL_CAMPAIGN_WORKSPACE", "1")
    monkeypatch.delenv("CHORDENTIAL_ADMIN_TOKEN", raising=False)
    for m in ("db", "campaign_intelligence", "campaigns", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod
    with TestClient(app_mod.app) as c:
        yield c


def _opp_with(ci_facts=()):
    from chordential_oia.web import campaign_intelligence as ci
    from chordential_oia.web import db
    conn = db.connect()
    try:
        oid = db.insert_opportunity(conn, Opportunity(
            client="Halden", need="40th anniversary film", description="",
            buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL))
        row = db.get_opportunity(conn, oid)
        ci_id = ci.ensure_for_opportunity(conn, row)["id"]
        for facet, key, value in ci_facts:
            ci.edit_or_create(conn, ci_id, facet, key, "fact", value, actor="operator")
        return oid
    finally:
        conn.close()


def test_the_page_serves_and_carries_the_written_questions(client):
    oid = _opp_with()
    page = client.get(f"/opportunity/{oid}/prep").text
    assert "Call prep" in page
    assert "How long do you need the usage to run?" in page
    assert "What is the approved number for music?" in page
    assert "Where does this run? US only, or worldwide?" in page


def test_the_page_reads_back_what_intelligence_already_holds(client):
    oid = _opp_with([("engagement", "budget_band", "$55,000-$65,000 USD, hard ceiling")])
    page = client.get(f"/opportunity/{oid}/prep").text
    assert "$55,000-$65,000 USD, hard ceiling" in page
    assert "Read it back" in page
    assert "On file" in page


def test_it_is_reachable_from_the_meeting_card(client):
    """It is worth nothing on a page nobody opens before a call."""
    from chordential_oia.web import db
    oid = _opp_with()
    conn = db.connect()
    try:
        db.create_meeting(conn, opp_id=oid, start_at="2026-09-20T15:00:00+00:00",
                          join_url="https://zoom.example/j/1", meeting_type="zoom")
    finally:
        conn.close()
    detail = client.get(f"/opportunity/{oid}").text
    assert f"/opportunity/{oid}/prep" in detail
    assert "Call prep" in detail


def test_it_is_reachable_before_any_call_is_booked(client):
    """The meeting card is the natural home for it and was the ONLY home for it, so a
    deal typed in by hand — which has no meeting until you book one — showed no way to
    reach the prep sheet at all. That is backwards: the deals with nothing in the diary
    are the ones you have not prepared for."""
    detail = client.get(f"/opportunity/{_opp_with()}").text
    assert "Create discovery call" in detail, "sanity: no meeting exists on this deal"
    assert "Reschedule" not in detail, "sanity: the meeting card is genuinely absent"
    assert "Call prep" in detail


def test_an_unknown_opportunity_is_a_404_not_a_crash(client):
    assert client.get("/opportunity/99999/prep").status_code == 404


def test_the_sheet_costs_nothing_to_render(client, monkeypatch):
    """Phase 0 spends no credit, by construction. A prep sheet that calls a model is a
    prep sheet that costs money every time you open it before a call."""
    from chordential_oia.web import ai_budget
    spent = []
    monkeypatch.setattr(ai_budget, "record", lambda *a, **k: spent.append(a))
    oid = _opp_with([("engagement", "deadline", "Oct 3")])
    assert client.get(f"/opportunity/{oid}/prep").status_code == 200
    assert spent == []


# ── the console's own ergonomics ─────────────────────────────────────────────────
def test_disposing_a_field_returns_to_that_field_not_the_top(client):
    """Reported live: pressing "Mark answered" threw the page back to the section
    heading, a screen or more above the line just pressed. Ten dispositions meant ten
    scrolls back down, losing your place each time."""
    from chordential_oia.web import campaign_intelligence as ci
    from chordential_oia.web import db
    oid = _opp_with()
    conn = db.connect()
    try:
        ci_id = db.ci_for_opportunity(conn, oid)["id"]
        # NOT an `ask_*` key: those route to the gaps section, which already has an
        # inline answer box. The questions carrying "Mark answered" are the ones in the
        # producer's read, and those have only the dispose button.
        fid = ci.contribute(conn, ci_id, "commercial", "stem_count",
                            "Confirm the stem count for social.", kind="open_question",
                            source="discovery_call")
    finally:
        conn.close()
    r = client.post(f"/opportunity/{oid}/intelligence/dispose",
                    data={"field_id": str(fid)}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].endswith(f"#ci-{fid}"), r.headers["location"]

    page = client.get(f"/opportunity/{oid}").text
    assert f'id="ci-{fid}"' in page, "the anchor must exist on the item it points at"


def test_an_open_question_offers_an_answer_box_not_just_a_close_button(client):
    """"Mark answered" used to close the question and keep NOTHING, so the answer
    evaporated at the moment somebody actually knew it. Answered now means answered: the
    text is recorded as a fact. "Dismiss" remains for questions that will never have one,
    and says plainly that it records nothing."""
    from chordential_oia.web import campaign_intelligence as ci
    from chordential_oia.web import db
    oid = _opp_with()
    conn = db.connect()
    try:
        ci_id = db.ci_for_opportunity(conn, oid)["id"]
        ci.contribute(conn, ci_id, "commercial", "territory",
                      "Where does this run?", kind="open_question", source="discovery_call")
    finally:
        conn.close()
    page = client.get(f"/opportunity/{oid}").text
    assert f"/opportunity/{oid}/intelligence/answer" in page
    assert "it's kept as a fact" in page
    assert "Dismiss" in page and "Nothing is recorded." in page


def test_the_section_nav_sits_with_the_title_it_navigates(client):
    """Every other page in this group renders it on line 7. Only the Overview had it near
    the foot, so reaching Budget estimate meant scrolling past the whole page first."""
    oid = _opp_with()
    page = client.get(f"/opportunity/{oid}").text
    nav = page.index("Qualification rationale")
    first_section = page.index('class="card')
    assert nav < first_section, "the tabs must come before the page content, not after it"
