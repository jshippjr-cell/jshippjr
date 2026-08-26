"""Phase 2 of the Call Copilot: the panel that raises its hand while the call is running.

`docs/discovery-copilot-plan.md` names four ways this fails before it names anything it
should do, and those four are what most of this file tests:

    "It becomes a script."      → the panel never blocks, nags or beeps.
    "It fires wrong."           → ambiguity leaves a line OPEN. A wrong tick manufactures
                                  false confidence, which is worse than no panel.
    "It costs per minute."      → a hard per-call ceiling, checked BEFORE the spend, and
                                  the panel says plainly when it stops rather than going
                                  quiet.
    "It leaks."                 → nothing here is reachable by a client, ever.

The fifth thing worth pinning is not from the plan but from building it: the free tier
carries the panel. Phase 1's written cues cost nothing to run, so ✓/○ against every line
works with no API key at all — and the paid tier is what turns "budget came up" into
"$55–65k, hard ceiling".
"""
import importlib
import json
import os

import pytest

from chordential_oia import call_copilot as C
from chordential_oia.call_prep import prep_sheet


def _panel(**kw):
    return C.new_panel(prep_sheet({}), **kw)


def _say(text, at=10.0, who="Priya"):
    return C.Utterance(at_s=at, speaker=who, text=text)


# ── the engine ──────────────────────────────────────────────────────────────────────
def test_a_covered_line_keeps_the_sentence_that_covered_it():
    """A tick you cannot check is worse than no tick — the whole risk of a live panel is
    manufactured confidence."""
    p = _panel()
    C.observe(p, [_say("What is the approved number for music?", at=61.0, who="Jon")])
    line = p.line("budget_band")
    assert line.state == C.RAISED
    assert line.evidence == "What is the approved number for music?"
    assert line.at_s == 61.0


def test_ambiguity_leaves_a_line_open():
    """Phase 1's bait sentences, live. `exclusiv` as a bare stem once ticked the priciest
    term on the sheet off "the music needs to feel exclusive and premium"."""
    p = _panel()
    C.observe(p, [_say("The music needs to feel exclusive and premium."),
                 _say("The brand team sits in New York."),
                 _say("Let's reconvene at 2:30 tomorrow.")])
    assert p.covered == []


def test_the_work_shrinks_as_the_call_runs():
    """The plan's cost rule, and it applies to the free tier too: a covered line is never
    looked for again, so a long call does less work per minute, not more."""
    p = _panel()
    C.observe(p, [_say("Where does this run, US only or worldwide?", who="Jon")])
    before = p.line("territory").evidence
    C.observe(p, [_say("Worldwide would be nice one day.", at=900.0)])
    assert p.line("territory").evidence == before, "a covered line was re-matched"


def test_a_slot_we_already_hold_is_not_pre_ticked():
    """The prep sheet turns a known slot into a READ-BACK rather than dropping it, because
    a value captured confidently and wrongly is the failure this product keeps having. A
    panel that pre-ticks what we hold is that failure with a green mark on it."""
    p = _panel()
    assert p.line("budget_band").state == C.OPEN
    assert len(p.not_yet) == len(p.lines)


def test_a_second_answer_raises_a_conflict_instead_of_overwriting():
    """The plan's own worked example. Overwriting is the failure it describes: the machine
    keeps whichever it heard last and nobody is ever asked which is right."""
    p = _panel()
    found = C.apply_values(p, {"decision_makers": "Tom Vasquez"},
                           on_file={"decision_makers": "Haiden Jones"})
    assert [c.question for c in found] == ["Haiden Jones, or Tom Vasquez?"]
    assert p.line("decision_makers").value == "Tom Vasquez"


def test_the_same_answer_said_differently_is_not_a_conflict():
    """A ⚠ the operator has to dismiss is a panel that nags, and a panel that nags gets
    ignored — which costs more than the ⚠ was worth."""
    p = _panel()
    assert not C.apply_values(p, {"deadline": "October 3rd"},
                              on_file={"deadline": "October 3"})
    assert not p.conflicts


def test_a_conflict_is_raised_once_however_long_the_call_runs():
    p = _panel()
    for _ in range(4):
        C.apply_values(p, {"decision_makers": "Tom"}, on_file={"decision_makers": "Haiden"})
    assert len(p.conflicts) == 1


