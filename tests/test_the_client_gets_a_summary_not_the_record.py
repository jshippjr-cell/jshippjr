"""What a client receives is a summary. What we hold is a record. They are not the same.

From a live Campaign Brief, 2026-08-14. Under the heading **WHAT WE HEARD**, the page said:

    "Here's what we heard. The music's job is to carry the film … The music carries
     restrained, understated tonality; explicitly not triumphant. Instrumentation: Piece
     should begin near-silent with a single instrument. Deliverables as discussed:
     Six-minute master; two-minute cut; 60-second broadcast cut; 30-second broadcast cut;
     9x16 social version; 1x1 social version; full stems for all versions. Timeline:
     October 3rd is the governing air date … Budget: Total production budget for the
     overall film (not the music) is approximately $900,000. Approvals: …"

directly above a table containing those same values, one per row. The same paragraph was
the body of the email. One reading, printed three times.

Underneath it, **Open questions** carried fourteen entries: six of our own conflict records
("The source states conflicting budget band values — confirm which is right"), one asking
the client to reconcile two names in OUR database, several truncated mid-word, and nine
separate "no X was mentioned" lines about licence terms. And the brief closed by inviting
the client to **request a discovery call** — the call it was summarising.

Nothing here is a reading failure. Every one of those facts was captured correctly. This is
about what gets put in front of a person afterwards.
"""
import pytest

from chordential_oia.client_voice import (client_questions, internal_questions,
                                          summary_prose)

# The live brief's own content, verbatim where it matters.
FIELDS = {
    "campaign_objective": "The music's job is to carry the film and make the anniversary "
                          "feel like one continuous thing rather than a retrospective thing.",
    "business_objective": "Joyful Product launch",
    "emotional_arc": "Restrained, understated tonality; explicitly not triumphant.",
    "deliverables": "Six-minute master; two-minute cut; 60-second broadcast cut; "
                    "30-second broadcast cut; 9x16 social version; 1x1 social version; "
                    "full stems for all versions",
    "deadline": "October 3rd is the governing air date (immovable); broadcast quality "
                "control requires final delivery three weeks ahead of that date.",
    "budget_band": "$55,000-$65,000 USD, hard ceiling, license included",
    "decision_makers": "Final approval / sign-off rests with Halden's brand director, "
                       "Tom Vasquez.",
    "reference_playlist": "John Williams and Thomas Bergersen, quieter work.",
}

QUESTIONS = [
    # ours, not theirs — asks a client to reconcile our own records
    "Clarify whether 'Haiden Jones' (Opportunity Intelligence contact, role unknown) is the "
    "same person as 'Tom Vasquez' (named in this call as Halden's brand director and final "
    "approver), or a different stakeholder — the two names do not match.",
    # a real question a client can answer
    "Confirm whether the $55k-$65k budget must also cover all requested deliverables "
    "(6-min master, 2-min cut, 60s/30s broadcast cuts, 9x16 and 1x1 social cuts, and all "
    "stems) or if these are assumed included",
    # conflict records, several truncated mid-word
    "The source states conflicting budget band values — confirm which is right: "
    "“Approved music budget is $55,000 to $65,000 USD” / “$65,000 is the hard ceiling”",
    "The source states conflicting production budget values — confirm which is right: "
    "“Total production budget for the overall film (not the music) is approximately $9”",
    "The source states conflicting deadline values — confirm which is right: “October 3rd "
    "is the governing air date (immovable); broadcast quality control req”",
    # the rights form
    "No exclusivity terms were mentioned (e.g., category exclusivity) — needs clarification.",
    "No explicit payment schedule, invoicing timing, or deposit/milestone terms were stated",
    "No mention of PRO (Performing Rights Organization) registration — needs clarification.",
    "No publishing split or ownership terms were discussed — needs clarification.",
    "No renewal terms were mentioned for the license — needs clarification.",
    "No license term/duration was specified (e.g., perpetual, X years) — needs clarification.",
    "No territory/geographic scope for usage rights was specified — needs clarification.",
    "No mention of union/non-union musician status — needs clarification.",
]


# ── the summary stops being a second copy of the table ───────────────────────────
def test_the_summary_never_reprints_a_field_value():
    """The whole defect in one assertion. The table is directly beneath it."""
    prose = summary_prose(FIELDS, lede=False, closing=False)
    for value in (FIELDS["deliverables"], FIELDS["deadline"], FIELDS["budget_band"],
                  FIELDS["decision_makers"], FIELDS["reference_playlist"]):
        assert value not in prose, f"the summary restated a table row: {value[:40]}…"


