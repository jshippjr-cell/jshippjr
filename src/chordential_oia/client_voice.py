"""How the machine speaks to a CLIENT, as opposed to what it knows.

Campaign Intelligence is a working record: every fact, every gap, every conflict, every
half-caught aside. That is correct, and it is what the operator needs. It is not what a
client should receive, and until this module the client received it anyway — serialized.

Three failures, all from the same missing distinction, all visible on one live brief:

  • **The summary restated the table.** `_understanding_from_ci` walked the canonical
    fields and joined them with full stops, producing "Instrumentation: … Deliverables as
    discussed: … Timeline: … Budget: … Approvals: …" — a data dump wearing sentence
    punctuation, printed directly above the table it had just read. The email carried the
    same paragraph, so the client got it twice on the page and a third time in their inbox.

  • **The heading said it and then the sentence said it again.** "WHAT WE HEARD" followed
    by "Here's what we heard."

  • **Open questions were a gap report.** Every unanswered `open_question` went to the
    client unfiltered: our own conflict records ("The source states conflicting budget band
    values — confirm which is right"), our own data-hygiene problems ("is 'Haiden Jones' the
    same person as 'Tom Vasquez'"), text truncated mid-word, and nine separate "no X was
    mentioned" lines about licence terms. Sending a client fourteen questions after a call
    is not thoroughness. It is the record leaking through the letterbox.

THE RULE HERE: **the workspace is the detailed reporter; the summary is the short one.**
Both read the same intelligence (one derivation, many reporters), and neither invents —
but a reporter that repeats another reporter word for word has not reported anything.

Everything below is deterministic. No model call, no generation; the humanising is in the
SELECTION and the shape, which is where it belongs.
"""
from __future__ import annotations

import re
from typing import Dict, List, Sequence, Tuple

# ── what the short version is allowed to name ────────────────────────────────────
# The summary says a campaign's SHAPE and points at the workspace for its contents. These
# are the areas it may say it has, by name — never their values, which is precisely the
# duplication that made the old paragraph a second copy of the table.
_AREA_PHRASES = [
    ("deliverables", "the deliverables"),
    ("deadline", "the timeline"),
    ("critical_deadline", "the timeline"),
    ("decision_makers", "who signs off"),
    ("budget_band", "the budget"),
    ("reference_playlist", "the references"),
]


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _sentence(value: str) -> str:
    """One clause, ending in exactly one full stop."""
    v = _clean(value).rstrip(" ;,")
    if not v:
        return ""
    return v if v.endswith((".", "!", "?")) else v + "."


def _lower_first(value: str) -> str:
    """Lower an initial capital unless the word is an acronym or a name we can't judge."""
    v = _clean(value)
    if not v or v[:1].islower():
        return v
    head = v.split()[0]
    if head.isupper() or (len(head) > 1 and head[1:].lower() != head[1:]):
        return v                     # NIKE, McCann — leave alone
    return v[:1].lower() + v[1:]


def summary_prose(ci_fields: Dict[str, str], *, met: bool = True,
                  open_question_count: int = 0,
                  lede: bool = True, closing: bool = True) -> str:
    """The short version, for the top of the brief and the body of the email.

    Four sentences at most, and it never prints a field's value beside its label. It states
    what the work IS, how it should feel, names the areas already captured, and hands off to
    the workspace — which is the surface where a wrong value can actually be corrected in
    place, rather than asserted at someone in an email.

    Budget is deliberately NOT restated here. It is the number most worth confirming and the
    most expensive to state wrongly, and it belongs on the page with an edit box next to it,
    not in a paragraph a client has to reply to in prose.

    ``lede`` and ``closing`` come off for the BRIEF, because that page already opens with a
    heading that says "What we heard" and an intro that says "if anything reads wrong, one
    reply fixes it". Printing both again underneath was how one thought came to be stated
    three times before a single fact appeared. The EMAIL keeps them: it is a letter, and a
    letter opens and closes.
    """
    def g(*keys: str) -> str:
        for k in keys:
            v = _clean(ci_fields.get(k) or "")
            if v:
                return v
        return ""

    objective = g("campaign_objective", "business_objective")
    arc = g("emotional_arc", "tone")
    if not (objective or arc):
        return ""

    out: List[str] = []
    if lede:
        out.append("Here's the short version of what we heard."
                   if met else "Here's the short version of where we've got to.")
    if objective:
        out.append(_sentence(objective))
    if arc:
        out.append(_sentence(f"Tonally: {_lower_first(arc)}"))

    have = []
    for key, phrase in _AREA_PHRASES:
        if _clean(ci_fields.get(key) or "") and phrase not in have:
            have.append(phrase)
    if have:
        listed = have[0] if len(have) == 1 else ", ".join(have[:-1]) + " and " + have[-1]
        tail = (", along with a couple of things we'd like to confirm"
                if open_question_count else "")
        out.append(f"We've also written down {listed}, and it's all in your workspace{tail}.")
    elif lede or closing:
        out.append("The full record is in your workspace.")
    if closing:
        out.append("If a line reads wrong, one reply fixes it.")
    return "\n\n".join(out)