def test_the_ceiling_stops_with_a_sentence_not_a_flag():
    """A panel that silently stops thinking is the worst of both: its open lines read as
    questions still worth asking and its ticks as the whole story."""
    p = _panel(ceiling_usd=0.10)
    C.charge(p, 0.11)
    assert not p.spend.live
    assert "ceiling" in p.spend.stopped.lower()
    assert "still update" in p.spend.stopped


def test_open_canonical_is_what_a_model_call_is_scoped_to():
    p = _panel()
    assert {ln.key for ln in C.open_canonical(p)} <= {ln.key for ln in p.lines}
    assert all(ln.canonical for ln in C.open_canonical(p))
    n = len(C.open_canonical(p))
    C.apply_values(p, {"budget_band": "$60k"})
    assert len(C.open_canonical(p)) == n - 1


# ── the provider seam ───────────────────────────────────────────────────────────────
def _event(words=("Where", "does", "this", "run?"), bot="bot-77", at=41.2,
           name="Jon Shipp", event="transcript.data"):
    return json.dumps({"event": event, "data": {
        "data": {"words": [{"text": w, "start_timestamp": {"relative": at}} for w in words],
                 "participant": {"name": name}},
        "bot": {"id": bot}}}).encode()


def _recall(secret="s3cret"):
    from chordential_oia.meetings.recall import RecallCaptureProvider
    p = RecallCaptureProvider()
    p.webhook_secret = secret
    return p


def test_the_realtime_payload_is_read_where_recall_actually_puts_it():
    """The bot id is at ``data.bot.id`` — two levels deeper than the lifecycle webhook's,
    which is exactly the sort of difference that silently correlates nothing."""
    got = _recall().parse_realtime({}, _event(), token="s3cret")
    assert got == {"bot_id": "bot-77", "speaker": "Jon Shipp",
                   "text": "Where does this run?", "at_s": 41.2}


def test_an_unverified_stream_is_dropped():
    p = _recall()
    assert p.parse_realtime({}, _event(), token="wrong") is None
    assert p.parse_realtime({}, _event(), token="") is None


def test_only_finalized_utterances_are_taken():
    """`transcript.partial_data` sends the same sentence repeatedly as the recogniser
    changes its mind. A tick that appears and then vanishes is worse than one a second
    late."""
    assert _recall().parse_realtime(
        {}, _event(event="transcript.partial_data"), token="s3cret") is None


def test_the_stream_is_only_asked_for_when_it_can_arrive(monkeypatch):
    """Three guards, in one place, because a rule copied into three call sites is a rule
    that will hold in two of them."""
    from chordential_oia import meetings as M
    monkeypatch.setenv("CHORDENTIAL_PUBLIC_DOMAIN", "https://chordential.com")
    monkeypatch.setenv("CHORDENTIAL_RECALL_WEBHOOK_SECRET", "tok")
    monkeypatch.delenv("CHORDENTIAL_CALL_COPILOT", raising=False)
    assert M.realtime_url().startswith("https://chordential.com/webhooks/capture/recall/live/")

    monkeypatch.delenv("CHORDENTIAL_RECALL_WEBHOOK_SECRET")
    assert M.realtime_url() == "", "no token — we would accept anyone's audio"
    monkeypatch.setenv("CHORDENTIAL_RECALL_WEBHOOK_SECRET", "tok")

    monkeypatch.setenv("CHORDENTIAL_PUBLIC_DOMAIN", "http://localhost:8099")
    assert M.realtime_url() == "", "Recall posts from the internet; a laptop cannot receive"
    monkeypatch.setenv("CHORDENTIAL_PUBLIC_DOMAIN", "https://chordential.com")

    monkeypatch.setenv("CHORDENTIAL_CALL_COPILOT", "0")
    assert M.realtime_url() == ""


def test_a_bot_is_only_configured_to_stream_when_asked():
    """A bot pointed at an endpoint that refuses the connection is worse than one that
    never streamed — it retries."""
    p = _recall()
    p.api_key = "k"
    sent = {}
    p._post = lambda path, payload: sent.update(payload) or {"id": "b"}
    p.invite(join_url="https://zoom.us/j/1", meeting_ref="1")
    assert "realtime_endpoints" not in sent["recording_config"]
    sent.clear()
    p.invite(join_url="https://zoom.us/j/1", meeting_ref="1",
             realtime_url="https://x.test/live/?token=t")
    ep = sent["recording_config"]["realtime_endpoints"][0]
    assert ep["events"] == ["transcript.data"], "partials would tick and then untick"
    assert ep["url"] == "https://x.test/live/?token=t"


