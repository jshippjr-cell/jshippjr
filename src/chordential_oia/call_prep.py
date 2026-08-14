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
# Ordered the way a call actually goes: the work, then the sound, then the plan, then
# the people, then the terms. The terms come last because they are the ones that get
# skipped when a call runs long, which is exactly why they need to be visible.
_BANK = [
    ("The work", "What is being made, and what the music has to do in it.", [
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
    ("The sound", "How it should feel, and what it must not be.", [
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
    ("The plan", "When it has to exist, and what it can cost.", [
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
    ("The people", "Who decides, and who you are actually working with.", [
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
    ("The terms", "The ones that get skipped when a call runs long. Ask them anyway.", [
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
]

# The commercial group is the one whose questions have NO canonical slot of their own —
# they are the recurring topics `client_voice._DEFERRABLE_TOPICS` keeps having to defer.
# Flagged so a surface can tell "this fills a labelled field" from "this is a term we
# should have settled", which are different kinds of missing.
_NON_CANONICAL_GROUP = "The terms"


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
    for title, blurb, rows in _BANK:
        group = PrepGroup(title=title, blurb=blurb)
        for key, label, ask, follow_up, why in rows:
            group.lines.append(PrepLine(
                key=key, label=label, ask=ask, follow_up=follow_up, why=why,
                known=fields.get(key, ""),
                canonical=(title != _NON_CANONICAL_GROUP),
            ))
        out.append(group)
    return out


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


__all__ = ["PrepLine", "PrepGroup", "prep_sheet", "coverage"]
