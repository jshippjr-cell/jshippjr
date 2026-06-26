# Chordential Delivery OS — Full Build Spec ("Frame.io for music" + delivery automation)

*Captures the founder's full vision (2026-06-26). The build target for the whole
delivery experience — every touchpoint, demoable on fictional campaigns. Phase-0
(Pass A: delivery engine + Clearance package + token-gated portal) is already built;
this spec extends it to the complete system and ends with an **agency-reviewer
critique** of the finished experience.*

---

## The problem (in the founder's words)

Music review and delivery happen over **email + attachments**, so:
- Composer emails V1 → agency replies → V2 → producer forwards → CD comments → client
  comments → agency notes → V3 …
- Someone reviews the **wrong version**. Someone has **V1 downloaded**. **Chaos.**
- After approval, someone **manually** exports Broadcast Mix → Instrumental → :30 →
  :15 → :06 → VO mix → stems → cue sheet → rights PDF → zip → Dropbox → email. **Tedious.**

## The vision (two pillars)

**1. The Review Portal — Frame.io for music.** The agency gets **one link per
campaign**. Each version has a player and **timestamped comments pinned to the
waveform**, plus **Approve / Request Changes**. Everything in one place — no emails,
no attachments, no version confusion.

**2. Delivery Automation — on APPROVE, the package assembles itself.** The instant the
agency approves, the system gathers the deliverables, generates the cue sheet +
metadata + rights certificate, format-converts, zips, and tells the agency *"Your
delivery package is ready — download everything."*

> **Automation, not AI.** The system organizes, documents, converts, packages, and
> delivers. The *creative* variants (the :30 edit, the instrumental, the stems) are
> produced once by the composer and uploaded once; the system then moves them through
> the pipeline. It never synthesizes music.

---

## Every touchpoint to build (the founder's list)

| Touchpoint | What it is |
|---|---|
| **Creative brief** | The campaign's objective/spec — the start of the record; seeds the package. |
| **Campaign dashboard** | One screen per campaign: brief, versions, comments, approvals, deliverables, timeline. |
| **Review portal** (client) | One link; versioned players; **timestamped comments**; Approve / Request Changes. |
| **Revision system** | Rounds scoped vs used; request-changes loop; feedback captured against versions. |
| **Version naming** | Deterministic, human-readable: `CAMPAIGN_CUE_LEN_ROLE_vN_STATE` (e.g. `AURORA_Anthem_60_MASTER_v3_FINAL`). |
| **Delivery folders** | Auto-organized structure (Masters / Cutdowns / Social / Stems / Docs). |
| **Cue sheets** | Auto-generated PRO cue sheet (so the client gets their backend royalties). |
| **Rights documents** | The Clearance Certificate (documented & original; indemnity later). |
| **Approval workflow** | Per-version + per-asset sign-off; locks the FINAL version; triggers delivery. |
| **Timeline** | Campaign chronology: brief → v1 → notes → v2 → approval → delivered. |
| **Delivery automation** | APPROVE → assemble + document + convert + ZIP → "download everything." |

Demoed on **fictional campaigns** (invented brands, e.g. *Aurora Outdoor — Summer
Anthem*, *Vance Athletic — Launch* — **not real trademarks**, consistent with the
honesty rule: never imply real client work).

---

## What's already built (Pass A — the foundation)

`delivery.py` (Clearance Certificate / cue sheet / manifest builders), per-project
`delivery_json` state, the generated print-ready **Clearance-Certified delivery
package**, a **token-gated client delivery portal**, local asset upload, logged
approvals. The new work extends these — it does not restart.

---

## Build phases (foreground, the founder's pace)

**P1 — Review Portal v1 (the centerpiece).** Per-campaign client link with: versioned
audio players, **timestamped comments** pinned to the waveform (anyone with the link
can add a comment at a time-code), comment threads, and **Approve / Request Changes**.
Comments + approvals persist per version. (Extends the token-gated portal.)

**P2 — Versions + revisions + naming.** A real version model (v1/v2/v3 + state),
deterministic version naming, the request-changes → new-version loop, rounds
scoped-vs-used. Producer/CD/client comments all land on the version.

**P3 — Delivery automation (the exciting one).** On APPROVE of the FINAL version:
auto-organize the uploaded deliverables into the named folder structure, auto-generate
cue sheet + metadata + rights certificate, **format-convert** (WAV→MP3 320,
loudness-prep) and **build the delivery ZIP** server-side, then surface *"package ready
— download everything."* (ffmpeg for conversions; deterministic assembly. Creative
variants are uploaded, not generated.)

**P4 — Creative brief + timeline + campaign dashboard.** The brief object that opens
the record; the campaign timeline (brief → versions → notes → approval → delivered);
the one-screen campaign dashboard tying brief, review, approvals, deliverables, and
timeline together.

**P5 — Seed fictional campaigns.** 2–3 realistic invented campaigns at different stages
(in-review with comments, approved+delivered, just-briefed) so the whole experience is
walkable end to end.

**P6 — The Agency-Reviewer critique (capstone).** A simulated **ad-agency producer /
creative director** persona walks the finished experience **stage by stage** — brief →
review portal → commenting → approval → delivery — and reports, candidly, **what works
and what must be improved** (clarity, trust, friction, what would make them choose
Chordential over email). Their feedback becomes the next round of work.

---

## Cross-cutting

- **Storage:** local for now (founder's call); the ZIP + converted files live in the
  upload dir. S3/R2 is the later durability upgrade.
- **Comments are open on the link** (anyone with the token can comment, like Frame.io)
  — no per-commenter login in v1; they identify themselves by name on the comment.
- **Honesty:** fictional brands only; the system documents real work, never fakes it.
- **Pattern:** deterministic + human-in-the-loop. Jon (or the composer) uploads and
  presses the buttons; the agency reviews and approves; the machine does the busywork.
