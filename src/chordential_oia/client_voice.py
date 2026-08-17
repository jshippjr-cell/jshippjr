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
    # Notes about OUR OWN capture rather than about the engagement. A live brief showed a
    # client "Meeting metadata lists only one speaker ('Jon Shipp') despite a clear
    # two-party dialogue" — a transcription problem on our side, printed as a project risk
    # under their company's name.
    "meeting metadata",
    "captured materials",
    "in the transcript",
    "interviewer",
    "speaker identities",
    "not specified anywhere",
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
    seen, sigs, ask, topics = set(), [], [], []
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
        # Near-duplicates too, not just identical text. A live brief asked the client
        # Marta's own job title twice in a four-item list, in two different wordings.
        sig = _signature(q)
        if not _deferrable_topic(q) and _is_near_duplicate(sig, sigs):
            continue
        sigs.append(sig)
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


_MAX_CLIENT_RISKS = 5

_STOPWORDS = frozenset("""a an the and or but if is are was were be been being to of in on
for with as at by from that this it its their there which who whom what when will would
not no need needs should must may might can could have has had do does did client clients
about into over under than then so such we our us you your they them he she""".split())


def _signature(text: str) -> frozenset:
    """The content words of a line, for judging whether two lines say the same thing."""
    words = re.findall(r"[a-z0-9$]+", _clean(text).lower())
    return frozenset(w for w in words if w not in _STOPWORDS and len(w) > 2)


_CONTAINMENT_MIN_WORDS = 6


def _is_near_duplicate(sig: frozenset, seen: List[frozenset], threshold: float = 0.5,
                       containment: float = 0.5) -> bool:
    """Do two lines say the same thing? Judged two ways, because one is not enough.

    Exact-text dedupe misses all of it: a live brief carried the colour-grade slip FOUR
    times, worded differently each time, and "too polished" three. A reader does not
    experience that as thoroughness.

    **Jaccard** catches two similar-length restatements. It does NOT catch a short line
    swallowed by a longer one — "The colour grade lock has already slipped twice, creating
    schedule risk" against the same fact plus both dates and the reason scored 0.47, under
    any threshold safe enough to use. **Containment** — the shared words as a fraction of
    the SHORTER line — scores that pair 0.75, because the short one genuinely adds nothing.
    A restatement with extra detail is still a restatement."""
    for other in seen:
        union = sig | other
        shared = len(sig & other)
        if union and shared / len(union) >= threshold:
            return True
        # Containment is only meaningful on a line long enough for the ratio to mean
        # something: at six content words a 0.5 score is three shared words, and below
        # that it would merge lines that genuinely differ. Short lines get Jaccard alone.
        smaller = min(len(sig), len(other))
        if smaller >= _CONTAINMENT_MIN_WORDS and shared / smaller >= containment:
            return True
    return False


# A risk is something that could STILL go wrong. Two things that keep arriving in the
# concern bucket are neither.
_RESOLVED = ("was clarified", "later clarified", "was confirmed", "is confirmed",
             "has been confirmed", "originally ambiguous", "this was clarified",
             "client confirmed")
_ASKS = ("what is", "what's", "clarify ", "confirm ", "does client", "will the",
         "worth confirming", "need to confirm", "should be confirmed")

# Words that mean a sentence names a CONSEQUENCE rather than an observation. Used to
# order, not to exclude: a five-item list built from the first five extracted is arbitrary,
# and on the live brief it surfaced two resolved ambiguities and a question while leaving
# out the colour grade that had already slipped twice into a fixed delivery date.
_CONSEQUENCE = ("risk", "slip", "delay", "deadline", "compress", "strain", "miss",
                "fail", "jeopard", "push the", "single point", "not currently reflected",
                "carries additional cost", "elevated", "sensitiv")


def _is_resolved(text: str) -> bool:
    t = _clean(text).lower()
    return any(m in t for m in _RESOLVED)


def _reads_as_a_question(text: str) -> bool:
    t = _clean(text).lower()
    return t.endswith("?") or t.startswith(_ASKS)


