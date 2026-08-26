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


# ── the sendable pair ────────────────────────────────────────────────────────────
# A PDF, because the point is to TEXT it to whoever reads the other half, and markdown
# arrives on a phone as either a download nobody opens or a wall of asterisks.
#
# Sized 4.25 x 7.5in rather than A4 ON PURPOSE. A letter-width page fitted to a phone
# screen scales to about half, which turns comfortable body text into something you
# squint at while trying to act. A narrow page fits at roughly 0.8 and stays readable in
# the hand — the script is read aloud from the device, not filed.
CSS = """
@page { size: 4.25in 7.5in; margin: 0.42in 0.4in 0.5in; }
* { box-sizing: border-box; }
body { margin:0; font: 15px/1.5 Georgia,'Times New Roman',serif; color:#241016;
       -webkit-print-color-adjust:exact; print-color-adjust:exact; }
h1 { font: 700 20px/1.2 Georgia,serif; margin:0 0 2px; }
.kicker { font:700 9px/1.4 Helvetica,Arial,sans-serif; letter-spacing:.14em;
          text-transform:uppercase; color:#b34a21; margin:0 0 10px; }
.role { font:600 15px/1.4 Georgia,serif; margin:0 0 4px; }
.meta { font:13px/1.45 Georgia,serif; color:#6f6660; margin:0 0 14px; }
.rule { border:0; border-top:2px solid #b34a21; margin:14px 0; }
.how { background:#faf3ee; border:1px solid #e7e1d8; border-radius:8px; padding:11px 12px;
       margin:0 0 16px; }
.how h2 { font:700 10px/1.4 Helvetica,Arial,sans-serif; letter-spacing:.12em;
          text-transform:uppercase; color:#8a4b1d; margin:0 0 7px; }
.how ol { margin:0; padding-left:17px; font-size:13px; line-height:1.5; }
.how li { margin:0 0 6px; }
.how li:last-child { margin:0; }
.turn { margin:0 0 13px; page-break-inside:avoid; break-inside:avoid; }
.n { font:700 9px/1 Helvetica,Arial,sans-serif; letter-spacing:.1em;
     color:#b0a69c; display:block; margin:0 0 3px; }
.you .n { color:#b34a21; }
.you p { margin:0; font-size:16.5px; line-height:1.48; font-weight:600; }
.them { padding-left:11px; border-left:2px solid #e0d8ce; }
.them p { margin:0; font-size:13.5px; line-height:1.45; color:#6f6660; font-style:italic; }
.note { margin:6px 0 0; padding:7px 9px; background:#fff6ec; border-left:2px solid #d98b2b;
        font:12.5px/1.42 Helvetica,Arial,sans-serif; color:#6a4a1c; }
.back { page-break-before:always; break-before:page; }
.back h2 { font:700 15px/1.3 Georgia,serif; margin:0 0 4px; }
.back h3 { font:700 10px/1.4 Helvetica,Arial,sans-serif; letter-spacing:.12em;
           text-transform:uppercase; color:#b34a21; margin:16px 0 6px; }
.back p, .back li { font-size:13px; line-height:1.5; }
.back ul { margin:0 0 10px; padding-left:16px; }
.back li { margin:0 0 7px; }
.trap { border:1px solid #e7e1d8; border-radius:8px; padding:9px 11px; margin:0 0 8px;
        page-break-inside:avoid; }
.trap .w { font:700 9.5px/1.3 Helvetica,Arial,sans-serif; letter-spacing:.1em;
           text-transform:uppercase; color:#b34a21; margin:0 0 3px; }
.trap .t { font-weight:700; margin:0 0 3px; font-size:13px; }
.trap .f { margin:0; font-size:12.5px; color:#6f6660; }
.score { background:#faf3ee; border-left:3px solid #b34a21; border-radius:0 8px 8px 0;
         padding:10px 12px; margin:8px 0 12px; }
.score .big { font:700 17px/1.3 Georgia,serif; margin:0; }
"""

HOW = """<div class="how"><h2>How to run it</h2><ol>
<li>Two readers, one script each. <b>Both are numbered the same</b>, and the other person's
lines are printed so you never lose your place.</li>
<li>Schedule the call in Chordential so the notetaker joins, then start the Zoom.</li>
<li><b>Read at talking pace, not reading pace.</b> Pause, overlap, say &ldquo;um&rdquo;. It is
being tested against speech &mdash; a flat recitation tests nothing that matters.</li>
<li>About <b>10&ndash;12 minutes</b>. Don't rush the read-back near the end; it is doing real
work.</li></ol></div>"""


