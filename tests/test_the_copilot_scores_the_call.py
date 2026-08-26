"""Phase 1 of the Call Copilot: scoring a call that already happened.

`docs/discovery-copilot-plan.md` puts this phase before the live panel on purpose. It is
the MEASUREMENT step — "does detection actually work", answered against calls that already
happened, at zero risk and no new spend. Building the live version first would mean
finding out the detector is wrong while a client is on the line.

So these tests are mostly about the detector being WRONG in the cheap direction. The plan
names the failure explicitly:

    "It fires wrong. Marking something covered when it was not is worse than not being
     there, because it manufactures false confidence. Detection must be conservative:
     ambiguity leaves a line OPEN, not ticked. A missed tick costs one repeated question;
     a wrong tick costs a wrong proposal."

Three states, and they are three different claims — conflating them is how a tick becomes
a lie. `answered` = a value reached Campaign Intelligence from this call. `raised` = a
written cue matched a transcript line, so the topic came up; it does not claim an answer
landed. `missed` = neither.
"""
import importlib

import pytest

from chordential_oia.call_prep import prep_sheet, score_call

# A call run properly: every group on the sheet actually asked.
GOOD = """Jon: Before we start — who's with us today?
Priya: I'm Priya, brand lead.
Jon: I've got a notetaker running so I'm listening rather than typing.
Jon: I'll ask about the work, the sound, the plan and some boring commercial questions.
Jon: Before the music, what is this campaign trying to do for the business?
Priya: Launching Fieldhouse into a younger demographic.
Jon: What is the music's job inside the film specifically?
Priya: It carries the whole thing, there's no voiceover.
Jon: Talk me through every version you need.
Marco: A master, two cutdowns and socials. Stems too.
Jon: Walk me through how it should feel across the piece.
Priya: Starts quiet, builds to hopeful.
Jon: What are you listening to for this?
Priya: A lot of Johannsson. The temp track is the wrong direction.
Jon: What is the air date, and when do you need final delivery?
Marco: October 3rd, final delivery three weeks prior.
Jon: What is the approved number for music?
Priya: The budget is 55 to 65 thousand.
Jon: Who gives final approval on this?
Priya: Tom Vasquez.
Jon: Tell me how the brand shows up. What is it careful about?
Priya: Cautious about anything that reads as cheap.
Jon: How does your side actually work, who moves paper?
Marco: Legal team is slow, plan three weeks.
Jon: How long do you need the usage to run?
Priya: Two years from first air.
Jon: When that term is up, do you expect to renew?
Priya: Probably renew.
Jon: Where does the music actually run - broadcast, digital, social?
Priya: Broadcast and social, no cinema.
Jon: Where does this run? US only, or worldwide?
Priya: North America.
Jon: Do you need any exclusivity, category or otherwise?
Priya: Category exclusive for the term.
Jon: Is there an expectation about who holds publishing?
Priya: We'd want a share of publishing.
Jon: Will this need PRO registration, and do you have a cue sheet process?
Marco: Yes, we file the cue sheet.
Jon: What does your payment schedule usually look like?
Marco: Net 30 from invoice.
Jon: Any requirement about union or non-union players?
Priya: Non-union is fine.
Jon: Let me play back what I've got, and stop me where I'm wrong.
Jon: What haven't I asked about that I should have?
Priya: Nothing comes to mind.
Jon: You'll get a written summary today. Who else should be on it?
Priya: Add Tom.
"""

# A call where NONE of the sheet is covered, written to bait every loose cue that a first
# draft of the detector actually fell for. Each line below produced a false tick once.
BAIT = """Jon: How long have you been at the agency?
Priya: Three years. The brand team sits in New York.
Marco: Our terms of engagement with the production company are already signed.
Priya: We ran a global campaign last year that did well.
Jon: Is the edit locked?
Marco: Not yet, we're still cutting.
Priya: The music needs to feel exclusive and premium, if that makes sense.
Marco: Let's reconvene at 2:30 tomorrow.
Priya: We recorded a scratch vocal last week.
Jon: One year ago we'd have said no to this.
Marco: The European Union rules changed on that.
Priya: Their tone of voice guidelines are strict.
"""


def _by_label(score, label):
    return next(ln for ln in score.lines if ln.label == label)


# ── the failure the plan names first ────────────────────────────────────────────────
def test_a_call_that_covered_nothing_ticks_nothing():
    """Every line here was a real false positive during the build. A wrong tick is the
    one error this phase must not make, so the whole bait transcript scores zero."""
    score = score_call(prep_sheet({}), BAIT)
    ticked = [(ln.label, ln.evidence) for ln in score.lines if ln.covered]
    assert ticked == [], f"detector fired on a call that covered none of it: {ticked}"


def test_feeling_exclusive_is_not_the_exclusivity_term():
    """The most expensive false tick available. `exclusiv` as a bare stem matched
    "the music needs to feel exclusive and premium" — a creative adjective — and would
    have reported a priced rights term as handled."""
    score = score_call(prep_sheet({}), BAIT)
    assert _by_label(score, "Exclusivity").state == "missed"