def _risk_weight(text: str) -> int:
    t = _clean(text).lower()
    score = sum(1 for w in _CONSEQUENCE if w in t)
    if re.search(r"\b(january|february|march|april|may|june|july|august|september|"
                 r"october|november|december)\b", t) or "$" in t:
        score += 1                       # a risk pinned to a date or a number is concrete
    return score


def client_risks(risks: Sequence[str], *, limit: int = _MAX_CLIENT_RISKS) -> List[str]:
    """The few risks a CLIENT should see, from everything flagged as a concern.

    This function exists because I fixed `open_questions` and left its identical twin.
    Everything filtered out of one list came straight out of the other: a live Campaign
    Brief carried roughly forty "risks", among them six of our own conflict records,
    fragments truncated mid-word, a note about our transcription mislabelling the speakers,
    and the same colour-grade slip restated four times. Under the client's own company name,
    on a page headed "Risks we're tracking".

    A risk list is a warning. Forty of them is not a warning, it is a log — and a log that
    admits our record-keeping problems to the person paying us.

    Held back is not deleted: `internal_risks` returns the complement for the operator, who
    is the only person who can act on a conflict record anyway."""
    kept: List[str] = []
    seen: List[frozenset] = []
    for raw in risks or []:
        r = _clean(raw)
        if not r or _is_internal(r):
            continue
        # A gap in the commercial terms is not a risk, it is a thing to settle — and it is
        # already said once, properly, by `client_questions`'s deferred note.
        if _deferrable_topic(r):
            continue
        # Neither is an ambiguity we already resolved ("$110,000 was ambiguous… it was
        # later clarified") — that is the audit trail, and reading it back as a live
        # concern makes a settled thing sound unsettled.
        if _is_resolved(r):
            continue
        # Nor a question. It belongs in the questions list, where it already is; a live
        # brief printed "What is Marta Vance's exact title" in BOTH.
        if _reads_as_a_question(r):
            continue
        sig = _signature(r)
        if _is_near_duplicate(sig, seen):
            continue
        seen.append(sig)
        kept.append(r)
    # Ordered by whether the sentence names a consequence, so a cap keeps the risks that
    # matter rather than the ones the extractor happened to emit first.
    kept.sort(key=lambda t: -_risk_weight(t))
    return kept[:max(0, limit)]


def internal_risks(risks: Sequence[str]) -> List[str]:
    """Everything `client_risks` held back, for the operator's own surfaces."""
    keep, kept_sigs = [], []
    for raw in risks or []:
        r = _clean(raw)
        if not r:
            continue
        if (_is_internal(r) or _deferrable_topic(r) or _is_resolved(r)
                or _reads_as_a_question(r)):
            keep.append(r)
            continue
        sig = _signature(r)
        if _is_near_duplicate(sig, kept_sigs):
            keep.append(r)
        else:
            kept_sigs.append(sig)
    return keep


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

# ── What an estimate rests on, in the client's hearing ──────────────────────────────
#
# `estimation._assumptions` is written for the operator and says so: it discloses the
# target gross margin, that the priors are uncalibrated, and what the blended rates are
# built from. Every one of those is true and none of them belongs on a document a buyer
# SIGNS — a proposal that states our margin has priced the next negotiation for us.
#
# What the client is owed is the other half of that list: which numbers came out of their
# brief and which we guessed. ADR-0058 is the rule ("scope carries its own evidence") and
# a signable proposal is where breaking it costs the most, because the guess stops being
# a working figure and becomes a term.
_MARGIN_MARKERS = (
    "gross margin", "margin", "expert priors", "not calibrated", "uncalibrated",
    "phase 1", "phase 2", "blended $/hr", "afm", "sag-aftra", "market data",
    "confidence band", "actuals",
)

# The lead-in `estimation` uses for the one line that names what it had to guess. Kept as
# a constant because this is a contract between two modules: if that phrasing changes and
# this misses it, the assumption silently stops reaching the client — which fails quietly,
# in the direction of saying less than we should.
ASSUMED_PREFIX = "assumed, not stated in the brief"