# ── which questions a client should actually be asked ────────────────────────────
# An open_question is written for whoever can answer it, and most of them are for US.

# Our own bookkeeping, surfaced by the engine so the operator can reconcile a record.
# Sending it to a client asks them to debug our database.
_INTERNAL_MARKERS = (
    "the source states conflicting",
    "confirm which is right",
    "opportunity intelligence",
    "prior board",
    "record lists",
    "buyer.",
    "crm",
    "discrepancy",
    "possible name confusion",
)

# The commercial and rights points a discovery call routinely does not reach. Individually
# each is a fair question; nine of them in a list is a form, and a client did not agree to
# fill in a form. They are collapsed into one sentence that says what happens next.
_DEFERRABLE_TOPICS = [
    ("licence term", ("license term", "licence term", "term/duration", "usage duration",
                      "how long usage")),
    ("territory", ("territory", "geographic scope")),
    ("publishing and ownership", ("publishing", "ownership terms", "who retains")),
    ("PRO registration", ("pro registration", "performing rights")),
    ("payment terms", ("payment schedule", "payment terms", "invoicing", "deposit")),
    ("exclusivity", ("exclusivity", "exclusive use")),
    ("renewal", ("renewal",)),
    ("musician status", ("union", "non-union")),
]

_MAX_CLIENT_QUESTIONS = 4


def _is_internal(text: str) -> bool:
    t = _clean(text).lower()
    if any(m in t for m in _INTERNAL_MARKERS):
        return True
    # Truncated mid-thought: an odd number of quote marks means a clause was cut, and the
    # live brief shipped several ("…is approximately $9”", "…for which they lack audi").
    for pair in ('"', "“”"):
        if len(pair) == 1:
            if t.count(pair) % 2:
                return True
        elif t.count(pair[0]) != t.count(pair[1]):
            return True
    return False


def _deferrable_topic(text: str) -> str:
    t = _clean(text).lower()
    if not any(p in t for p in ("no ", "not ", "needs clarification", "were mentioned",
                                "was mentioned", "was specified", "was stated")):
        return ""
    for label, needles in _DEFERRABLE_TOPICS:
        if any(n in t for n in needles):
            return label
    return ""


def client_questions(open_questions: Sequence[str], *,
                     limit: int = _MAX_CLIENT_QUESTIONS) -> Tuple[List[str], str]:
    """Split the engine's open questions into ``(ask_now, deferred_note)``.

    ``ask_now``  — the few a client can usefully answer, deduped and capped. Fewer, answered,
                   beats fourteen, ignored.
    ``deferred_note`` — one sentence naming the commercial and rights points that were not
                   covered, and saying we will propose a standard for each rather than
                   interrogating them by email. Empty when there are none.

    Nothing is deleted anywhere: every question stays in Campaign Intelligence, where the
    operator works. This decides only what is put in front of a CLIENT.
    """
    seen, ask, topics = set(), [], []
    for raw in open_questions or []:
        q = _clean(raw)
        if not q:
            continue
        fingerprint = re.sub(r"[^a-z0-9 ]+", "", q.lower())[:120]
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        if _is_internal(q):
            continue
        topic = _deferrable_topic(q)
        if topic:
            if topic not in topics:
                topics.append(topic)
            continue
        ask.append(q)

    note = ""
    if topics:
        listed = (topics[0] if len(topics) == 1
                  else ", ".join(topics[:-1]) + " and " + topics[-1])
        note = (f"A few commercial points didn't come up on the call ({listed}). "
                f"We'll put our standard terms in the proposal so you have something to "
                f"react to rather than a questionnaire to fill in.")
    return ask[:max(0, limit)], note


def internal_questions(open_questions: Sequence[str]) -> List[str]:
    """The complement: everything `client_questions` held back. For the operator's own
    surfaces, so nothing is hidden from the person who can act on it."""
    keep = []
    for raw in open_questions or []:
        q = _clean(raw)
        if q and (_is_internal(q) or _deferrable_topic(q)):
            keep.append(q)
    return keep


__all__ = ["summary_prose", "client_questions", "internal_questions"]
