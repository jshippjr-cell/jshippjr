# Chordential Delivery OS — Agency Buyer Review

*Reviewer: Dana Whitfield, Senior Producer. I commission original music for brand
campaigns. I've lived in Frame.io, Dropbox, and a thousand email threads. The founder
asked what needs to be fixed, not whether it's pretty — so this is candid. I walked the
two seeded campaigns that matter: **Vance Athletic — Summer Launch** (in review, v2,
Round 2 of 3, timestamped comments) and **Northwind Coffee — Holiday Anthem** (approved,
FINAL locked, ZIP built, released). Everything below is grounded in the actual build.*

---

## The one-paragraph reaction

This is genuinely close to something I'd use. The "one link, no email" review portal plus
the auto-assembled, documented delivery package is exactly the workflow I keep faking with
Dropbox folders and PDF cue sheets a composer hand-types. The delivery moment — *"your
package is ready, download everything"* — is the best part of the whole product and it's
real, not a mockup. But the review loop has friction that Frame.io solved years ago
(I retype my name on every single action, there are no notifications, no reply threads, no
per-comment resolve), and the rights documentation — the thing I have to sell to legal —
quietly undercuts itself in a way procurement *will* catch. Fixable. But today it's a
"yes if," not a "yes."

---

## Stage 1 — The creative brief

**What works.** Opening the Vance console, the brief is right there at the top as the
"start of the record": objective, references, tone, deliverables needed, deadline. The
nice touch is that it's *seeded* — even a brand-new project isn't a blank form; it pulls
the objective from the opportunity's need and references/tone from the description
(`seed_brief` in `delivery.py`). That means a producer never stares at an empty box, and
the brief flows downstream into the package cover and the portal hero.

**Friction / missing.** Two problems. First, the brief is **operator-only**. It lives on
`delivery_console.html`, which is admin-gated. On the client portal
(`delivery_portal.html`) I only get one line of it — `brief.objective` under the hero — and
nothing else. As the buyer, the brief is *my* document; I want to see (and ideally
confirm) the full brief I'm being held to on the same link where I review. Right now I
can't tell whether the composer is working from the brief I approved.

Second, the brief is **free-text and unversioned**. "Deliverables needed" is a prose
field (`:60 anthem, :30/:15 cutdowns, :06 bumper, stems`) that never reconciles against
what actually shows up in the manifest. So the manifest's "Scoped" rows are a *generic*
standard list, not *my* brief's list. If I asked for a :06 bumper and it never appears, the
system doesn't flag it. That's the exact gap I'm paying you to close.

**The improvement.** Show the full brief on the client portal (collapsed is fine), and let
me **acknowledge/lock it** so there's a timestamped "brief approved by Dana" event at the
top of the timeline. Then parse "deliverables needed" into checklist rows and reconcile
them against uploaded assets, so the manifest shows *brief said :06 bumper → not yet
delivered*. That turns the brief from a note into a contract.

---

## Stage 2 — The review portal / one link

**What works.** This is the heart of it and it mostly lands. The token link
(`/project/{id}/delivery-portal?k=…`) drops me straight onto a clean, on-brand page — no
login, no account, like Frame.io's share links. The player is a tidy custom audio bar;
clicking a comment's timecode seeks the track and plays (`data-t` → `currentTime`), which is
the single feature that makes a music review tool feel real. The **Round X of N** chip
("Round 2 of 3" on Vance) is a genuinely smart bit of trust — I instantly know how much
revision runway is left, which is information I normally have to dig a contract out to find.

**Friction / missing.**

- **"Which version am I on?" is half-answered.** The version rail renders chips
  `v1 · v2 (current)` and marks the *last* one current — good. But the rail is **not
  clickable**. I can see v2 is current, but I can't pull up v1 to A/B it. For music that's
  a real loss: directors constantly say "go back to the v1 energy." The player only ever
  loads the current version (`review_track = current`), so the earlier versions are
  visible-but-unplayable.
- **Comments collapse across versions confusingly.** Active-version notes show in full;
  earlier versions' notes get shoved into a dimmed `<details>` "Earlier versions' notes"
  fold. On Vance, the v1 comments (the :12 hook note, the 0:34 drums note) are *the notes
  that produced v2* — burying them under a fold while I review v2 is backwards. I want to
  see "here's what we asked for in v1, here's v2 answering it," side by side.
- **No waveform.** It's a progress bar, not a waveform. Frame.io-for-music's whole promise
  is *pins on the waveform*. Scrubbing to 0:34 by eyeballing a thin orange bar is fiddly;
  a waveform makes timecoded comments feel precise instead of approximate.