def test_it_names_the_areas_it_has_without_reciting_them():
    prose = summary_prose(FIELDS, lede=False, closing=False)
    for phrase in ("the deliverables", "the timeline", "who signs off", "the budget"):
        assert phrase in prose
    assert "your workspace" in prose, "and it must say where the detail lives"


def test_no_label_colon_value_pairs_survive():
    """"Deliverables as discussed: …", "Timeline: …", "Budget: …", "Approvals: …" — the
    serializer's fingerprint, and what made a paragraph read like a database export."""
    prose = summary_prose(FIELDS)
    for fingerprint in ("Deliverables as discussed:", "Timeline:", "Budget:", "Approvals:",
                        "Instrumentation:", "Distribution:"):
        assert fingerprint not in prose


def test_the_budget_is_not_asserted_at_the_client_in_prose():
    """It is the number most worth confirming and the most expensive to state wrongly. It
    belongs on the page with an edit box beside it, not in a paragraph."""
    assert "$55,000" not in summary_prose(FIELDS)
    assert "$900,000" not in summary_prose(FIELDS)


def test_it_stays_short():
    prose = summary_prose(FIELDS)
    assert len([p for p in prose.split("\n\n") if p.strip()]) <= 6
    assert len(prose) < 700, f"a 'short version' of {len(prose)} characters is not one"


# ── the brief and the email are cut differently ──────────────────────────────────
def test_the_brief_drops_the_lede_and_the_closing_because_the_page_already_says_them():
    """The page has a "What we heard" heading above and an intro ending "one reply fixes
    it" — so printing both again stated one thought three times before a single fact."""
    brief = summary_prose(FIELDS, lede=False, closing=False)
    assert not brief.startswith("Here's the short version")
    assert "one reply fixes it" not in brief


def test_the_email_keeps_them_because_a_letter_opens_and_closes():
    email = summary_prose(FIELDS)
    assert email.startswith("Here's the short version of what we heard.")
    assert email.rstrip().endswith("If a line reads wrong, one reply fixes it.")


def test_nothing_at_all_when_intelligence_is_bare():
    assert summary_prose({}) == ""


# ── the questions a client is actually asked ─────────────────────────────────────
def test_our_own_conflict_records_never_reach_the_client():
    ask, _note = client_questions(QUESTIONS)
    joined = " ".join(ask)
    assert "conflicting" not in joined and "confirm which is right" not in joined


def test_the_client_is_not_asked_to_debug_our_database():
    ask, _note = client_questions(QUESTIONS)
    assert not any("Haiden Jones" in q for q in ask), (
        "reconciling two names in our own record is our job, not theirs")


def test_a_fragment_cut_mid_thought_is_never_sent():
    ask, _note = client_questions(QUESTIONS)
    for q in ask:
        assert q.count("“") == q.count("”")
        assert q.count('"') % 2 == 0


def test_nine_rights_questions_become_one_sentence_about_the_proposal():
    """A client did not agree to fill in a form. Each is a fair question; nine in a list
    is a questionnaire, and it is answered better by a proposal they can react to."""
    ask, note = client_questions(QUESTIONS)
    assert note
    for topic in ("licence term", "territory", "publishing", "payment terms"):
        assert topic in note
    assert "proposal" in note
    assert not any("PRO" in q or "territory" in q.lower() for q in ask)


def test_the_real_question_survives_all_of_it():
    ask, _note = client_questions(QUESTIONS)
    assert len(ask) == 1
    assert "budget must also cover all requested deliverables" in ask[0]


def test_the_client_list_is_capped_even_if_everything_is_legitimate():
    """Genuinely different questions, because near-identical ones are correctly merged by
    the duplicate rule and would test nothing about the cap."""
    many = [
        "Which cut is the hero, the sixty or the thirty?",
        "Does the vocal need to sit under a voiceover in any version?",
        "Is the edit locked, or should we expect picture changes?",
        "Who else at the brand should see the first pass?",
        "Are you supplying the archive stems or should we recreate them?",
        "How many rounds of revision do you expect to need?",
        "Will this play in cinema as well as broadcast?",
    ]
    ask, _note = client_questions(many)
    assert len(ask) == 4


def test_duplicates_are_collapsed():
    ask, _note = client_questions(["Confirm the stem count.", "Confirm the stem count!",
                                   "confirm the stem count"])
    assert len(ask) == 1


