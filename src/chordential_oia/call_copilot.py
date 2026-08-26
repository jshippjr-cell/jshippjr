"""The Call Copilot's live panel — Phase 2 of `docs/discovery-copilot-plan.md`.

Phase 0 put the questions in front of the operator BEFORE the call. Phase 1 scored the
call AFTER it. This is the middle, and it is the one the plan was written for: the machine
reasons *while* it transcribes, and gives that reasoning one output — a short list of what
has not been covered yet, in front of the person who can still ask.

WHAT THIS MODULE IS. The state of that panel, and the rules for moving it. Pure: no
database, no network, no clock of its own. The web layer feeds it utterances and asks what
to draw; the model tier (also injected) is optional and the panel is useful without it.

TWO TIERS, AND THE FREE ONE CARRIES THE PANEL.

The plan budgeted for a model call per window, because when it was written there was no
detector. Phase 1 then built one — written cues, adversarially tested against a bait
transcript of ordinary sentences — and it costs nothing to run. So:

  tier 1  ``observe()``      free, instant, every window. Moves a line to `raised` and
                             keeps the sentence that did it. No key, no spend, no network.
  tier 2  ``apply_values()`` a model reading the window for the VALUE behind an open slot,
                             turning `raised` into `answered` with a figure on the panel,
                             and surfacing a value that disagrees with one already on file.

Tier 1 alone is most of the plan's picture: ✓/○ against every line with the question to
ask, updating live. Tier 2 is what makes a ✓ say *"$55–65k, hard ceiling"* rather than
*"budget came up"*. **When tier 2 is capped, unavailable, or switched off, the panel says
so and keeps working** — the plan's rule that it must never go quiet.

WHAT THE PANEL MAY NEVER DO. From the plan's own list of ways this fails:

  • **It must not become a script.** Nothing here blocks, nags, or beeps. The panel is
    read at a glance and ignored at will; that is a UI property, but it starts here — this
    module has no notion of an alert, only of state.
  • **It must not fire wrong.** A wrong tick manufactures false confidence, which is worse
    than no panel. Ambiguity leaves a line OPEN. `observe` inherits Phase 1's conservative
    cues wholesale rather than loosening them for a live setting.
  • **It must not cost per minute without a ceiling.** `Spend` is carried on the panel and
    the ceiling is checked before every model call, not after.
  • **It must not leak.** Nothing in here is client-facing. The panel's *unresolved* state
    in particular never reaches a client artifact.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from .call_prep import _CANON_SLOTS, _CUES, PrepGroup, _raised_in, _segments

OPEN, RAISED, ANSWERED = "open", "raised", "answered"


@dataclass
class Utterance:
    """One thing somebody said. ``at_s`` is seconds from the start of the recording, which
    is what makes a covered line clickable back to the moment later."""
    at_s: float
    speaker: str
    text: str


@dataclass
class Line:
    """One question on the sheet, as the panel currently understands it."""
    key: str
    label: str
    group: str
    ask: str
    canonical: bool
    state: str = OPEN
    evidence: str = ""      # the sentence that covered it — verbatim, always checkable
    value: str = ""         # what was actually said, once the model has read it
    at_s: float = 0.0       # when, in the call

    @property
    def covered(self) -> bool:
        return self.state != OPEN


@dataclass
class Conflict:
    """Two answers to one question — the ⚠ row, and the reason the panel is worth looking
    at rather than just recording. These cost the most later and take ten seconds to settle
    while everyone is still on the call."""
    key: str
    label: str
    on_file: str
    heard: str

    @property
    def question(self) -> str:
        return f"{self.on_file}, or {self.heard}?"


@dataclass
class Spend:
    """What tier 2 has cost this call, and whether it is still running.

    ``stopped`` is a SENTENCE, not a flag: the plan requires the panel to say plainly when
    it stops rather than going quiet, and a panel that silently stops thinking is the worst
    of both — it looks like everything is covered."""
    usd: float = 0.0
    calls: int = 0
    ceiling_usd: float = 0.0
    stopped: str = ""

    @property
    def live(self) -> bool:
        return not self.stopped

    def would_exceed(self, next_call_usd: float) -> bool:
        return bool(self.ceiling_usd) and (self.usd + next_call_usd) > self.ceiling_usd


@dataclass
class Panel:
    lines: List[Line] = field(default_factory=list)
    conflicts: List[Conflict] = field(default_factory=list)
    spend: Spend = field(default_factory=Spend)
    seen_id: int = 0          # the last transcript row folded in — the resume point
    elapsed_s: float = 0.0
    heard_lines: int = 0

    # ── what the panel is for: what has NOT been covered, in front of someone who can
    #    still ask. Everything else on the panel is context for this list.
    @property
    def not_yet(self) -> List[Line]:
        return [ln for ln in self.lines if ln.state == OPEN]

    @property
    def covered(self) -> List[Line]:
        return [ln for ln in self.lines if ln.covered]

    @property
    def answered(self) -> List[Line]:
        return [ln for ln in self.lines if ln.state == ANSWERED]

    def line(self, key: str) -> Optional[Line]:
        return next((ln for ln in self.lines if ln.key == key), None)

    @property
    def headline(self) -> str:
        n, total = len(self.covered), len(self.lines)
        if n == total:
            return "Everything covered."
        return f"{n} of {total} covered · {total - n} still to ask"


def new_panel(groups: Sequence[PrepGroup], *, ceiling_usd: float = 0.0) -> Panel:
    """A panel for one call, built from the SAME sheet Phases 0 and 1 use.

    A slot Campaign Intelligence already holds is NOT pre-ticked. It stays open, because
    the call is where a value gets confirmed and the whole reason the prep sheet turns a
    known slot into a read-back is that a value captured confidently and wrongly is the
    failure this product keeps having. What we hold is the material for a ⚠, not a ✓.
    """
    panel = Panel(spend=Spend(ceiling_usd=ceiling_usd))
    for group in groups:
        for src in group.lines:
            panel.lines.append(Line(key=src.key, label=src.label, group=group.title,
                                    ask=src.ask, canonical=src.canonical))
    return panel


def observe(panel: Panel, utterances: Sequence[Utterance]) -> List[Line]:
    """TIER 1 — free. Fold new speech into the panel; return the lines it just covered.

    Runs Phase 1's written cues against each new utterance. Deliberately unchanged from the
    post-call detector: the live setting is exactly where a loosened cue would do its damage
    (a line ticked mid-call is a question the operator then does not ask), so it inherits
    the conservative version and its bait-transcript test wholesale.

    THE WORK SHRINKS AS THE CALL RUNS, which is the plan's own cost rule and applies to the
    free tier too: a covered line is no longer looked for, so a long call does less work per
    minute, not more.
    """
    newly: List[Line] = []
    for u in utterances:
        panel.heard_lines += 1
        panel.elapsed_s = max(panel.elapsed_s, float(u.at_s or 0.0))
        segments = _segments(u.text)
        if not segments:
            continue
        for ln in panel.lines:
            if ln.covered:
                continue                      # never looked for again
            hit = _raised_in(segments, _CUES.get(ln.key, ()))
            if hit:
                ln.state = RAISED
                ln.evidence = hit
                ln.at_s = float(u.at_s or 0.0)
                newly.append(ln)
    return newly


def open_canonical(panel: Panel) -> List[Line]:
    """The slots tier 2 still has anything to learn about — Campaign Intelligence slots
    with no value yet. This list is what a model call is scoped to, and it is why the cost
    of the panel falls over the course of a call instead of rising."""
    return [ln for ln in panel.lines
            if ln.canonical and ln.key in _CANON_SLOTS and ln.state != ANSWERED]


def apply_values(panel: Panel, values: Dict[str, str], *,
                 on_file: Optional[Dict[str, str]] = None) -> List[Conflict]:
    """TIER 2's result — a value per slot, from the model that read the window.

    A value promotes its line to ``answered`` and puts the figure on the panel, which is
    the difference between "budget came up" and "$55–65k, hard ceiling". It also promotes a
    line the free tier never saw: a client can answer a question that was asked in words no
    cue matches.

    Where the value DISAGREES with what we already hold, a ⚠ is raised rather than the
    record being quietly overwritten. That is the plan's own worked example — two names for
    the approver — and overwriting is precisely the failure it describes, because the
    machine keeps whichever it heard last and nobody is ever asked which is right.
    """
    held = {k: (v or "").strip() for k, v in (on_file or {}).items()}
    found: List[Conflict] = []
    for key, raw in (values or {}).items():
        value = (raw or "").strip()
        ln = panel.line(key)
        if ln is None or not value:
            continue
        ln.state = ANSWERED
        ln.value = value
        if not ln.evidence:
            ln.evidence = value
        if not ln.at_s:
            ln.at_s = panel.elapsed_s
        prior = held.get(key, "")
        if prior and not _same(prior, value) and not any(
                c.key == key for c in panel.conflicts):
            conflict = Conflict(key=key, label=ln.label, on_file=prior, heard=value)
            panel.conflicts.append(conflict)
            found.append(conflict)
    return found


def _same(a: str, b: str) -> bool:
    """Two renderings of one answer. Deliberately generous — a ⚠ the operator has to
    dismiss because "Oct 3" and "October 3rd" look different is a panel that nags, and a
    panel that nags gets ignored, which costs more than the ⚠ was worth."""
    def norm(t):
        return "".join(ch for ch in t.lower() if ch.isalnum())
    x, y = norm(a), norm(b)
    return bool(x) and bool(y) and (x == y or x in y or y in x)


def stop(panel: Panel, why: str) -> None:
    """Tier 2 stops, and the panel SAYS SO. Never a silent halt: an operator reading a
    panel that quietly gave up would read its open lines as questions still worth asking
    and its ticks as the whole story, and both would be wrong."""
    panel.spend.stopped = why


def charge(panel: Panel, usd: float) -> None:
    panel.spend.usd += max(0.0, float(usd or 0.0))
    panel.spend.calls += 1
    if panel.spend.ceiling_usd and panel.spend.usd >= panel.spend.ceiling_usd:
        stop(panel, f"Spend ceiling reached (${panel.spend.ceiling_usd:.2f}). "
                    "Ticks below still update; values have stopped.")


__all__ = ["OPEN", "RAISED", "ANSWERED", "Utterance", "Line", "Conflict", "Spend",
           "Panel", "new_panel", "observe", "open_canonical", "apply_values",
           "stop", "charge"]
