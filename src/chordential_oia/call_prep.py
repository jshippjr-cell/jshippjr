"""The prep sheet: what to ask on the call, and what we already know.

Phase 0 of the Call Copilot (`docs/discovery-copilot-plan.md`). No live component, no model
call, no spend. A page you read before the call and glance at during it.

WHY IT EXISTS. A live discovery brief closed with fourteen open questions. Every one was a
real gap and every one was findable during the call: nine were licence and rights terms that
take about forty seconds each to ask. The machine only started thinking after everyone had
hung up, so its whole contribution was a list of things it was now too late to ask.

A question asked on the call gets an answer. A question emailed afterwards gets a reply if
you are lucky, a partial reply if you are normal, and silence if the client is busy — and
then it becomes an assumption, which is how a wrong number reaches a proposal.

THE BANK IS THE POINT. The questions below are written, not generated, and they are the
deliverable most worth getting right and the least technical. Each carries:

  • ``ask``       the sentence to say, in the operator's voice. Not a topic label.
  • ``follow_up`` for when the first answer is partial, which is most of the time.
  • ``why``       what it protects downstream, so a rep can judge whether to spend the time.

Later phases change WHEN this is shown (live, during the call) and HOW it is ticked. They do
not change the bank. If the sheet is not useful on paper, no amount of real time makes it
useful, and this is the cheapest possible way to find that out.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .client_voice import _clean


@dataclass
class PrepLine:
    key: str            # canonical slot key, or a topic slug for the terms
    label: str
    ask: str
    follow_up: str
    why: str
    known: str = ""     # what intelligence already holds, verbatim
    canonical: bool = True

    @property
    def state(self) -> str:
        """``have`` when intelligence already holds a value (so the call CONFIRMS it),
        ``ask`` when it does not."""
        return "have" if self.known else "ask"

    @property
    def prompt(self) -> str:
        """The sentence to actually say. A slot we already hold is not asked from scratch —
        reading a known answer back is faster, warmer, and catches the case where what we
        captured is wrong, which is the failure this whole area keeps having."""
        if self.known:
            return f"We have this already. Read it back and check: “{self.known}”"
        return self.ask


@dataclass
class PrepGroup:
    title: str
    blurb: str
    lines: List[PrepLine] = field(default_factory=list)


# ── the bank ─────────────────────────────────────────────────────────────────────
# THE ARC OF A CALL, opening to close. The middle five groups are the brief; the first
# and last are the parts that make the middle work — a call that starts without a frame
# gets guarded answers to commercial questions, and one that ends without a read-back
# ships whatever was misheard.
#
# The terms sit LATE but not last, because they are what gets dropped when a call runs
# long and they need a wrap-up behind them to catch what the drop cost.
#
# `canonical` says whether a group's questions fill Campaign Intelligence slots. The
# opening, the terms and the wrap-up do not: they are conversation, not fields.
_BANK = [
    ("Open the call", "Frame it before you ask anything. Two minutes here buys straight "
     "answers to the awkward questions later.", False, [
        ("attendees", "Who's on the call",
         "Before we start — who's with us, and how does each of you touch this project?",
         "And who isn't here who has an opinion on the music?",
         "The person who is missing is usually the person who sends it back. Naming them "
         "in minute one is cheaper than meeting them in week six."),
        ("recording_consent", "The notetaker",
         "I've got a notetaker running so I'm listening rather than typing. Is that alright "
         "with you?",
         "It only takes the audio; I'll send you the written summary afterwards either way.",
         "Ask it out loud, every time. Some places require both sides to agree, and a "
         "recording nobody consented to is worth less than no recording."),
        ("agenda", "The shape of the call",
         "I'll ask about the work, the sound, the plan and then some boring commercial "
         "questions at the end. You'll have a written summary today. Does that work?",
         "Anything you want to make sure we cover before I start?",
         "Flagging the commercial questions up front is what stops them feeling like an "
         "ambush at minute forty, which is when they normally get skipped."),
    ]),
    ("The work", "What is being made, and what the music has to do in it.", True, [
        ("business_objective", "Business objective",
         "Before the music, what is this campaign trying to do for the business?",
         "And how will you know it worked?",
         "Everything downstream reads this. A piece that serves the wrong goal is on brief "
         "and still wrong."),
        ("campaign_objective", "What the music must do",
         "What is the music's job inside the film specifically?",
         "Is it carrying the whole thing, or supporting a voiceover?",
         "This is the difference between a score and a bed, and it changes the fee."),
        ("deliverables", "Deliverables",
         "Talk me through every version you need. Master, cutdowns, socials, stems.",
         "And do you need stems on all of them, or just the master?",
         "The most common source of scope creep. Every unnamed cutdown is one you will be "
         "asked for free later."),
    ]),
    ("The sound", "How it should feel, and what it must not be.", True, [
        ("emotional_arc", "Emotional arc",
         "Walk me through how it should feel across the piece, start to end.",
         "Is there a turn anywhere, or does it hold one feeling throughout?",
         "A direction is easier to work to than an adjective, and it catches the "
         "'do not let it become triumphant' instructions that only come out when asked."),
        ("reference_playlist", "References",
         "What are you listening to for this? And is there anything you have been sent "
         "that is the wrong direction?",
         "Which part of that reference are you reacting to, the instrumentation or the "
         "feeling?",
         "The second half matters more. A disavowed reference tells you what to avoid, and "
         "clients rarely volunteer it."),
    ]),
    ("The plan", "When it has to exist, and what it can cost.", True, [
        ("deadline", "Timeline",
         "What is the air date, and when do you need final delivery to hit it?",
         "Are those the same date? And is anything upstream of us still moving, like the "
         "edit lock?",
         "Air date and delivery date are different dates. Treating them as one has cost "
         "three weeks of schedule before."),
        ("budget_band", "Budget",
         "What is the approved number for music?",
         "Is that all-in including the licence, and is it a ceiling or a target?",
         "Ask for the MUSIC number by name. A production budget or a media spend quoted "
         "back at you is a number that walks into a proposal."),
    ]),
    ("The people", "Who decides, and who you are actually working with.", True, [
        ("decision_makers", "Who signs off",
         "Who gives final approval on this, and how many times will they see it?",
         "Is anyone else in the room whose opinion changes the outcome?",
         "The person on the call is often not the approver. One review from someone who "
         "has not seen a draft is where projects die."),
        ("brand_notes", "The brand",
         "Tell me how the brand shows up. What is it careful about?",
         "Has music let them down before?",
         "How a brand behaves is a delivery risk as much as a creative one."),
        ("agency_notes", "The agency",
         "How does your side actually work? Who moves paper, and how fast?",
         "Is there anything about your process I should plan around?",
         "Slow legal and slow signatures are schedule facts, and they only surface when "
         "someone asks."),
    ]),
    ("The terms", "The ones that get skipped when a call runs long. Ask them anyway.", False, [
        # MEDIA WAS NEVER ASKED, and it is priced. The sheet asked territory, term and
        # exclusivity and skipped the fourth lever entirely — worth ×0.55 on organic
        # social and ×1.55 on all-media-including-cinema, which on an ordinary job is
        # several thousand dollars nobody was prompted to establish. It was reaching the
        # quote only by accident, read out of whatever the deliverables happened to
        # mention.
        ("media", "Where it runs",
         "Where does the music actually run — broadcast, digital, social, cinema?",
         "Is that the whole plan, or is there a phase two?",
         "The fourth priced lever and the one nobody asks. Organic social and all-media-"
         "including-cinema are nearly three times apart, and a media plan that grows "
         "after the quote is growth we agreed to for free."),
        ("license_term", "Licence term",
         "How long do you need the usage to run?",
         "Is that from delivery or from first air?",
         "Term drives the fee more than almost anything else, and 'perpetual' assumed is a "
         "fee given away."),
        ("renewal", "Renewal",
         "When that term is up, do you expect to renew, or does it lapse?",
         "Would you want the renewal price agreed now or at the time?",
         "Its own question because it has its own answer. Folded into the licence follow-up "
         "it only gets asked when the first answer is partial, which is exactly how it was "
         "skipped and ended up in a client's inbox."),
        ("territory", "Territory",
         "Where does this run? US only, or worldwide?",
         "Any chance it extends later?",
         "Territory is priced. Discovering it after the quote means eating it or "
         "renegotiating."),
        ("exclusivity", "Exclusivity",
         "Do you need any exclusivity, category or otherwise?",
         "For how long?",
         "Exclusivity is a real cost to us and clients often assume it is free."),
        ("publishing", "Publishing and ownership",
         "Is there an expectation about who holds publishing?",
         "Does your legal team have a standard position on that?",
         "Cheaper to raise now than to unpick in a contract with a writer already "
         "attached."),
        ("pro_registration", "PRO registration",
         "Will this need PRO registration, and do you have a cue sheet process?",
         "Who files it on your side?",
         "Free money for the writer if handled, lost forever if nobody asks."),
        ("payment_terms", "Payment terms",
         "What does your payment schedule usually look like?",
         "Is there a deposit, and what triggers the final invoice?",
         "Payment terms decide whether we can pay a creator before we get paid."),
        ("musician_status", "Musicians",
         "Any requirement about union or non-union players?",
         "Does that come from you or from the client?",
         "It changes who we can book and what it costs, and it cannot be fixed after "
         "a session."),
    ]),
    ("Wrap up", "The two minutes that decide whether any of the above survives contact "
     "with the proposal.", False, [
        ("recap", "Read it back",
         "Let me play back what I've got, and stop me where I'm wrong.",
         "Is there anything in that you'd say differently?",
         "The cheapest moment to catch a wrong number is while the person who knows it is "
         "still on the line. Everything downstream is built on this read."),
        ("unasked", "What I didn't ask",
         "What haven't I asked about that I should have?",
         "Is there anything that's gone wrong on a project like this before?",
         "The single most productive question on any discovery call, and the one that "
         "surfaces the constraint nobody thought to mention."),
        ("next_step", "What happens next",
         "You'll get a written summary today. Who else should be on it?",
         "And what's the best way to reach you if something needs a quick answer?",
         "A summary that reaches only the person on the call gets confirmed by only the "
         "person on the call, and the approver sees it for the first time at the end."),
    ]),
]



def prep_sheet(ci_fields: Optional[Dict[str, str]] = None) -> List[PrepGroup]:
    """The sheet for one opportunity: every question, with what we already hold beside it.

    A slot we already hold is NOT dropped. It becomes a read-back — faster to say, warmer to
    hear, and it catches a wrong capture while the person who knows is still on the line.
    Dropping known slots would have hidden exactly the failure this product keeps having:
    a value captured confidently and wrong.
    """
    fields = {k: _clean(v) for k, v in (ci_fields or {}).items()}
    # `critical_deadline` is the same question as `deadline`; either satisfies it.
    if not fields.get("deadline"):
        fields["deadline"] = fields.get("critical_deadline", "")
    out: List[PrepGroup] = []
    for title, blurb, canonical, rows in _BANK:
        group = PrepGroup(title=title, blurb=blurb)
        for key, label, ask, follow_up, why in rows:
            group.lines.append(PrepLine(
                key=key, label=label, ask=ask, follow_up=follow_up, why=why,
                known=fields.get(key, "") if key in _CANON_SLOTS else "",
                canonical=key in _CANON_SLOTS,
            ))
        out.append(group)
    return out


# ── Phase 1 · scoring a call that already happened ───────────────────────────────
# WHY THIS PHASE EXISTS AT ALL. It is the MEASUREMENT step, and its whole job is to make
# Phase 2 judgeable: "does detection actually work" answered against calls that already
# happened, at zero risk and no new spend. Building the live panel first would mean
# discovering the detector is wrong while a client is on the line.
#
# TWO SOURCES OF EVIDENCE, and they answer DIFFERENT questions — conflating them is how a
# tick becomes a lie:
#
#   answered — a Campaign Intelligence field cites this capture for that slot. The
#              extraction already ran; this costs nothing and re-reads its own result.
#              Only canonical slots can reach this state; the terms and the conversation
#              questions have no CI slot to land in.
#   raised   — a written cue matched a line of the transcript. This proves the TOPIC came
#              up. It does not prove an answer was given, and it never claims to.
#   missed   — neither. Not proof it was skipped, but it is the actionable direction, and
#              the plan's own arithmetic applies: a missed tick costs one repeated
#              question, a wrong tick costs a wrong proposal.
#
# The middle state is the interesting one and the reason this is worth building rather
# than counting CI fields: "raised but not answered" means the question WAS asked and the
# answer did not stick, which needs a different fix from "never asked".
#
# The cues are written, like the bank, and matched against the transcript verbatim with
# the matching sentence kept as evidence. A tick you cannot check is the thing this
# repository keeps having to unbuild.
_CUES: Dict[str, tuple] = {
    # Open the call
    "attendees": ("who's with us", "who is with us", "who else is on", "who's on the call",
                  "introduce yourself", "introduce yourselves", "everyone on the call"),
    "recording_consent": ("notetaker", "note taker", "note-taker", "recording this",
                          "record this call", "recording the call", "transcribing this"),
    "agenda": ("shape of the call", "how this will go", "written summary", "before i start",
               "cover today", "run you through", "boring commercial"),
    # The work
    "business_objective": ("for the business", "business objective", "what's the goal",
                           "what is the goal", "trying to achieve", "how will you know it worked",
                           "success looks like"),
    "campaign_objective": ("music's job", "job of the music", "what the music has to do",
                           "what the music needs to do", "carrying the whole", "voiceover",
                           "voice over", "score or a bed", "under the vo"),
    "deliverables": ("cutdown", "cut-down", "cut down", "stems", "deliverable",
                     "versions you need", "versions do you need", "socials",
                     "social cuts", "how many versions"),
    # The sound
    "emotional_arc": ("how it should feel", "how should it feel", "emotional", "the arc",
                      "feel across", "the mood", "builds to", "starts quiet",
                      "how it feels"),
    "reference_playlist": ("reference", "listening to", "playlist", "temp track",
                           "temp music", "sounds like", "wrong direction", "in the vein of"),
    # The plan
    "deadline": ("air date", "airdate", "on air", "deadline", "delivery date",
                 "when do you need", "timeline", "go live", "launch date",
                 "final delivery"),
    "budget_band": ("budget", "approved number", "ballpark", "price range",
                    "what can you spend", "number for music", "allocated for music"),
    # The people
    "decision_makers": ("final approval", "signs off", "sign-off", "sign off on",
                        "approver", "who decides", "decision maker", "who else needs to see"),
    "brand_notes": ("brand guidelines", "brand is careful", "how the brand",
                    "brand shows up", "brand safety", "let them down", "brand police"),
    "agency_notes": ("your side", "your process", "moves paper", "legal team",
                     "how does your", "procurement"),
    # The terms — the ones that keep recurring, which is the whole reason for the plan.
    # MEDIA is deliberately narrow: "broadcast" alone is how a client describes a
    # DELIVERABLE ("a 30-second cut down for broadcast"), so ticking media off that word
    # would mark the fourth priced lever covered on a call where nobody asked about it.
    # These are phrasings that can only be about where the music RUNS.
    "media": ("where does the music actually run", "where will it run", "where does it run",
              "media plan", "broadcast and digital", "digital only", "social only",
              "in cinema", "cinema as well", "run on tv", "paid and organic",
              "phase two"),
    "license_term": ("licence term", "license term", "in perpetuity", "perpetuity",
                     "how long do you need", "usage to run", "term of the licence",
                     "term of the license", "buyout", "buy-out", "usage period",
                     "licence period", "license period", "media term", "how long can we"),
    "renewal": ("renew", "renewal", "lapse", "extend the licence", "extend the license",
                "when the term is up"),
    "territory": ("territory", "territories", "worldwide", "us only", "u.s. only",
                  "domestic", "north america", "where does it run", "where will it run",
                  "global rights"),
    "exclusivity": ("exclusivity", "exclusive use", "exclusive to", "exclusive rights",
                    "category exclusive", "exclusively to you"),
    "publishing": ("publishing", "publisher", "who holds the rights", "own the master",
                   "ownership of the", "copyright"),
    "pro_registration": ("pro registration", "cue sheet", "ascap", "bmi", "prs", "sesac",
                         "performing rights"),
    "payment_terms": ("payment terms", "payment schedule", "net 30", "net 60", "net thirty",
                      "net sixty", "deposit", "invoice", "when do you pay",
                      "purchase order"),
    "musician_status": ("non-union", "nonunion", "union player", "union musician",
                        "musicians union", "union rate", "afm", "session player",
                        "session players", "live players"),
    # Wrap up
    "recap": ("play back what", "read that back", "read it back", "let me recap",
              "recap what", "stop me where", "to summarise", "to summarize"),
    "unasked": ("haven't i asked", "have i not asked", "what haven't i",
                "anything i should have asked", "anything else i should",
                "gone wrong on a project"),
    "next_step": ("what happens next", "next steps", "who else should be on",
                  "best way to reach you", "send you the summary"),
}

_ANSWERED, _RAISED, _MISSED = "answered", "raised", "missed"


@dataclass
class ScoredLine:
    key: str
    label: str
    group: str
    state: str          # answered | raised | missed
    evidence: str       # the extracted value, or the transcript sentence — verbatim
    ask: str            # the question, so a missed line reads as something to do

    @property
    def covered(self) -> bool:
        return self.state != _MISSED


@dataclass
class CallScore:
    lines: List[ScoredLine] = field(default_factory=list)
    total: int = 0
    answered: int = 0
    raised: int = 0
    missed: int = 0
    pct: int = 0
    text: str = ""

    @property
    def missed_lines(self) -> List[ScoredLine]:
        return [ln for ln in self.lines if ln.state == _MISSED]

    @property
    def raised_lines(self) -> List[ScoredLine]:
        """Asked, but nothing landed in a slot. A different failure from never asking, and
        the one worth reading first."""
        return [ln for ln in self.lines if ln.state == _RAISED and ln.key in _CANON_SLOTS]


# WHICH LINES FILL A CAMPAIGN INTELLIGENCE SLOT — declared per KEY, not per group.
#
# It used to be a flag on the group, which was true while the terms were conversation and
# became false the moment four of them (media, territory, licence term, exclusivity) were
# made real slots so a human could correct what the call got wrong. They sit in "The
# terms" beside renewal, publishing, PRO and payment terms, which are still conversation —
# so the group can no longer answer the question and the key has to.
#
# `tests/test_call_prep_sheet.py` pins this against `campaign_intelligence.CANONICAL_FIELDS`
# so the two cannot drift: a slot added there and forgotten here would be a question whose
# answer the sheet never reads back, and a key removed there would be a read-back of a
# field that no longer exists.
_CANON_SLOTS = {
    "business_objective", "campaign_objective", "deliverables",
    "emotional_arc", "reference_playlist",
    "deadline", "budget_band",
    "decision_makers", "brand_notes", "agency_notes",
    # priced, and therefore correctable (pricing.licence_from_ci → build_quote)
    "media", "territory", "license_term", "exclusivity",
}


def _segments(transcript: str) -> List[str]:
    """The transcript as checkable sentences, speaker prefixes and all.

    Kept verbatim — the evidence for a tick is the line that produced it, and a normalised
    or reflowed line is no longer quotable back at the operator."""
    out: List[str] = []
    for raw in (transcript or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        for part in re.split(r"(?<=[.?!])\s+", line):
            part = part.strip()
            if part:
                out.append(part)
    return out


def _raised_in(segments: List[str], cues) -> str:
    for seg in segments:
        low = seg.lower()
        for cue in cues:
            if cue in low:
                return seg
    return ""


def score_call(groups: List[PrepGroup], transcript: str,
               answered: Optional[Dict[str, str]] = None) -> CallScore:
    """Score a FINISHED call against the sheet — Phase 1 of the copilot plan.

    ``answered`` maps a canonical slot key to the value Campaign Intelligence took from
    THIS call's capture. It is read, never recomputed: the extraction already ran, and
    running it again would spend money to learn something already on file.

    No model call, no network, no live component. Deterministic, so the same transcript
    scores the same way twice — which is what makes a coverage number worth watching over
    time rather than a reading of the weather.
    """
    have = {k: _clean(v) for k, v in (answered or {}).items() if _clean(v)}
    segments = _segments(transcript)
    score = CallScore()
    for group in groups:
        for line in group.lines:
            value = have.get(line.key, "") if line.canonical else ""
            if value:
                state, evidence = _ANSWERED, value
            else:
                hit = _raised_in(segments, _CUES.get(line.key, ()))
                state, evidence = (_RAISED, hit) if hit else (_MISSED, "")
            score.lines.append(ScoredLine(
                key=line.key, label=line.label, group=group.title,
                state=state, evidence=evidence, ask=line.ask))
    score.total = len(score.lines)
    score.answered = sum(1 for ln in score.lines if ln.state == _ANSWERED)
    score.raised = sum(1 for ln in score.lines if ln.state == _RAISED)
    score.missed = score.total - score.answered - score.raised
    covered = score.answered + score.raised
    score.pct = int(round(100.0 * covered / score.total)) if score.total else 0
    missed = [ln.label.lower() for ln in score.missed_lines]
    score.text = (f"{covered} of {score.total} covered"
                  + (f"; missed {', '.join(missed)}" if missed else " — everything came up"))
    return score


def coverage(groups: List[PrepGroup]) -> dict:
    """How much of the sheet intelligence already answers. Reported honestly: this counts
    what we HOLD, not what is right — a read-back on the call is what makes it true."""
    lines = [ln for g in groups for ln in g.lines]
    have = [ln for ln in lines if ln.state == "have"]
    return {
        "total": len(lines),
        "have": len(have),
        "ask": len(lines) - len(have),
        "pct": int(round(100.0 * len(have) / len(lines))) if lines else 0,
    }


__all__ = ["PrepLine", "PrepGroup", "ScoredLine", "CallScore",
           "prep_sheet", "coverage", "score_call"]