def test_nothing_is_destroyed_the_operator_still_sees_all_of_it():
    """Held back from the CLIENT is not deleted. The operator is the person who can act on
    a conflict record, so it must still reach them."""
    ask, _note = client_questions(QUESTIONS)
    held = internal_questions(QUESTIONS)
    assert len(ask) + len(held) == len(QUESTIONS)
    assert any("Haiden Jones" in q for q in held)
    assert any("conflicting" in q for q in held)


@pytest.mark.parametrize("bare", [[], None])
def test_no_questions_means_no_note(bare):
    ask, note = client_questions(bare)
    assert ask == [] and note == ""


# ── the brief stops asking for the meeting it is summarising ─────────────────────
def test_the_discovery_cta_is_gone_once_the_call_has_happened():
    """The live brief ended with "Next step · Request a discovery call · Let's spend 20
    minutes discussing your creative direction, timeline, campaign goals" — sent to someone
    who had just spent that time. It reads as a form letter that did not notice the
    conversation, and it is the one block on the page that contradicts the rest of it."""
    from chordential_oia import capabilities as cap
    from chordential_oia.models import BuyerType, MusicRequirement, Opportunity
    from chordential_oia.qualification import QualificationEngine

    opp = Opportunity(client="Halden", need="40th anniversary brand film, original score",
                      description="Original music for a six-minute documentary short.",
                      buyer_type=BuyerType.AGENCY,
                      music_requirement=MusicRequirement.ORIGINAL)
    qual = QualificationEngine().qualify(opp)
    toggles = cap.default_toggles("New")
    assert toggles["call"] is True, "the toggle itself must still be on; met is the switch"

    after = cap.build_capabilities_doc(opp, qual, None, toggles=toggles,
                                       ci_view={"fields": FIELDS}, met=True)
    assert after.show_call is False, "never invite someone to book the call they just had"

    before = cap.build_capabilities_doc(opp, qual, None, toggles=toggles,
                                        ci_view={"fields": FIELDS}, met=False)
    assert before.show_call is True, "pre-discovery the invitation is the whole point"


# ── the risk list, which is where all of it went instead ─────────────────────────
# Fen & Foundry test call, 2026-08-14. The questions had been filtered; RISKS had not,
# so everything removed from one list came out of the other. The live brief carried ~40
# bullets under "Risks we're tracking", printed under the client's own company name.
LIVE_RISKS = [
    # ours: conflict records
    "The source states conflicting brand notes values — confirm which is right: "
    "“Brand narrative: '11 years of being small is our whole story'” / “Client is wary”",
    "The source states conflicting production budget values — confirm which is right: "
    "“Total campaign/production budget is approximately $110,000” / “The $110,000 figure”",
    # ours: a transcription problem, shown to the client as a project risk
    "Meeting metadata lists only one speaker ('Jon Shipp') despite a clear two-party "
    "dialogue in the transcript — clarify speaker identities/roles for accurate attribution",
    "The role of primary contact Marta Vance at Fen & Foundry is not specified anywhere "
    "in the captured materials.",
    "Interviewer's question mentioned 'master, cut down, social, stems' as example "
    "deliverable types, but client's confirmed list did not include a social cutdown.",
    # resolved: the audit trail, read back as though still live
    "Initial budget figure of $110,000 was ambiguous (stated as budget 'for the "
    "campaign'); it was later clarified that $110,000 covers total production while "
    "$38,000 is specifically allocated for music, inclusive of the license.",
    "Usage term is confirmed to run from first air date rather than delivery date, which "
    "aligns with the March 4 launch date — this was clarified but originally ambiguous.",
    # questions, already in the questions list
    "What is Marta Vance's exact title/role at Fen & Foundry, and does she have sole "
    "sign-off authority, or are there other approvers involved in final decisions?",
    "If the color grade lock (Feb 2) slips again, will the February 18 delivery deadline "
    "still hold, or does it need to move to protect the March 4 launch?",
    # deferred terms, already said once by the note
    "No PRO (performing rights organization) registration or cue sheet handling was discussed",
    "Territory of use was not specified despite brand going national in spring",
    "No mention of union/non-union musician status for the recording",
    # the same fact, four times
    "Final delivery is required February 18 (two weeks before March 4 air date) for "
    "station clearance, but the color grade lock date has already slipped twice and is "
    "now set for February 2, creating schedule risk for on-time delivery.",
    "Color grade lock (an upstream production dependency) has already slipped twice, "
    "indicating a pattern of schedule delay that could push the February 18 music "
    "delivery deadline.",
    "The color grade lock date has already slipped twice, creating schedule risk that "
    "could compress the music delivery timeline.",
    "Delivery is dependent on color grade being locked, which has slipped twice already.",
    # genuine, and the ones a client should actually see
    "Client has had two prior negative experiences with music for this brand: one "
    "described as 'too polished' and another as sounding 'a little like an insurance "
    "advertisement,' indicating high sensitivity to tone and elevated approval risk.",
    "The $38,000 music budget must cover both composition/production and the license, "
    "which combined with potential exclusivity costs could strain the budget.",
    "Client indicated that approvals and paperwork move through them personally, "
    "suggesting a single point of approval and a single point of failure if unavailable.",
    # a plain fact, not a risk at all
    "Warm, handmade feel throughout.",
]


