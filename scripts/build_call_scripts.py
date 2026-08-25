# -*- coding: utf-8 -*-
"""Build the paired discovery-call test scripts from ONE source.

    python3 scripts/build_call_scripts.py

Two readers work off two files, and a line that drifts between them is the whole way a
paired read falls apart — so the turns are written once here and both scripts are printed
from them, the way `build_score_scene.py` prints one model to several recorders.

`docs/call-scripts/*.md` are BUILD ARTIFACTS. Edit the turns below, re-run this, and
commit the regenerated pair. It also scores the finished transcript through
`call_prep.score_call` and stamps the expected result into the studio script, so the
exercise has a known answer to check the real call against."""
import os, textwrap

JON, MAR = "JON", "MARISA"

# (speaker, line, note-for-the-operator-only)
TURNS = [
(JON,"Marisa, thanks for making time. Before we start — who's with us today, and how does each of you touch this project?",""),
(MAR,"Just me today. I'm Marisa Del Rio, senior producer at Pike & Rowan. I'm running production on this one end to end.",""),
(JON,"And who isn't here who has an opinion on the music?",""),
(MAR,"Our creative director, Aziz Barr. And someone on the HALVARD side will have to bless it, but that's later.",""),
(JON,"I've got a notetaker running so I'm listening rather than typing. Is that alright with you?","Say this OUT LOUD every time. It is the consent line, and a recording nobody agreed to is worth less than no recording."),
(MAR,"That's fine.",""),
(JON,"I'll ask about the work, the sound, the plan, and then some boring commercial questions at the end. You'll have a written summary today. Does that work?",""),
(MAR,"Works. I've got about forty minutes.",""),
(JON,"Before the music — what is this campaign trying to do for the business?",""),
(MAR,"HALVARD has been a technical outdoor brand for twenty years and it reads as cold. This is the autumn brand film, and the job is to make people feel something about the brand rather than about the jacket. If we get it right, it shifts how people talk about them.",""),
(JON,"And how will you know it worked?",""),
(MAR,"Honestly? If the comments are about the film and not about the price.",""),
(JON,"What is the music's job inside the film specifically?",""),
(MAR,"It carries the whole thing. There's no voiceover and barely any dialogue — a woman walking home over about two minutes, the seasons changing around her. The music is the narration.",""),
(JON,"Talk me through every version you need. Master, cutdowns, socials, stems.",""),
(MAR,"A two-minute master for the film. Then thirty and fifteen second cutdowns for broadcast, and vertical versions for social.",""),
(JON,"How many verticals, and do you need stems on all of them or just the master?",""),
(MAR,"Three verticals. Stems just on the master — our editor likes to duck things himself.","TRAP 1 of 5 — she changes this to four verticals at turn 68. The summary must carry FOUR."),
(JON,"Walk me through how it should feel across the piece, start to end.",""),
(MAR,"It starts as almost nothing — one instrument, quite bare. It should feel like the cold. Then it warms, and by the last thirty seconds it's full and it lands somewhere hopeful. But not triumphant. Please, not triumphant.",""),
(JON,"Is there a turn anywhere, or does it hold one feeling throughout?",""),
(MAR,"There's a turn about eighty seconds in, when she reaches the ridge.",""),
(JON,"What are you listening to for this? And is there anything you've been sent that's the wrong direction?",""),
(MAR,"We've been living in Johannsson and Hildur Gudnadottir. Everyone keeps sending us Sigur Ros and it is the wrong direction — too weightless. And the temp track on the cut right now is a licensed indie thing that we all hate.","The DISAVOWED reference is the valuable half. Check the summary records what to avoid, not just what to chase."),
(JON,"Which part of the Johannsson are you reacting to — the instrumentation, or the feeling?",""),
(MAR,"The restraint. He leaves space.",""),
(JON,"What is the air date, and when do you need final delivery to hit it?",""),
(MAR,"It goes live October the third. We'd want final delivery three weeks before that, so around the twelfth of September.","Two DIFFERENT dates. If the summary collapses them into one, that is the schedule bug this question exists to catch."),
(JON,"Are those the same date for everything, or do socials come later?",""),
(MAR,"Socials can come a week after the master.",""),
(JON,"And is anything upstream of us still moving, like the edit lock?",""),
(MAR,"We lock picture on the twenty-second of August. That should hold.",""),
(JON,"What is the approved number for music?",""),
(MAR,"We're around sixty.","TRAP 2 — a soft number. Do NOT accept it; the follow-up is the next line and it is what pins the real one."),
(JON,"Is that all-in including the licence, and is it a ceiling or a target?",""),
(MAR,"The approved music number is fifty-five to sixty-five thousand, and it is a hard ceiling. That's inclusive of the licence.",""),
(JON,"Who gives final approval on this, and how many times will they see it?",""),
(MAR,"Aziz signs off creatively. He'll see it twice — a first pass and a final.",""),
(JON,"Is anyone else in the room whose opinion changes the outcome?",""),
(MAR,"Sorry — I should correct myself. Aziz signs off on our side, but final approval is Tom Vasquez, HALVARD's brand director. He sees it once, at the end.","TRAP 3, and the important one. TWO answers to 'who signs off'. Campaign Intelligence should surface the conflict rather than silently keeping whichever it heard last."),
(JON,"That's worth having straight. So Aziz is our day-to-day, and Tom is the one who can send it back?",""),
(MAR,"Yes. And Tom is not a music person, so make it obvious.",""),
(JON,"Tell me how the brand shows up. What is it careful about?",""),
(MAR,"They're careful about anything that reads as luxury — they're a working brand. And music has let them down before. They licensed something two years ago that turned up in a car ad three months later, and it was embarrassing.",""),
(JON,"How does your side actually work — who moves paper, and how fast?",""),
(MAR,"Our legal is slow. Assume three weeks for any contract. And procurement will want a purchase order before anything starts.",""),
(JON,"Right — the boring bit. How long do you need the usage to run?",""),
(MAR,"Twelve months from first air, I think.",""),
(JON,"Is that from delivery, or from first air?",""),
(MAR,"From first air.",""),
(JON,"When that term is up, do you expect to renew, or does it lapse?",""),
(MAR,"I'd expect we renew if it performs. Can we agree the renewal price now?",""),
(JON,"We can, and it is cheaper to. Where does this run — US only, or worldwide?",""),
(MAR,"North America to start. There's a chance it extends to the UK in the spring, but that is not committed.","An UNCOMMITTED extension is not a territory. It should read as a possibility, never priced as if agreed."),
(JON,"Do you need any exclusivity, category or otherwise?",""),
(MAR,"Category exclusive for outdoor apparel, for the term. That one is non-negotiable after what happened.",""),
(JON,"Is there an expectation about who holds publishing?",""),
(MAR,"I genuinely don't know. I'd have to ask legal.","TRAP 4 — a question ASKED but not answered. It must land as an open question, never as a captured fact. This is the state Phase 1 calls 'raised'."),
(JON,"That's fine — I'll put a standard position in the summary and your legal can push back. Will this need PRO registration, and do you have a cue sheet process?",""),
(MAR,"Yes, we file cue sheets. Our post house handles it.",""),
(JON,"What does your payment schedule usually look like?",""),
(MAR,"Net sixty from invoice.",""),
(JON,"Is there a deposit, and what triggers the final invoice?",""),
(MAR,"We can do a deposit on signature. Final on delivery and acceptance.",""),
(JON,"Any requirement about union or non-union players?",""),
(MAR,"No requirement. We've used live players before and liked it.",""),
(JON,"One more thing — you said three verticals earlier. Is that still right?",""),
(MAR,"Actually, make it four. There's a fourth placement we just picked up.","TRAP 1 lands here. Scope moved mid-call. If the summary still says three, the deal is under-scoped before it starts."),
(JON,"Noted — four verticals. Let me play back what I've got, and stop me where I'm wrong. Two-minute master; thirty and fifteen second cutdowns; four verticals; stems on the master only. Live October third, final delivery September twelfth, picture lock August twenty-second. Fifty-five to sixty-five all-in, hard ceiling. Twelve months from first air, North America, category exclusive in outdoor apparel. Net sixty with a deposit on signature. Tom Vasquez approves, Aziz day to day. Publishing still open.","The read-back is the cheapest moment to catch a wrong number, and it is the line most often skipped when a call runs long."),
(MAR,"That's all right. One correction — the fifteen second cutdown might become a six. I'll confirm.","TRAP 5 — a correction arriving DURING the read-back, which is exactly what the read-back is for."),
(JON,"I'll scope both and we'll drop one. What haven't I asked about that I should have?",""),
(MAR,"Whether you need the stems by instrument or by group. Group is fine.",""),
(JON,"Good catch — that's a real difference. Has anything gone wrong on a project like this before?",""),
(MAR,"The car ad thing. And once we got a track that was beautiful and forty seconds too short to cut down.",""),
(JON,"You'll get a written summary today. Who else should be on it?",""),
(MAR,"Copy Aziz. Not Tom yet.",""),
(JON,"And what's the best way to reach you if something needs a quick answer?",""),
(MAR,"Email, or my mobile — it's in my signature.",""),
(JON,"Thanks Marisa. This was a good one.",""),
(MAR,"Thanks Jon.",""),
]

