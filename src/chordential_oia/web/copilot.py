"""The Call Copilot's web half — Phase 2 of `docs/discovery-copilot-plan.md`.

Three jobs, and the split between them is the design:

  ``ingest_line``   the door Recall streams into while the call runs. One INSERT.
  ``panel_for``     rebuild the panel: the free tier recomputed from the whole transcript,
                    plus whatever the paid tier already bought.
  ``value_pass``    the paid tier, under every one of the plan's cost rules.

THE PANEL IS THE WORKER, which is why there is no background thread here. Detection runs
on the poll that draws the panel. That falls out of the plan's own cost rule — *"only
windows containing new speech are examined"* — and goes one better: work happens only while
a human is actually looking at the panel. A call the operator walked away from costs
nothing, and there is no worker left running after a bot goes home.

WHY THE FREE TIER IS RECOMPUTED EVERY TIME. It is pure string matching over a few hundred
short rows, so caching it would trade a millisecond for a class of bug this codebase has
paid for repeatedly: two surfaces answering the same question differently. Rebuilt from the
transcript, a refresh, a second window, and a phone all show the same panel because there is
only ever one derivation (ADR-0029 / ADR-0033 / ADR-0057 applied to a live surface).

The PAID tier is the opposite and is stored on the meeting: a value that cost money must
survive a refresh, because recomputing it means paying for it twice.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Dict, List, Optional, Tuple

from .. import call_copilot as C
from ..call_prep import prep_sheet
from . import ai_budget, campaign_intelligence, db

_log = logging.getLogger("chordential.copilot")

# What one call may spend on tier 2 before the panel says it has stopped. Deliberately
# small: this runs per minute of call rather than once, and the plan is explicit that a
# call quietly spending more than the engagement is worth is a failure however well it
# works. Ten cents buys many economy-model passes over a few hundred words.
CEILING_ENV = "CHORDENTIAL_COPILOT_CALL_CAP"
DEFAULT_CEILING_USD = 0.10

# How much transcript one value pass reads. A window, not the call: the plan's "rolling
# window", and the reason the cost of a pass does not grow with the length of the call.
WINDOW_LINES = 40


def call_ceiling_usd() -> float:
    try:
        return max(0.0, float(os.environ.get(CEILING_ENV, "") or DEFAULT_CEILING_USD))
    except ValueError:
        return DEFAULT_CEILING_USD


def enabled() -> bool:
    """The copilot as a whole. Off switches the panel off; the notetaker is untouched and
    still records, still ingests, exactly as before."""
    return (os.environ.get("CHORDENTIAL_CALL_COPILOT", "1") or "1").strip() != "0"


# --------------------------------------------------------------------------- #
# The door Recall streams into
# --------------------------------------------------------------------------- #
def ingest_line(conn, provider_key: str, headers, body: bytes, token: str) -> dict:
    """One streamed utterance → one row. Called several times a minute, for a whole call.

    Kept to a parse, a correlation and an INSERT because everything done here is done again
    in four seconds while somebody is trying to hold a conversation. Detection is NOT done
    here: it belongs to whoever is looking at the panel, and doing it on ingest would run it
    whether or not anybody was.

    A payload we cannot verify or cannot correlate to a meeting we originated is dropped.
    Never guessed at — an unmatched bot id is somebody else's call.
    """
    from .. import meetings as M
    cp = M.get_capture_provider()
    if cp.name != provider_key or not hasattr(cp, "parse_realtime"):
        return {"ok": True, "ignored": "provider-not-active"}
    line = cp.parse_realtime(headers, body, token=token)
    if not line:
        return {"ok": True, "ignored": True}
    meeting = db.meeting_by_external(conn, line.get("bot_id") or "")
    if meeting is None:
        return {"ok": True, "unmatched": True}
    db.add_live_line(conn, bot_id=line.get("bot_id") or "",
                     meeting_id=int(meeting["id"]),
                     opp_id=int(meeting["opp_id"] or 0),
                     at_s=float(line.get("at_s") or 0.0),
                     speaker=line.get("speaker") or "",
                     text=line.get("text") or "")
    return {"ok": True, "stored": True}


# --------------------------------------------------------------------------- #
# The panel
# --------------------------------------------------------------------------- #
def _stored(meeting) -> dict:
    try:
        raw = meeting["copilot_json"] if "copilot_json" in meeting.keys() else ""
    except (TypeError, IndexError):
        raw = ""
    try:
        return json.loads(raw) if raw else {}
    except (ValueError, TypeError):
        return {}


def _save(conn, meeting_id: int, state: dict) -> None:
    db.update_meeting(conn, int(meeting_id), copilot_json=json.dumps(state))


def on_file(conn, opp_id: int) -> Dict[str, str]:
    """What Campaign Intelligence already holds for this opportunity.

    NOT used to pre-tick anything — it is the other half of a ⚠. A slot we hold and a
    different answer on the call is the plan's worked example, and the whole point is that
    it gets asked about while both people are still on the line."""
    row = db.ci_for_opportunity(conn, int(opp_id))
    if row is None:
        return {}
    fields = campaign_intelligence.brief_view(conn, int(row["id"])).get("fields") or {}
    return {k: (v or "").strip() for k, v in dict(fields).items()
            if v and not str(k).startswith("ask_")}


def panel_for(conn, meeting, *, held: Optional[Dict[str, str]] = None) -> C.Panel:
    """The panel as it stands. Free tier recomputed, paid tier read back."""
    state = _stored(meeting)
    panel = C.new_panel(prep_sheet({}), ceiling_usd=call_ceiling_usd())
    panel.spend.usd = float(state.get("usd") or 0.0)
    panel.spend.calls = int(state.get("calls") or 0)
    panel.spend.stopped = str(state.get("stopped") or "")
    rows = db.live_lines(conn, int(meeting["id"]))
    C.observe(panel, [C.Utterance(at_s=float(r["at_s"] or 0.0),
                                  speaker=r["speaker"] or "", text=r["text"] or "")
                      for r in rows])
    panel.seen_id = int(rows[-1]["id"]) if rows else 0
    values = dict(state.get("values") or {})
    if values:
        C.apply_values(panel, values,
                       on_file=held if held is not None else on_file(
                           conn, int(meeting["opp_id"] or 0)))
    return panel


def transcript_text(conn, meeting_id: int, *, last: int = WINDOW_LINES) -> str:
    """The window a value pass reads: the last N utterances, speaker-labelled."""
    rows = db.live_lines(conn, int(meeting_id))
    return "\n".join(f"{(r['speaker'] or 'Speaker')}: {r['text']}" for r in rows[-last:])


# --------------------------------------------------------------------------- #
# Tier 2 — the only thing here that costs money
# --------------------------------------------------------------------------- #
_PROMPT = """You are reading a live excerpt from a music-industry discovery call between a \
studio and a client. Extract ONLY values the client actually stated, for these fields:

{fields}

Rules, in order of importance:
1. If a field was not clearly answered in this excerpt, OMIT it. A missing field costs one \
repeated question; a wrong one walks into a proposal. Omission is always the safe answer.
2. Quote what was said, compactly. "$55-65k, hard ceiling, licence included" — not a \
paraphrase and not a sentence.
3. A question being ASKED is not an answer. Only record what was answered.
4. If a value was stated and then corrected, record the CORRECTION.

Return ONLY a JSON object mapping field key to value, no prose, no code fence. \
Return {{}} if nothing was answered.

EXCERPT:
{window}"""


def value_pass(conn, meeting, panel: C.Panel, *,
               provider=None, held: Optional[Dict[str, str]] = None) -> dict:
    """TIER 2 — read the window for the values behind the slots still open.

    Every one of the plan's cost rules is enforced here, and each is checked BEFORE the
    call rather than after, because a ceiling that notices afterwards has already spent the
    money it was there to protect:

    * **Only when there is new speech.** No new utterance since the last pass → no pass.
    * **Only the slots still open.** A slot with a value is never asked about again, so the
      work shrinks as the call goes on — the opposite of the end-of-call run.
    * **A window, not the call.** Cost per pass stays flat however long the call runs.
    * **The economy model**, chosen by the same `model_for` the extraction engine uses.
    * **A hard per-call ceiling**, and when it bites the panel SAYS so.

    Spend is also charged to the durable monthly ledger, because a ceiling that only the
    caller can see is the exact failure `ai_budget` was written for: five callers spending
    and one of them counting.

    A call the operator is sitting in is asked-for work by definition (ADR-0023), so this
    runs inside `approved_by` rather than falling back to the free path.
    """
    if panel.spend.stopped:
        return {"skipped": "stopped"}
    state = _stored(meeting)
    if panel.seen_id <= int(state.get("seen_id") or 0):
        return {"skipped": "no new speech"}
    slots = C.open_canonical(panel)
    if not slots:
        # Nothing left worth paying to learn. Recorded on the panel rather than left to
        # look like a failure — "every slot is answered" is the good ending.
        state["seen_id"] = panel.seen_id
        _save(conn, int(meeting["id"]), state)
        return {"skipped": "every slot answered"}

    # THE APPROVAL WRAPS THE WHOLE DECISION, not just the call. `may_spend` reads the
    # approval off a contextvar, so asking it outside `approved_by` always answers "nobody
    # approved this" — which is exactly what it did here first time, and the panel duly
    # reported that background work never spends about a call the operator was sitting in.
    # A call scheduled by a person and attended by a person is asked-for work (ADR-0023);
    # the approval is a property of the whole pass, so it opens the whole pass.
    with ai_budget.approved_by("live call"):
        return _value_pass(conn, meeting, panel, provider, held, state, slots)


def _value_pass(conn, meeting, panel, provider, held, state, slots) -> dict:
    """The body of :func:`value_pass`, inside the spend approval. Split out so the approval
    is opened once and cannot be forgotten on one of the early returns below — each of
    which still has to record WHY it stopped."""
    from ..extraction import providers as P
    ok, why = ai_budget.may_spend("call copilot")
    if not ok:
        C.stop(panel, f"Values are off: {why}. Ticks below still update.")
        state["stopped"] = panel.spend.stopped
        _save(conn, int(meeting["id"]), state)
        return {"skipped": why}

    window = transcript_text(conn, int(meeting["id"]))
    if not window.strip():
        return {"skipped": "nothing heard yet"}

    prov = provider if provider is not None else P.get_provider()
    if not getattr(prov, "available", False):
        C.stop(panel, "Values are off: no extraction model is configured. "
                      "Ticks below still update.")
        state["stopped"] = panel.spend.stopped
        _save(conn, int(meeting["id"]), state)
        return {"skipped": "no provider"}

    fields = "\n".join(f"- {ln.key}: {ln.label} — the answer to “{ln.ask}”"
                       for ln in slots)
    prompt = _PROMPT.format(fields=fields, window=window)
    model = P.model_for(len(prompt))
    # PRICE IT FIRST. The output is capped at 400 tokens, so the cost of a pass is known
    # before it is made and the ceiling can refuse it rather than report it.
    likely = P.estimate_cost(model, len(prompt) // 4, 400)
    if panel.spend.would_exceed(likely):
        C.stop(panel, f"Spend ceiling reached (${panel.spend.ceiling_usd:.2f}). "
                      "Ticks below still update; values have stopped.")
        state["stopped"] = panel.spend.stopped
        _save(conn, int(meeting["id"]), state)
        return {"skipped": "ceiling"}

    setattr(prov, "model", model)
    raw = prov.complete(prompt, max_tokens=400)
    usage = getattr(prov, "usage", None) or {}
    spent = P.estimate_cost(model, int(usage.get("in") or 0), int(usage.get("out") or 0)) \
        if usage.get("in") else likely
    ai_budget.record("call copilot", cost=spent, calls=1,
                     in_tokens=int(usage.get("in") or 0),
                     out_tokens=int(usage.get("out") or 0))
    C.charge(panel, spent)

    found = _parse_values(raw, {ln.key for ln in slots})
    if found:
        C.apply_values(panel, found,
                       on_file=held if held is not None else on_file(
                           conn, int(meeting["opp_id"] or 0)))
    values = dict(state.get("values") or {})
    values.update(found)
    state.update({"values": values, "seen_id": panel.seen_id,
                  "usd": panel.spend.usd, "calls": panel.spend.calls,
                  "stopped": panel.spend.stopped})
    _save(conn, int(meeting["id"]), state)
    return {"found": found, "cost": spent, "model": model}


def _parse_values(raw: Optional[str], allowed: set) -> Dict[str, str]:
    """The model's answer, believed only where it is well-formed and in scope.

    A key we did not ask about is DROPPED rather than trusted: the panel's lines are the
    sheet's, and a model inventing a field would put a row on the operator's screen that no
    question corresponds to. Unparseable output yields nothing, which leaves every line
    exactly as the free tier found it — the safe direction.
    """
    text = (raw or "").strip()
    if not text:
        return {}
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text.strip("`")
        text = text[4:] if text.lower().startswith("json") else text
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for key, value in data.items():
        if key in allowed and isinstance(value, str) and value.strip():
            out[str(key)] = value.strip()[:300]
    return out


def reset(conn, meeting_id: int) -> None:
    """Forget a call's panel — the streamed rows and the values bought from them.

    For a rehearsal: running the test script twice against one meeting would otherwise
    score the second run against both. The permanent record is unaffected; the CAPTURE is
    written from the finished transcript (ADR-0014) and nothing here touches it."""
    db.clear_live_lines(conn, int(meeting_id))
    _save(conn, int(meeting_id), {})