def client_assumptions(assumptions: Sequence[str], *, limit: int = 6) -> List[str]:
    """The assumptions a client should read beneath a number they are asked to accept.

    Keeps what describes THEIR project — scope, duration, recording, what we had to
    guess — and drops what describes our pricing model. The guessed-inputs line is
    promoted to the top wherever it appears: it is the one a reader most needs and the
    one buried deepest.
    """
    kept: List[str] = []
    for raw in assumptions or []:
        a = _clean(raw)
        if not a or a in kept:
            continue
        if any(m in a.lower() for m in _MARGIN_MARKERS):
            continue
        kept.append(a)
    kept.sort(key=lambda a: 0 if a.lower().startswith(ASSUMED_PREFIX) else 1)
    return kept[:limit]


def internal_assumptions(assumptions: Sequence[str]) -> List[str]:
    """The complement — everything `client_assumptions` held back. Nothing is hidden
    from the person who can act on it; it is only kept off the client's copy."""
    return [a for a in (_clean(x) for x in assumptions or [])
            if a and any(m in a.lower() for m in _MARGIN_MARKERS)]

# ── Values that become CONTRACT TERMS ────────────────────────────────────────────────
#
# Campaign Intelligence records what it heard, in its own voice, hedges included. That is
# right for intelligence and wrong for a contract. A live signed proposal carried:
#
#     Scope: Deliverables mentioned: three-minute master film, 30-second social cutdown,
#     stems (for video editor), and a screening/live-event playback version for the
#     February fundraising dinner (needs clarified).
#
# Two separate faults in one line a client put her name to. "Deliverables mentioned:" is
# the extractor narrating itself. "(needs clarified)" is the machine saying it is NOT
# sure — printed as a settled term, in the document where an unconfirmed item is most
# expensive. ADR-0058 says a value carries its own evidence; here the evidence was
# carried INTO the binding text instead of beside it.
_EXTRACTION_PREFIX = re.compile(
    r"^\s*(?:the\s+)?(?:client\s+|buyer\s+|they\s+)?"
    r"(?:deliverables?|scope|timeline|budget|requirements?|assets?)?\s*"
    r"(?:mentioned|stated|said|noted|indicated|discussed|confirmed|requested)\s*:\s*",
    re.I)

# Parentheticals that mean "we are not sure". They must leave the term and reappear as a
# caveat — deleting them outright would turn a guess into a fact, which is worse than the
# clutter it removes.
_UNCERTAIN_PAREN = re.compile(
    r"\s*\((?:needs?\s+(?:to\s+be\s+)?(?:clarified|confirming|confirmation|confirmed)"
    r"|to\s+be\s+confirmed|tbc|tbd|unconfirmed|not\s+confirmed|unclear|assumed"
    r"|if\s+confirmed|pending)\)\s*", re.I)


def contract_phrase(value: str) -> Tuple[str, List[str]]:
    """Clean one Campaign Intelligence value for use as a contract term.

    Returns ``(term, caveats)``. The term is what belongs on the agreement; each caveat is
    a sentence naming something the brief did not settle, for the document's
    "WHAT THIS RESTS ON" section. Nothing is silently dropped: an uncertainty removed from
    the term always comes back as a caveat, because the alternative is a signed document
    presenting a guess as a fact.
    """
    text = _clean(value)
    if not text:
        return "", []
    text = _EXTRACTION_PREFIX.sub("", text, count=1)
    caveats: List[str] = []
    if _UNCERTAIN_PAREN.search(text):
        caveats.append(
            "Part of the scope was described on the call but not finalised; it is "
            "confirmed at spotting before any of it is built.")
        text = _UNCERTAIN_PAREN.sub(" ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    return text.rstrip(" .") + ("." if text.rstrip().endswith(".") else ""), caveats


def joined_sentence(lead: str, tail: str) -> str:
    """Glue a lead-in onto a captured phrase without producing "Working back from Final
    delivery needed two weeks before the launch..".

    The live document did exactly that: a full captured sentence, capital and terminal
    stop intact, concatenated after "Working back from" — leaving a mid-sentence capital
    and a doubled period on a contract line. Lower-cases the join and lets the lead-in own
    the punctuation.
    """
    tail = _clean(tail).rstrip(" .")
    if not tail:
        return ""
    if tail[:1].isupper() and not tail[:4].isupper():
        # Not an acronym or a proper noun run — safe to fold into the sentence.
        tail = tail[0].lower() + tail[1:]
    return f"{lead.rstrip()} {tail}."