HEAD = """# Discovery call · test script — {who}

> {role}
>
> A Chordential discovery call · HALVARD, *"Long Way Home"* · agency: Pike & Rowan
>
> A rehearsal script for testing the notetaker → Campaign Intake → Campaign
> Intelligence path on a real Zoom call. Two readers, one script each.
> **Every name and brand here is invented.** HALVARD and Pike & Rowan are not real
> companies; nothing in this call describes real client work.

## How to run it

1. Open the two scripts on two machines — **{who}** reads this one, the other person
   reads the other. Both are numbered identically; the other party's lines are printed
   in full so you never lose your place.
2. Schedule the call in Chordential so the notetaker joins, and start the Zoom.
3. **Read at conversational pace, not reading pace.** Pause, overlap a little, say "um".
   The extraction is being tested against speech, and a flat recitation tests nothing
   that matters.
4. Roughly **10–12 minutes**. Don't rush the read-back near the end — it is doing real work.
5. Afterwards, open `/opportunity/<id>/prep` and compare the score against the expected
   result at the foot of the studio script.

---

"""

FOOT_JON = """
---

## What this call is engineered to break

Five deliberate traps, in the order they arrive. Each is a real failure this system has
had or could have, and the point of the exercise is to check the summary catches them —
not to check the transcript is pretty.

| # | Turn | The trap | What a correct summary does |
|---|---|---|---|
| 1 | 18 → 68 | Three verticals becomes **four**, forty turns later | Scopes **four**. Three means the deal is under-scoped before it starts. |
| 2 | 34 → 36 | "We're around sixty" — a soft number | Records **$55–65k, hard ceiling, licence inclusive**. Never "around 60". |
| 3 | 38 → 40 | **Two** answers to "who signs off" — Aziz, then Tom Vasquez | Surfaces the conflict. Silently keeping the last one heard is the bug. |
| 4 | 58 | Publishing **asked but not answered** | An open question, never a captured fact. Evidence or nothing. |
| 5 | 70 | A correction arriving *during* the read-back | Carries the ":15 may become :06" caveat into the summary. |

Two more worth watching, which are not traps so much as things that are easy to lose:

- **Turn 28 gives two different dates** — air October 3rd, delivery September 12th. A
  summary that collapses them into one date has made the schedule mistake the timeline
  question exists to prevent.
- **Turn 54 is an *uncommitted* extension** to the UK. It must read as a possibility. If
  it is priced as agreed territory, the quote is wrong in the client's favour and we eat it.

## Expected score

This script asks **every question on the sheet** — that is deliberate, and it makes the run
a control. Scored against the script text itself, Phase 1 returns:

> **{expected}**

So on `/opportunity/<id>/prep` after the call, the headline should read **24 of 24
covered**. Anything less is a finding, and where it came from is worth separating:

- **A line comes back `missed` that you know you asked.** The transcript is the first
  suspect, not the detector — open the capture and read what the notetaker actually heard.
  Only if the words are plainly there is it a gap in the cue bank (`call_prep._CUES`).
- **A line comes back covered that you know you skipped.** That is a **false tick**, and it
  is the failure that matters — it manufactures confidence. Note the sentence it printed as
  evidence; that sentence is the fix.

**The `answered` / `raised` split is the real reading.** The headline count above says the
topics came up. It does not say values landed:

- **`answered`** — the extraction pulled a value into Campaign Intelligence from this call.
- **`raised`** — the topic demonstrably came up and **nothing landed in a slot**.

Ten of the sheet's lines are Campaign Intelligence slots; the other fourteen are
conversation and can only ever read `raised`. So the number to watch is the *"Asked, but
nothing stuck"* line. Every slot on it was asked on this call — you have the script to
prove it — which makes each one a clean extraction failure with a known correct answer
sitting in the transcript. That list is the most useful thing this exercise produces.
"""