def test_a_time_of_day_is_not_a_deliverable_and_a_year_ago_is_not_a_term():
    score = score_call(prep_sheet({}), BAIT)
    assert _by_label(score, "Deliverables").state == "missed"
    assert _by_label(score, "Licence term").state == "missed"
    assert _by_label(score, "Musicians").state == "missed"      # "European Union"
    assert _by_label(score, "Emotional arc").state == "missed"  # "tone of voice"


# ── and it must still detect a call that DID cover it ───────────────────────────────
def test_a_well_run_call_scores_everything():
    """A detector that never fires is safe and useless. The other half of the test."""
    score = score_call(prep_sheet({}), GOOD)
    assert score.missed == 0, f"still missing: {[l.label for l in score.missed_lines]}"
    assert score.pct == 100


def test_the_evidence_is_the_line_that_matched():
    """A tick you cannot check is the thing this repository keeps having to unbuild. Every
    covered line carries the verbatim sentence that produced it."""
    score = score_call(prep_sheet({}), GOOD)
    for ln in score.lines:
        if ln.state == "raised":
            assert ln.evidence and ln.evidence in GOOD, ln


# ── the three states are three different claims ─────────────────────────────────────
def test_a_value_on_file_outranks_a_cue_in_the_transcript():
    score = score_call(prep_sheet({}), GOOD, answered={"budget_band": "$55-65k ceiling"})
    line = _by_label(score, "Budget")
    assert line.state == "answered"
    assert line.evidence == "$55-65k ceiling"


def test_a_conversation_question_can_never_be_answered():
    """The opening and the wrap-up have no Campaign Intelligence slot to land in, so they
    can only ever reach `raised`. Reporting one as `answered` would mean a slot key
    collided with a topic slug."""
    score = score_call(prep_sheet({}), GOOD,
                       answered={"recap": "yes", "unasked": "nothing"})
    assert _by_label(score, "Read it back").state == "raised"
    assert _by_label(score, "What I didn't ask").state == "raised"
    # …while a PRICED term is a slot now, and does reach `answered`. The licence terms
    # stopped being conversation the day a wrong one could be corrected and move the
    # quote.
    priced = score_call(prep_sheet({}), GOOD, answered={"license_term": "2 years"})
    assert _by_label(priced, "Licence term").state == "answered"


def test_raised_is_not_reported_as_a_failed_slot(prep):
    """Fourteen lines on the sheet are conversation — the opening, the terms, the wrap-up
    — with no Campaign Intelligence slot to land in. The headline said "raised without an
    answer landing", which read as twenty failures when most were questions doing their
    job. The claim only holds for the slots, and it is made where it holds."""
    c, _app, db, opp_id = prep
    _file_a_call(db, opp_id, GOOD)
    page = c.get(f"/opportunity/{opp_id}/prep").text
    assert "raised without an answer landing" not in page
    assert "Asked, but nothing stuck" in page


def test_asked_but_nothing_stuck_is_reported_on_its_own():
    """The interesting cell, and the reason this is worth building rather than counting CI
    fields: a question that WAS asked and whose answer did not land needs a different fix
    from one nobody asked."""
    score = score_call(prep_sheet({}), GOOD, answered={"budget_band": "$55-65k"})
    labels = [ln.label for ln in score.raised_lines]
    assert "Budget" not in labels
    assert "Timeline" in labels          # asked on the call, no value on file
    # Conversation questions are not slots and must not be listed as unfilled ones.
    assert "Read it back" not in labels


def test_a_missed_line_carries_the_question_to_ask_next_time():
    score = score_call(prep_sheet({}), BAIT)
    line = _by_label(score, "Licence term")
    assert line.ask and line.ask.endswith("?")


def test_the_headline_reads_like_the_plan_said_it_would():
    score = score_call(prep_sheet({}), BAIT)
    assert score.text.startswith("0 of 25 covered; missed ")
    assert "licence term" in score.text
    assert score_call(prep_sheet({}), GOOD).text.endswith("everything came up")


def test_scoring_is_deterministic():
    """A coverage number is only worth watching over time if the same transcript scores
    the same way twice. No model, no sampling, no clock."""
    a = score_call(prep_sheet({}), GOOD, answered={"deadline": "Oct 3"})
    b = score_call(prep_sheet({}), GOOD, answered={"deadline": "Oct 3"})
    assert [(l.key, l.state, l.evidence) for l in a.lines] == \
           [(l.key, l.state, l.evidence) for l in b.lines]


def test_an_empty_transcript_is_all_missed_not_a_crash():
    for empty in ("", "   ", "\n\n"):
        score = score_call(prep_sheet({}), empty)
        assert score.missed == score.total == 25