def esc(t):
    return (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def turns_html(turns, me, notes):
    out, other = [], ("MARISA" if me == JON else "JON")
    for i, (who, line, note) in enumerate(turns, start=1):
        cls, who_lbl = ("you", "YOU") if who == me else ("them", other)
        out.append(f'<div class="turn {cls}"><span class="n">{i} &middot; {who_lbl}</span>'
                   f'<p>{esc(line)}</p>')
        if note and notes:
            out.append(f'<div class="note">{esc(note)}</div>')
        out.append("</div>")
    return "\n".join(out)


TRAPS = [
    ("Turns 18 &rarr; 68", "Three verticals quietly becomes four, forty turns later.",
     "The summary must scope FOUR. Three means the deal is under-scoped before it starts."),
    ("Turns 34 &rarr; 36", "&ldquo;We're around sixty&rdquo; &mdash; a soft number.",
     "Must land as $55&ndash;65k, hard ceiling, licence inclusive. Never &ldquo;around 60&rdquo;."),
    ("Turns 38 &rarr; 40", "Two answers to who signs off &mdash; Aziz, then Tom Vasquez.",
     "The conflict has to surface. Silently keeping whichever was heard last is the bug."),
    ("Turn 58", "Publishing is asked and NOT answered.",
     "It must survive as an open question, never a captured fact. Evidence or nothing."),
    ("Turn 70", "A correction arrives during the read-back.",
     "The &ldquo;:15 may become :06&rdquo; caveat has to reach the summary."),
]


def back_html(expected):
    traps = "".join(
        f'<div class="trap"><p class="w">{w}</p><p class="t">{t}</p><p class="f">{f}</p></div>'
        for w, t, f in TRAPS)
    return f"""<div class="back">
<h2>What this call is engineered to break</h2>
<p>Five deliberate traps, in the order they arrive. Each is a real failure this system has
had or could have. The exercise is checking the summary catches them &mdash; not checking the
transcript is tidy.</p>
{traps}
<h3>Two more, easy to lose</h3>
<ul>
<li><b>Turn 28 gives two different dates</b> &mdash; air October 3rd, delivery September 12th.
A summary that collapses them into one has made the schedule mistake the timeline question
exists to prevent.</li>
<li><b>Turn 54 is an uncommitted extension</b> to the UK. It must read as a possibility. Priced
as agreed territory, the quote is wrong in the client's favour and we eat it.</li>
</ul>
<h3>Expected score</h3>
<p>This script asks <b>every question on the sheet</b>, which makes the run a control with a
known answer. Scored against the script text, Phase&nbsp;1 returns:</p>
<div class="score"><p class="big">{expected}</p></div>
<p>So the prep page should read <b>24 of 24 covered</b>. Less than that is a finding:</p>
<ul>
<li><b>A line comes back missed that you know you asked.</b> Suspect the transcript first &mdash;
read what the notetaker actually heard. Only if the words are plainly there is it a gap in the
cue bank.</li>
<li><b>A line comes back covered that you know you skipped.</b> That is a false tick, and it is
the failure that matters, because it manufactures confidence. Note the sentence it printed as
evidence; that sentence is the fix.</li>
</ul>
<h3>The number actually worth reading</h3>
<p>Not the headline &mdash; the <b>answered / raised</b> split. Ten of the twenty-four lines are
Campaign Intelligence slots; the other fourteen are conversation and can only ever read
<i>raised</i>. So watch the <b>&ldquo;Asked, but nothing stuck&rdquo;</b> line. Every slot on it
was asked on this call and you have the script to prove it, which makes each one a clean
extraction failure with the right answer sitting in the transcript.</p></div>"""


CLIENT_BACK = """<div class="back">
<h2>Staying in character</h2>
<ul>
<li><b>You are the client, not the tester. Don't help.</b> If Jon doesn't ask something, don't
volunteer it &mdash; half of what this measures is what a real call loses.</li>
<li><b>Two of your lines are corrections, and they matter.</b> At turn 40 you correct who signs
off; at turn 70 you correct the cutdown length during the read-back. Deliver both as genuine
afterthoughts, not as cues.</li>
<li><b>At turn 58 you don't know the answer.</b> Say so plainly and move on. A question that gets
no answer has to survive the call as an open question.</li>
<li>Improvise at the edges &mdash; an &ldquo;um&rdquo;, a false start, a different word &mdash; as
long as the facts land. Speech that sounds like speech is the point.</li>
</ul></div>"""

PAGE = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>{title}</title><style>{css}</style></head><body>
<p class="kicker">Discovery call &middot; test script</p>
<h1>{h1}</h1>
<p class="role">{role}</p>
<p class="meta">A Chordential discovery call &middot; HALVARD, &ldquo;Long Way Home&rdquo;
&middot; agency: Pike &amp; Rowan.<br><b>Every name and brand here is invented.</b> Nothing in
this call describes real client work.</p>
<hr class="rule">
{how}{turns}{back}</body></html>"""

for path, title, h1, role, tn, bk in [
    ("docs/call-scripts/discovery-call-studio.html",
     "Discovery call script - the studio (Jon)", "Your half &mdash; the studio",
     "You are <b>Jon Shipp</b>, Chordential. You run the call.",
     turns_html(TURNS, JON, notes=True), back_html(expected)),
    ("docs/call-scripts/discovery-call-client.html",
     "Discovery call script - the client (Marisa)", "Your half &mdash; the client",
     "You are <b>Marisa Del Rio</b>, senior producer at Pike &amp; Rowan.",
     turns_html(TURNS, MAR, notes=False), CLIENT_BACK)]:
    open(path, "w").write(PAGE.format(css=CSS, title=title, h1=h1, role=role,
                                      how=HOW, turns=tn, back=bk))
print("html: 2 files")

# The PDF is the artifact that actually gets sent, so it is built here rather than by
# hand. Chromium prints it: the page is a designed thing (two voices at two weights) and a
# generic PDF writer would flatten that back into paragraphs. Skipped with a message when
# Playwright is absent — the markdown and HTML are still written, and a missing browser
# must not fail the build.
def _pdfs():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("pdf: skipped (no playwright)")
        return
    import pathlib
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        pg = b.new_page()
        for name in ("discovery-call-studio", "discovery-call-client"):
            src = pathlib.Path("docs/call-scripts", name + ".html").resolve()
            out = os.path.join("docs/call-scripts", name + ".pdf")
            pg.goto(src.as_uri())
            pg.wait_for_timeout(300)
            pg.pdf(path=out, width="4.25in", height="7.5in", print_background=True,
                   margin={"top": "0.42in", "bottom": "0.5in",
                           "left": "0.4in", "right": "0.4in"})
            print(f"pdf: {out} ({os.path.getsize(out) // 1024} KB)")
        b.close()


_pdfs()