FOOT_MAR = """
---

## Staying in character

- **You are the client, not the tester.** Don't help. If Jon doesn't ask something,
  don't volunteer it — half of what this exercise measures is what a real call loses.
- **Two lines are corrections and they matter.** At turn 40 you correct who signs off,
  and at turn 70 you correct the cutdown length during the read-back. Deliver both as
  genuine afterthoughts, not as cues.
- **At turn 58 you don't know the answer.** Say so plainly and move on. A question that
  gets no answer has to survive the call as an open question.
- Improvise around the edges — an "um", a false start, a slightly different word — as
  long as the facts land. Speech that sounds like speech is the point.
"""

def block(turns, me):
    out = []
    for i, (who, line, _note) in enumerate(turns, start=1):
        wrapped = textwrap.fill(line, 92, subsequent_indent="  ")
        if who == me:
            out.append(f"**{i} · YOU**\n\n{wrapped}\n")
        else:
            other = "MARISA" if me == JON else "JON"
            out.append(f"> `{i} · {other}` — {textwrap.fill(line, 88, subsequent_indent='> ')}\n")
    return "\n".join(out)


def block_jon(turns):
    """The studio copy carries the operator's margin notes; the client's copy must not."""
    out = []
    for i, (who, line, note) in enumerate(turns, start=1):
        if who == JON:
            out.append(f"**{i} · YOU**\n\n{textwrap.fill(line, 92)}\n")
        else:
            out.append(f"> `{i} · MARISA` — {textwrap.fill(line, 88, subsequent_indent='> ')}\n")
        if note:
            out.append(f"⚠︎ *{textwrap.fill(note, 88)}*\n")
    return "\n".join(out)