# ── on the page ─────────────────────────────────────────────────────────────────────
@pytest.fixture()
def prep(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "d.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "passphrase")
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    for m in ("db", "campaigns", "uploads", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod, db
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    with TestClient(app_mod.app):
        pass
    c = TestClient(app_mod.app)
    c.cookies.set(ADMIN_COOKIE, admin_cookie_value("passphrase"))
    conn = db.connect()
    try:
        opp = conn.execute("SELECT id FROM opportunities ORDER BY id LIMIT 1").fetchone()
        opp_id = int(opp["id"])
    finally:
        conn.close()
    return c, app_mod, db, opp_id


def _file_a_call(db, opp_id, transcript, *, fields=(), questions=()):
    from chordential_oia.web import campaign_intelligence as ci
    conn = db.connect()
    try:
        row = db.ci_for_opportunity(conn, opp_id)
        ci_id = int(row["id"]) if row is not None else int(
            ci.ensure_for_opportunity(conn, db.get_opportunity(conn, opp_id))["id"])
        cap = db.insert_capture(
            conn, ci_id=ci_id, campaign_id=0, opp_id=opp_id, lane="discovery_call",
            stance="objective", modality="transcript", provenance_source="discovery_call",
            raw_text=transcript, extraction=[], artifact_ref="", external_ref="",
            metadata={}, status="ingested", created_by="test")
        for key, value in fields:
            ci.contribute(conn, ci_id, "engagement", key, value, kind="fact",
                          source="discovery_call", contributed_by="test", capture_id=cap)
        for key, value in questions:
            ci.contribute(conn, ci_id, "engagement", key, value, kind="open_question",
                          source="ai", contributed_by="ai", capture_id=cap)
        conn.commit()
        return cap
    finally:
        conn.close()


def test_no_transcript_means_no_score_at_all(prep):
    """Phase 0 stands alone. A sheet with nothing to score against must not grow an empty
    scoreboard — an unfinished copilot has to leave the operator no worse off."""
    c, _app, _db, opp_id = prep
    page = c.get(f"/opportunity/{opp_id}/prep")
    assert page.status_code == 200
    assert "How the call went" not in page.text


def test_the_score_appears_on_the_same_sheet(prep):
    """Same page, same lines, before and after — because the panel Phase 2 builds is this
    sheet with the score arriving live. A separate report now is a second thing to
    unbuild later."""
    c, _app, db, opp_id = prep
    _file_a_call(db, opp_id, GOOD)
    page = c.get(f"/opportunity/{opp_id}/prep").text
    assert "How the call went" in page
    assert "25 of 25 covered" in page
    # Evidence is the matching SENTENCE, printed verbatim so the tick can be argued with.
    assert "US only, or worldwide?" in page


def test_the_machines_own_open_questions_are_not_answers(prep):
    """`ask_*` rows are Campaign Intelligence noticing a slot is EMPTY. Counting one as a
    filled slot would tick a line precisely because nobody answered it."""
    c, _app, db, opp_id = prep
    _file_a_call(db, opp_id, GOOD,
                 questions=[("ask_territory", "What territory does this run in?")])
    page = c.get(f"/opportunity/{opp_id}/prep").text
    assert "<b>0</b> answered" in page
    from chordential_oia.web.opportunity_routes import _scored_call
    conn = db.connect()
    try:
        assert "ask_territory" not in _scored_call(conn, opp_id)["answered"]
    finally:
        conn.close()


def test_a_filed_value_shows_as_answered_on_the_page(prep):
    c, _app, db, opp_id = prep
    _file_a_call(db, opp_id, GOOD, fields=[("budget_band", "$55-65k, ceiling")])
    page = c.get(f"/opportunity/{opp_id}/prep").text
    assert "$55-65k, ceiling" in page
    assert "<b>1</b> answered" in page


def test_the_newest_call_is_the_one_scored(prep):
    """A second discovery call is a second call. The sheet reports the one that just
    happened, not an average of every conversation ever had."""
    c, _app, db, opp_id = prep
    _file_a_call(db, opp_id, BAIT)
    _file_a_call(db, opp_id, GOOD)
    assert "25 of 25 covered" in c.get(f"/opportunity/{opp_id}/prep").text


def test_scoring_never_re_reads_the_transcript_with_a_model(prep, monkeypatch):
    """Phase 1's whole promise is "zero risk and no new spend". The extraction already ran
    and its results are on file citing that capture; asking a model to read the same
    transcript again would spend money to learn something we are holding."""
    from chordential_oia.web import campaign_intake, extraction_bridge
    c, _app, db, opp_id = prep
    _file_a_call(db, opp_id, GOOD)

    def _explode(*a, **kw):
        raise AssertionError("the prep sheet re-ran extraction")

    monkeypatch.setattr(campaign_intake, "reanalyze_capture", _explode)
    monkeypatch.setattr(campaign_intake, "ingest", _explode, raising=False)
    monkeypatch.setattr(extraction_bridge, "for_capture", _explode, raising=False)
    assert c.get(f"/opportunity/{opp_id}/prep").status_code == 200