# ── the wired thing ─────────────────────────────────────────────────────────────────
@pytest.fixture()
def live(tmp_path, monkeypatch):
    for k, v in {"CHORDENTIAL_DB": str(tmp_path / "d.db"),
                 "CHORDENTIAL_UPLOAD_DIR": str(tmp_path / "up"),
                 "CHORDENTIAL_ADMIN_TOKEN": "passphrase",
                 "CHORDENTIAL_SEED_DEMO": "1",
                 "CHORDENTIAL_NOTETAKER_PROVIDER": "recall",
                 "CHORDENTIAL_RECALL_API_KEY": "k",
                 "CHORDENTIAL_RECALL_WEBHOOK_SECRET": "tok",
                 "CHORDENTIAL_PUBLIC_DOMAIN": "https://chordential.com"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CHORDENTIAL_CALL_COPILOT", raising=False)
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
        opp = int(conn.execute(
            "SELECT id FROM opportunities ORDER BY id LIMIT 1").fetchone()["id"])
        mid = db.create_meeting(conn, opp_id=opp, start_at="2026-08-26T15:00:00+00:00",
                                join_url="https://zoom.us/j/1", duration_min=40,
                                provider="zoom", scheduled_by="t", status="bot_invited")
        db.update_meeting(conn, mid, bot_id="bot-77", notetaker_provider="recall")
        conn.commit()
    finally:
        conn.close()
    return c, db, opp, mid


def _stream(c, text, who="Jon", at=10.0, token="tok", bot="bot-77"):
    return c.post(f"/webhooks/capture/recall/live/?token={token}",
                  json=json.loads(_event(tuple(text.split()), bot=bot, at=at,
                                         name=who).decode()))


def _state(c, opp):
    return c.get(f"/opportunity/{opp}/copilot.json").json()


def test_the_panel_moves_as_the_call_runs(live):
    c, _db, opp, _mid = live
    assert _state(c, opp)["covered"] == []
    _stream(c, "What is the approved number for music?", at=120.0)
    _stream(c, "Where does this run, US only or worldwide?", at=300.0)
    d = _state(c, opp)
    assert {l["label"] for l in d["covered"]} == {"Budget", "Territory"}
    assert d["elapsed"] == "05:00"
    assert "Budget" not in {l["label"] for l in d["not_yet"]}


def test_a_covered_line_carries_the_moment_to_jump_back_to(live):
    c, _db, opp, _mid = live
    _stream(c, "What is the approved number for music?", at=125.0)
    covered = _state(c, opp)["covered"][0]
    assert covered["at"] == "02:05"
    assert covered["evidence"] == "What is the approved number for music?"


def test_the_open_list_is_the_question_to_say_not_a_topic_label(live):
    """The plan is explicit: not a topic label — a question, in the operator's voice, ready
    to read aloud. A panel of nouns is a panel you have to translate mid-sentence."""
    c, _db, opp, _mid = live
    ask = {l["label"]: l["ask"] for l in _state(c, opp)["not_yet"]}
    assert ask["Licence term"] == "How long do you need the usage to run?"
    assert all(q.strip().endswith("?") or len(q) > 30 for q in ask.values())


def test_an_unverified_or_unknown_stream_stores_nothing(live):
    c, db, opp, mid = live
    _stream(c, "What is the approved number for music?", token="WRONG")
    _stream(c, "Where does this run, US only or worldwide?", bot="somebody-elses-bot")
    conn = db.connect()
    try:
        assert db.live_line_count(conn, mid) == 0
    finally:
        conn.close()
    assert _state(c, opp)["covered"] == []


def test_the_stream_door_never_asks_to_be_retried(live):
    """A webhook that errors teaches the sender to retry, and a stream we are deliberately
    ignoring must not be re-sent for the length of the call."""
    c, _db, _opp, _mid = live
    assert _stream(c, "hello", token="WRONG").status_code == 200
    assert c.post("/webhooks/capture/recall/live/?token=tok",
                  content=b"not json").status_code == 200


def test_with_no_model_the_panel_still_works_and_says_why(live):
    """The free tier carries the panel. The plan's rule is that it must say plainly when it
    stops rather than going quiet — open lines on a panel that gave up read as questions
    still worth asking."""
    c, _db, opp, _mid = live
    _stream(c, "What is the approved number for music?", at=120.0)
    d = _state(c, opp)
    assert len(d["covered"]) == 1, "the free tier stopped working without a key"
    assert d["spend"]["usd"] == 0.0
    assert "still update" in d["spend"]["stopped"]


def test_resetting_forgets_the_call_for_a_rehearsal(live):
    c, _db, opp, _mid = live
    _stream(c, "What is the approved number for music?", at=120.0)
    assert _state(c, opp)["covered"]
    c.post(f"/opportunity/{opp}/copilot/reset")
    d = _state(c, opp)
    assert d["covered"] == [] and d["heard"] == 0


def test_the_client_can_never_see_the_panel(live):
    """The plan's fourth failure. The client never knows this exists — and its UNRESOLVED
    state in particular must never become another client artifact."""
    from chordential_oia.web import app as app_mod
    c, _db, opp, _mid = live
    for path in (f"/opportunity/{opp}/copilot", f"/opportunity/{opp}/copilot.json"):
        assert not app_mod._is_public_path(path), f"{path} is exempt from the admin gate"
    bare = type(c)(app_mod.app)
    assert bare.get(f"/opportunity/{opp}/copilot.json",
                    follow_redirects=False).status_code in (302, 303, 401, 403)


# ── the paid tier ───────────────────────────────────────────────────────────────────
class _Fake:
    """A model that answers whatever it is told to, and remembers what it was asked."""
    available = True
    name = "fake"
    model = ""

    def __init__(self, payload):
        self.payload = payload
        self.usage = {"in": 900, "out": 60, "calls": 1}
        self.seen = ""

    def complete(self, prompt, max_tokens=400):
        self.seen = prompt
        return self.payload


def _with_key(live, monkeypatch, payload):
    from chordential_oia.web import copilot
    c, db, opp, mid = live
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("CHORDENTIAL_EXTRACTION_ENGINE", "1")
    return c, db, opp, mid, copilot, _Fake(payload)


def test_a_value_makes_a_tick_say_what_was_actually_said(live, monkeypatch):
    c, db, opp, mid, copilot, fake = _with_key(
        live, monkeypatch, '{"budget_band": "$55-65k, hard ceiling"}')
    _stream(c, "What is the approved number for music?", at=120.0)
    conn = db.connect()
    try:
        m = db.get_meeting(conn, mid)
        panel = copilot.panel_for(conn, m, held={})
        out = copilot.value_pass(conn, m, panel, provider=fake, held={})
    finally:
        conn.close()
    assert out.get("found") == {"budget_band": "$55-65k, hard ceiling"}, out
    assert panel.line("budget_band").value == "$55-65k, hard ceiling"
    assert panel.line("budget_band").state == C.ANSWERED


def test_the_operator_sitting_in_the_call_is_the_approval(live, monkeypatch):
    """ADR-0023: a call scheduled by a person and attended by a person is asked-for work.
    `may_spend` reads the approval off a contextvar, so asking it OUTSIDE `approved_by`
    always answers "nobody approved this" — which is what it did first time, and the panel
    duly reported that background work never spends about a call the operator was in."""
    c, db, opp, mid, copilot, fake = _with_key(live, monkeypatch, '{"budget_band": "$60k"}')
    _stream(c, "What is the approved number for music?", at=120.0)
    conn = db.connect()
    try:
        m = db.get_meeting(conn, mid)
        out = copilot.value_pass(conn, m, copilot.panel_for(conn, m, held={}),
                                 provider=fake, held={})
    finally:
        conn.close()
    assert "skipped" not in out, out
    assert "nobody approved" not in json.dumps(out)


def test_a_pass_reads_a_window_and_only_the_slots_still_open(live, monkeypatch):
    c, db, opp, mid, copilot, fake = _with_key(live, monkeypatch, "{}")
    _stream(c, "What is the approved number for music?", at=120.0)
    conn = db.connect()
    try:
        m = db.get_meeting(conn, mid)
        panel = copilot.panel_for(conn, m, held={})
        C.apply_values(panel, {"deadline": "Oct 3"})
        copilot.value_pass(conn, m, panel, provider=fake, held={})
    finally:
        conn.close()
    assert "budget_band" in fake.seen
    assert "deadline" not in fake.seen, "a slot with a value was paid for a second time"
    assert "OMIT" in fake.seen, "the prompt must prefer a gap to a guess"


def test_a_field_nobody_asked_about_is_dropped(live, monkeypatch):
    """The panel's lines are the sheet's. A model inventing a field would put a row on the
    operator's screen that no question corresponds to."""
    c, db, opp, mid, copilot, fake = _with_key(
        live, monkeypatch, '{"budget_band": "$60k", "vibe": "cosy", "ask_territory": "x"}')
    _stream(c, "What is the approved number for music?", at=120.0)
    conn = db.connect()
    try:
        m = db.get_meeting(conn, mid)
        out = copilot.value_pass(conn, m, copilot.panel_for(conn, m, held={}),
                                 provider=fake, held={})
    finally:
        conn.close()
    assert out["found"] == {"budget_band": "$60k"}


def test_unparseable_output_changes_nothing(live, monkeypatch):
    c, db, opp, mid, copilot, fake = _with_key(live, monkeypatch, "I'm sorry, I can't help")
    _stream(c, "What is the approved number for music?", at=120.0)
    conn = db.connect()
    try:
        m = db.get_meeting(conn, mid)
        panel = copilot.panel_for(conn, m, held={})
        copilot.value_pass(conn, m, panel, provider=fake, held={})
    finally:
        conn.close()
    assert panel.line("budget_band").state == C.RAISED, "garbage promoted a line"


def test_a_value_survives_a_refresh_so_it_is_not_bought_twice(live, monkeypatch):
    c, db, opp, mid, copilot, fake = _with_key(
        live, monkeypatch, '{"budget_band": "$55-65k, hard ceiling"}')
    _stream(c, "What is the approved number for music?", at=120.0)
    conn = db.connect()
    try:
        m = db.get_meeting(conn, mid)
        copilot.value_pass(conn, m, copilot.panel_for(conn, m, held={}),
                           provider=fake, held={})
        again = copilot.panel_for(conn, db.get_meeting(conn, mid), held={})
        assert again.line("budget_band").value == "$55-65k, hard ceiling"
        # …and no new speech means no second charge.
        out = copilot.value_pass(conn, db.get_meeting(conn, mid), again,
                                 provider=fake, held={})
    finally:
        conn.close()
    assert out == {"skipped": "no new speech"}


def test_the_ceiling_refuses_before_it_spends(live, monkeypatch):
    """A ceiling that notices afterwards has already spent the money it was there to
    protect."""
    c, db, opp, mid, copilot, fake = _with_key(live, monkeypatch, '{"budget_band": "$60k"}')
    _stream(c, "What is the approved number for music?", at=120.0)
    conn = db.connect()
    try:
        m = db.get_meeting(conn, mid)
        panel = copilot.panel_for(conn, m, held={})
        panel.spend.usd = panel.spend.ceiling_usd      # nothing left
        out = copilot.value_pass(conn, m, panel, provider=fake, held={})
    finally:
        conn.close()
    assert out == {"skipped": "ceiling"}
    assert fake.seen == "", "the model was called after the ceiling was reached"
    assert "ceiling" in panel.spend.stopped.lower()


def test_a_disagreement_with_the_record_becomes_a_question_on_the_panel(live, monkeypatch):
    """End to end, the plan's worked example: two names for the approver, surfaced while
    both people are still on the line."""
    c, db, opp, mid, copilot, fake = _with_key(
        live, monkeypatch, '{"decision_makers": "Tom Vasquez, brand director"}')
    _stream(c, "Who gives final approval on this?", at=200.0)
    held = {"decision_makers": "Haiden Jones"}
    conn = db.connect()
    try:
        m = db.get_meeting(conn, mid)
        panel = copilot.panel_for(conn, m, held=held)
        copilot.value_pass(conn, m, panel, provider=fake, held=held)
    finally:
        conn.close()
    assert [x.question for x in panel.conflicts] == \
        ["Haiden Jones, or Tom Vasquez, brand director?"]


def test_every_slot_answered_is_the_good_ending_not_a_failure(live, monkeypatch):
    c, db, opp, mid, copilot, fake = _with_key(live, monkeypatch, "{}")
    _stream(c, "What is the approved number for music?", at=120.0)
    conn = db.connect()
    try:
        m = db.get_meeting(conn, mid)
        panel = copilot.panel_for(conn, m, held={})
        for ln in C.open_canonical(panel):
            ln.state, ln.value = C.ANSWERED, "x"
        out = copilot.value_pass(conn, m, panel, provider=fake, held={})
    finally:
        conn.close()
    assert out == {"skipped": "every slot answered"}