- **Comments aren't visually pinned to the timeline.** They're a list below the player. The
  timecode is a link, which is good, but I never *see* the cluster of notes sitting at 0:48
  on the track itself.

**The improvement.** Make the version chips clickable and load that version into the
player (and its comments). Add a real waveform with comment pins. And stop hiding the
prior round's notes — show them as a labeled, answered thread next to the new version.

---

## Stage 3 — Commenting + requesting changes

**What works.** The mechanics are right: the "Comment at 0:48" button ties the note to the
live playhead (`rc-t-val` updates on `timeupdate`), so my comment lands at the timecode I'm
hearing without me typing numbers. That's the correct Frame.io instinct.

**Friction / missing — and this is where it's most annoying.**

- **I retype my name on every single action.** Three separate forms (comment, approve,
  request-changes) each have their own `name="author"` `required` field. There's no "set
  your name once" — no cookie, no localStorage, nothing. In a real review session I'll
  leave fifteen notes and type "Dana Whitfield (Producer)" fifteen times. Frame.io asks
  once. This is the friction I'll complain about out loud on day one.
- **No notifications. At all.** When I leave a comment or request changes, nothing emails
  the composer; when the composer uploads v3, nothing emails me. The entire premise is
  "no email" — but the *coordination* signal is exactly what email was carrying. Without
  notifications, somebody still has to send a "hey, new version's up" message, and we're
  back in the inbox. This is the quiet killer of "one link replaces email."
- **No reply threads, no per-comment resolve.** Comments are a flat tape
  (`kind=comment`). I can't reply to the CD's 0:34 note, and the composer can't mark "0:34
  drums — fixed in v2." On Vance there are four notes and already I want to know which are
  addressed. Frame.io's resolve checkbox is table stakes.
- **The open link is a real exposure.** Anyone with the token can comment, approve, *and
  request changes* — and they self-identify by typing any name they like
  (`_review_token_ok` only checks the token). The "author" is unauthenticated free text. If
  that link gets forwarded to a client stakeholder, *they can press Approve* and trigger
  delivery, signed as whatever name they type. For a one-link convenience that's
  understandable; for the action that locks FINAL and assembles the package, it's too loose.
- **Request-changes note is optional but the form looks required.** The `note` field has no
  `required`, so a changes request can land as a bare "Requested changes." with no
  guidance — and it still burns a revision round. I'd want the note required (and ideally a
  confirm), because each change request increments `revisions_used`.

**The improvement.** Remember my name (cookie/localStorage) so I set it once. Add email
notifications on the two events that matter — new version uploaded, and changes
requested/approved. Add per-comment resolve and at least one level of reply. And gate the
*decision* actions (Approve / Request Changes) behind a lightweight named identity or a
per-reviewer link, even if commenting stays open.

---

## Stage 4 — Approval

**What works.** The consequence of Approve is well-designed under the hood: it logs the
sign-off, **stamps the current version's label to FINAL**, flips state to Delivered, and
**auto-assembles the package** (`review_approve` → `_build_delivery_package`). The
sign-off then appears in a clean "Sign-off" table on the portal and package
(approver + date). That's a real, accountable paper trail — better than "looks good, ship
it" buried in an email.

**Friction / missing — do I trust pressing it?**

- **No confirmation, no preview of consequences.** The Approve button is a green
  `✓ Approve` next to a name box. Pressing it instantly locks FINAL, marks Delivered, and
  builds the ZIP — irreversibly, as far as I can tell from the portal (there's no
  "un-approve"). For an action with that much downstream weight, I want a confirm step that
  tells me *what* I'm approving (which version, which deliverables) and *what happens next*
  ("this locks v2 as FINAL and assembles your delivery package"). Right now I'm trusting a
  button with no warning.
- **Approval is whole-version, not per-asset.** The plan and spec both promise per-asset
  sign-off (":60 master APPROVED · :30 cutdown awaiting"). In the build, Approve signs off
  "the current version" wholesale. In practice I approve the :60 and the :30 separately and
  on different days; one button can't represent that.
- **After delivery, I lose the review surface entirely.** The portal hides the whole
  review/approve card once state is Delivered or Released (`state not in (...)`). So on
  Northwind I can't even *see* the comment history that led to approval from the client
  link — it's gone. The record of how we got to FINAL should survive the hand-off.