os.makedirs("docs/call-scripts", exist_ok=True)
return_transcript = "\n".join(
    f"{'Jon' if w == JON else 'Marisa'}: {l}" for w, l, _n in TURNS)
open("/tmp/transcript.txt", "w").write(return_transcript)

import sys
sys.path.insert(0, "src")
from chordential_oia.call_prep import prep_sheet, score_call
sc = score_call(prep_sheet({}), return_transcript)
expected = sc.text + "."
note = ("Every line on the sheet is covered by design — that is the control. A clean run "
        "proves the path works end to end before you take it into a call that matters.")
if sc.missed:
    note = ("Lines this script does not cover: "
            + ", ".join(l.label for l in sc.missed_lines) + ".")

with open("docs/call-scripts/discovery-call-studio.md", "w") as f:
    f.write(HEAD.format(who="Chordential (Jon)",
                        role="**You are Jon Shipp**, Chordential — you run the call")
            + block_jon(TURNS)
            + FOOT_JON.format(expected=expected, score_note=note))

with open("docs/call-scripts/discovery-call-client.md", "w") as f:
    f.write(HEAD.format(who="the client (Marisa)",
                        role="**You are Marisa Del Rio**, senior producer, Pike & Rowan")
            + block(TURNS, MAR) + FOOT_MAR)

print("SCORE:", sc.text)
print("answered", sc.answered, "raised", sc.raised, "missed", sc.missed)
print("turns:", len(TURNS), "| words:", len(return_transcript.split()))
