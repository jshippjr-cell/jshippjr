# The marketing team — how it runs

The founder talks to **one seat: the CEO** (the session titled *Opportunity intelligence
agent*, which also holds the codebase). The CEO dispatches to eight role sessions, one per
charter in this directory, and reads what they produce. The founder can open any role's
session from the sidebar at any time, read the whole conversation, and reply directly to
redirect it.

## The rules every role session follows

1. **Read `docs/marketing/00-brief.md` first.** It is the canon. A role that contradicts
   it is wrong, not creative. If a role believes the brief is wrong, it says so in its
   deliverable under a heading **"Objection to the brief"** and carries on under the
   brief as written. The CEO takes objections to the founder.
2. **Read your own charter** (`docs/marketing/agents/<role>.md`) and the roadmap
   (`docs/marketing/roadmap.md`).
3. **Write your deliverable to `docs/marketing/deliverables/<role>.md`.** Nothing else.
   No side documents, no artifacts, no edits to the brief or another role's file.
4. **Commit and push to the branch you were given.** Pull before you push; the files do
   not overlap, so conflicts mean something went wrong.
5. **Facts or nothing.** Chordential has no delivered client work yet. No case studies,
   testimonials, logos, "trusted by", or named clients. Demo work uses invented brands
   (AURORA, Vance Athletic). A real organisation, show or event may be named only when
   you are confident it exists; mark anything to confirm with **(verify)**.
6. **No AI-generated music, anywhere, including as a demo.** Say so plainly in copy.
7. **The review round.** When the CEO asks, read every other role's deliverable and write
   your objections, merges and priorities to `docs/marketing/reviews/<role>.md`. Challenge
   weak ideas by name. Merge duplicates. Do not praise.
8. **Report back in one message** when done: what you decided, what you cut, what you
   could not resolve, and the commit hash.

## The waves

| Wave | Roles | Depends on |
|---|---|---|
| 1 | Brand Strategist | the brief |
| 2 | Content Strategist · Community & Outreach · SEO & Website · Analytics | wave 1 |
| 3 | Social Media Manager · LinkedIn Growth · Outbound Strategy | wave 2 |
| 4 | Review round, all eight | waves 1–3 |

The founder checks in with the CEO between waves. That is where a correction is cheap.