def test_the_risk_list_is_a_warning_not_a_log():
    from chordential_oia.client_voice import client_risks
    kept = client_risks(LIVE_RISKS)
    assert len(kept) <= 5, f"{len(kept)} risks is a log, not a warning"
    assert kept, "and the genuine ones must survive"


def test_our_own_conflict_records_and_transcription_problems_stay_ours():
    from chordential_oia.client_voice import client_risks
    joined = " ".join(client_risks(LIVE_RISKS)).lower()
    assert "conflicting" not in joined
    assert "meeting metadata" not in joined, (
        "our transcription mislabelled the speakers; that is not the client's risk")
    assert "captured materials" not in joined
    assert "interviewer" not in joined


def test_an_ambiguity_we_already_resolved_is_not_a_live_concern():
    """"$110,000 was ambiguous… it was later clarified" is the audit trail. Reading it
    back under "Risks we're tracking" makes a settled thing sound unsettled."""
    from chordential_oia.client_voice import client_risks
    joined = " ".join(client_risks(LIVE_RISKS)).lower()
    assert "later clarified" not in joined
    assert "originally ambiguous" not in joined


def test_a_question_is_not_a_risk_it_is_already_in_the_questions_list():
    from chordential_oia.client_voice import client_risks
    for r in client_risks(LIVE_RISKS):
        assert not r.rstrip().endswith("?"), f"a question printed as a risk: {r[:60]}"
    assert not any("What is Marta" in r for r in client_risks(LIVE_RISKS))


def test_the_same_fact_four_times_is_reported_once():
    """The colour grade slip appeared four times in one list, worded differently each
    time. A reader does not experience that as thoroughness."""
    from chordential_oia.client_voice import client_risks
    grade = [r for r in client_risks(LIVE_RISKS) if "color grade" in r.lower()]
    assert len(grade) == 1, f"the colour grade slip was reported {len(grade)} times"


def test_the_risks_that_survive_are_the_ones_that_name_a_consequence():
    """Ordered, not truncated at whatever the extractor emitted first. On the live brief
    the first five included two resolved ambiguities and a question, while the colour
    grade slipping twice into a fixed delivery date did not make the list at all."""
    from chordential_oia.client_voice import client_risks
    kept = " ".join(client_risks(LIVE_RISKS)).lower()
    assert "color grade" in kept, "the schedule risk with a date on it must survive"
    assert "too polished" in kept or "insurance advertisement" in kept


def test_nothing_is_destroyed_the_operator_still_sees_every_risk():
    from chordential_oia.client_voice import client_risks, internal_risks
    kept, held = client_risks(LIVE_RISKS), internal_risks(LIVE_RISKS)
    assert len(kept) + len(held) == len(LIVE_RISKS)
    assert any("Meeting metadata" in r for r in held)
    assert any("conflicting" in r for r in held)


def test_a_short_risk_is_never_merged_into_an_unrelated_one():
    """Containment on a five-word line is two shared words. The length guard is what
    stops "Stems on all versions" and "Stems are not included" collapsing into one."""
    from chordential_oia.client_voice import client_risks
    out = client_risks(["Budget is tight for stems.", "Timeline is tight for mixing."])
    assert len(out) == 2


def test_the_brief_puts_the_filtered_risks_on_the_page(tmp_path):
    from chordential_oia import capabilities as cap
    from chordential_oia.models import BuyerType, MusicRequirement, Opportunity
    from chordential_oia.qualification import QualificationEngine
    opp = Opportunity(client="Fen & Foundry", need="Brand launch film, original score",
                      description="Original music for a two-minute roastery film.",
                      buyer_type=BuyerType.BRAND,
                      music_requirement=MusicRequirement.ORIGINAL)
    doc = cap.build_capabilities_doc(
        opp, QualificationEngine().qualify(opp), None, toggles=cap.default_toggles("New"),
        ci_view={"fields": FIELDS, "risks": LIVE_RISKS}, met=True)
    assert len(doc.risks) <= 5
    assert not any("conflicting" in r for r in doc.risks)