**The improvement.** Add a confirm dialog that names the version and lists what's being
locked. Support per-asset approval (the spec already promises it). And keep the comment/
approval history visible (read-only) on delivered campaigns — it's the provenance.

---

## Stage 5 — Delivery automation

**This is the moment that would make me buy.** On Northwind, approval produced a real
`NorthwindCoffee_Delivery.zip` and the portal shows the green *"Your delivery package is
ready"* card with a checklist (the asset labels + Cue Sheet, Metadata, Rights Certificate,
Delivery ZIP) and one fat **"Download everything"** button. After years of "here's a
Dropbox link, the cue sheet is the third PDF, ignore the _FINAL_FINAL_v2 file," this is the
experience I actually want to give my traffic team.

**What works.** The ZIP organizes by folder (`Masters/ Cutdowns/ Social/ Stems/ Assets/
Docs/` via `asset_folder` keyword heuristics), generates four real documents
(`cue_sheet.csv`, `metadata.json`, `rights_certificate.txt`, `manifest.txt`), the version
files carry **deterministic, human-readable names**
(`NORTHWINDCOFFEE_Anthem_60_MASTER_v3_FINAL`), and WAV→MP3 320 conversion runs when ffmpeg
is around without ever blocking the package. The naming convention alone solves the
"someone has v1 downloaded" chaos the founder is fighting.

**Friction / missing.**

- **The folder routing is a fragile keyword guess.** `asset_folder` sorts by substring —
  "stem"→Stems, ":30/edit/instrumental"→Cutdowns, etc. A file labeled "Anthem :60 master"
  lands in Masters by luck of the word "master." Anything ambiguously labeled defaults to
  `Assets/` (or, for audio, Masters). I'd want the operator to *assign* each asset's folder
  explicitly rather than hope the label contains the magic word — misfiled deliverables in
  a procurement package look sloppy.
- **The cue sheet is thin to the point of being not-yet-fileable.** It's two rows
  (main cue + "cutdowns"), **durations are `—` and `var.`**, usage is a bare code (VV/BI),
  and there's no ISRC/ISWC, no timings, no air-date fields. The plan itself flags ISRC/ISWC
  "where relevant" — for a PRO to actually pay backend, durations and proper cue
  identification matter. As-is it's a credible *placeholder*, not the document my music
  supervisor files with BMI.
- **The demo ZIP has no actual audio.** On Northwind the assets are remote-referenced demo
  URLs with empty `filename`, so the seeded ZIP is **docs only** — no masters inside. I
  understand it's a demo, but it means the headline "download everything" currently
  downloads everything *except the music*. The real-upload path is built; the showcase just
  doesn't exercise it, which undersells the best feature.
- **Storage is local disk.** The ZIP lives in the upload dir; the plan flags S3/R2 as the
  durability upgrade. Fine for a PoC, but I'm not handing a client a download link that
  evaporates on the next deploy. I'd ask about persistence before I put my name on it.

**The improvement.** Let the operator confirm/override each asset's folder. Make the cue
sheet real — pull durations from the audio, add ISRC/ISWC fields and per-cue timings.
Wire the demo to a real uploaded master so "download everything" includes the music. And
get durable storage before this touches a paying client.

---

## Stage 6 — Rights / clearance documentation

This is the part I personally have to defend to legal and procurement, so I read it hardest.

**What works.** The Clearance Certificate is the right *idea* and well-presented: client +
campaign, chain of title from the real assignments (composer, mixer — pulled from
`_contributors`, not invented), an original-work warranty in plain language, the license
grant (type / territory / term / exclusivity), and Content-ID-safe status, with a "CLEARED
— original work" seal. The line *"100% original & cleared — no samples, no third-party
masters, no PRO surprises"* is exactly the assurance that distinguishes you from a stock
library, and it's the reason I'd consider you over an AI tool. Genuinely the strongest
strategic asset in the product.

**Friction / missing — and procurement will catch these.**

- **The warranty is asserted, never signed.** `rights_certificate_text` states "Chordential
  warrants that the music… is original work" — but there's no signatory, no entity block,
  no date, no version/asset the warranty attaches to, no governing terms reference. My legal
  team's first question is "warranted by whom, as of when, enforceable how?" A warranty with
  no signature line is marketing copy, not a defensible instrument.
- **"Indemnification available on request" is a yellow flag, not a green one.** I understand
  the founder scoped it to "documented & original, indemnity later." But from the buyer's
  chair, a clearance doc that says original-and-cleared *and then* footnotes "indemnity on
  request" reads as *"we won't actually stand behind this in writing."* Procurement reads
  that line and the whole certificate's confidence drops. Either commit to indemnity for the
  work you authored, or don't surface the word at all — the muted note draws the eye to the
  exact gap.
- **License defaults can over-claim silently.** The defaults are
  "Full buyout / work-made-for-hire," "Worldwide," "Perpetuity," "Exclusive to client for
  the campaign category." If the operator never edits the license, the certificate asserts a
  perpetual worldwide exclusive buyout *by default* — which may be more than the deal
  actually granted. A document that over-promises rights is worse than one that's blank,
  because I'll rely on it. The defaults should be conservative, or flagged as "standard
  terms — confirm per deal."
- **Content-ID "safe" is a claim with no evidence.** It just prints the string
  "Content-ID-safe." There's no safelist registration ID, no platform, no date. For paid
  social that's the assurance I most need to be *true*, and right now it's the assurance
  with the least backing.

**The improvement.** Add a signatory block (entity, signer, date) and attach the warranty
to the specific deliverables/version. Make the license confirmation a required operator step
before a package can be marked released (no silent buyout-by-default). Either back the
Content-ID claim with a reference or soften it. And decide on indemnity — the half-promise is
worse than either commitment.

---

## Stage 7 — The overall feel

Would I choose this over emailing my composer? On a real campaign with a client, a CD, and
three rounds — **yes, the structure beats email**, because email is precisely where versions
and approvals go to die, and this gives me one link, a clear current version, a round
counter, and a documented delivery I can forward to traffic without assembling it myself.
For a quick one-off where I trust the composer completely, email is still faster and I won't
bother.

**The ONE thing that would make me say yes:** the delivery package moment. *Approve → the
package assembles itself → "download everything"* with the cue sheet, rights cert, named
files, and organized folders already done. That's hours of my coordinator's life back per
campaign, and it's the thing no AI tool or library gives me. If you nail that (real audio in
the ZIP, a fileable cue sheet, durable links), it sells itself.

**The ONE thing most likely to make me bounce:** the review loop's missing connective
tissue — **no notifications + retyping my name every action + no resolve/threads.** It makes
the "replaces email" promise feel half-true, because coordination still leaks back to the
inbox. That's the difference between a tool my team adopts and a tool my team opens once.

---

## Top 5 improvements, prioritized

1. **Close the notification loop.** Email (or at least an in-app signal) on the two events
   that carry the workflow: *new version uploaded* (notify the agency) and *changes
   requested / approved* (notify the composer). Without this, "one link, no email" isn't
   true — the coordination just moves back to email manually. Highest impact, because it's
   the load-bearing claim of the whole product.

2. **Make the review session feel like Frame.io.** Remember my name once (cookie/
   localStorage instead of three `required` author fields), add per-comment **resolve**, and
   one level of **reply**. These three together remove the daily friction that decides
   whether my team adopts it.

3. **Make the rights documentation defensible, not just decorative.** Add a signatory block
   (entity + signer + date) attached to the specific version, require explicit license
   confirmation before release (kill silent buyout-by-default), and either commit to
   indemnity or drop the "available on request" line. This is what gets it past my legal/
   procurement gate — without it the differentiator doesn't survive review.

4. **Finish the delivery package so "download everything" is literally true.** Real
   uploaded audio inside the ZIP (wire the demo to it too), operator-assigned folders
   instead of keyword guessing, a fileable cue sheet (real durations, ISRC/ISWC, timings),
   and durable storage so the link survives. This is your best feature — make it complete.

5. **Make versions navigable and the brief a contract.** Clickable version chips that load
   and play each version (A/B the rounds), prior-round notes shown alongside the new version
   instead of hidden in a fold, and a brief that's visible/acknowledgeable on the client
   link and reconciled against delivered assets (brief said :06 bumper → flag if missing).

---

## The verdict

**Yes, if.** I'd run this on my next campaign **if** you close the notification loop and
fix the name-retyping/resolve friction (so it genuinely replaces email, not just the file
transfer), and **if** the rights certificate gets a signatory and a real position on
indemnity (so legal clears it). The delivery-automation payoff is strong enough that I'd
champion it internally the moment those two gaps close. As it stands today — a polished,
real, but coordination-incomplete review loop wrapped around an excellent delivery
moment — it's a confident **"yes if,"** not yet a clean yes. Get items 1–3 above done and
I'm bringing you the Vance brief for real.

*— Dana Whitfield, Senior Producer*
