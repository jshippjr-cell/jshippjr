# Chordential Delivery OS — Agency Buyer Re-Review (Round 2)

*Reviewer: Dana Whitfield, Senior Producer. Same chair, second pass. The team did
three improvement passes (IP1 trust/coordination, IP2 review polish, IP3 defensible
rights + finished package) against my first write-up. I went back into the actual
build — the portal, console, and package templates, the review/delivery routes in
`app.py`, the engine in `delivery.py`, and the seed — and checked each fix landed,
not just that it was claimed. I re-walked both campaigns that matter: **Vance
Athletic — Summer Launch** (In review, v2, Round 2 of 3) and **Northwind Coffee —
Holiday Anthem** (Released, FINAL locked, ZIP built). Candid as before.*

---

## The one-paragraph reaction

They listened. This is a real second draft, not a coat of paint. Four of my five
top items are genuinely fixed in code: I set my name once and it sticks, I can
resolve and reply to notes, I can click into v1 and actually play it, the rights
certificate now has a signatory and refuses to release until the license is
confirmed, the indemnity half-promise is gone, and the ZIP bundles real local audio
with an honest README. That's most of what was blocking me. But two things keep this
from a clean yes, and they're the same shape as before: **the notification loop is
still only half-wired** (the operator gets pinged when I act; I get *nothing* when a
new version lands — and that's the half that decides whether coordination leaks back
to email), and **the showcase still undersells the best feature** because the seeded
demos carry no local files, so the "download everything" ZIP on Northwind is *still*
docs-only. Plus the demo's own certificate prints the exact bare "Content-ID-safe"
claim the engine was rebuilt to stop printing. Close. Closer than last time. Read on.

---

## (1) Did my top-5 get fixed?

### Top-1 — Close the notification loop → **PARTIAL**

**What landed.** There's now a real operator notification path. `_notify_operator_review`
(`app.py:3073`) fires on every decision event: comment, reply, request-changes, and
approve all call it (`review_comment` 3154, `review_changes` 3307, `review_approve`
3258), pushing through both `webpush.send_web_push` and `signals.send_push` with a
campaign-labeled title and a deep link to the console. Best-effort, wrapped so push
failure never blocks the action. Good — when I comment, Jon's phone buzzes. That's
the operator-direction half, and it's done properly.

**Where it falls short.** The *agency-direction* half — notify **me** when the
composer uploads a new version — is **not built**. It's an explicit TODO sitting in
the code (`app.py:3082-3085`): *"agency-direction notifications… Requires a
transactional send channel (deferred outbound email infra) — not wired yet, so left
unimplemented rather than faked."* And true to that, `delivery_version`
(`app.py:2871`) logs v3, advances state, reopens to "In review" — and sends nothing
to me. So the exact failure I named last round still stands: *somebody still has to
send me a "new version's up" message, and we're back in the inbox.* I respect that
they didn't fake it (a fake email channel would be worse). But from the buyer's
chair, the load-bearing claim — "one link replaces email" — is still only true in the
Jon→me direction by him watching the console, and *not at all* in the me-finds-out
direction. This is the single biggest reason I'm not at a clean yes.

### Top-2 — Make the review session feel like Frame.io → **FIXED**

Verified all three sub-parts in code:

- **Set my name once.** Identity is captured in a `cdl_reviewer` cookie
  (`_set_reviewer_cookie`, `app.py:3059`) and rehydrated on every action
  (`_reviewer_identity`, 3042). The portal shows a "Who's reviewing?" block that
  hides once known, a "Reviewing as Dana <email> — change" line, and JS that fills
  the hidden `author`/`email` on every `.review-act` form
  (`delivery_portal.html:462-502`). The three forms no longer each demand a retype.
  This is the daily friction gone.
- **Per-comment resolve/reopen.** Real route (`review_resolve`, `app.py:3164`) +
  real engine (`toggle_comment_resolved`, `db.py:2393`, project-scoped so one
  campaign's token can't toggle another's). The portal renders a Resolve/Reopen
  button per top-level note, strikes through resolved ones, and shows a live
  "**N** open · **M** resolved on vX" count (`delivery_portal.html:203, 220`).
- **One level of reply.** `parent_id` threads a reply under its parent
  (`add_review_comment` carries it, `db.py:2353`; the comment route nests it with no
  timecode, `app.py:3132-3152`), and the portal renders an indented thread under each
  note with a Reply toggle (`delivery_portal.html:224-245`).

This is the Frame.io connective tissue I asked for, and it's wired through engine →
route → template, not faked in the UI. Clean fix.

### Top-3 — Make the rights documentation defensible → **FIXED** (with one demo-data smudge)

- **Signatory block.** `ClearanceCertificate` now carries `signatory`,
  `certified_version`, `certified_date` (`delivery.py:256-259`); the cert text
  renders an entity / authorized-signer+title / signature line / date block
  (`rights_certificate_text` 806-817), and both the portal ("Certified by") and the
  package (Document 02 "Signatory" panel) show it attached to the certified version.
  The warranty now has a name and a date on it. My legal team's "warranted by whom,
  as of when" is answered.
- **License confirmation gates release.** `delivery_release` (`app.py:2971`) flatly
  **refuses** to release until `license_confirmation(delivery)` is non-null, bouncing
  back with `?release=needs_license`; the console surfaces the refusal banner and a
  "Confirm license terms" action (`delivery_console.html:131-149`). Until confirmed,
  the cert prints "GRANT OF RIGHTS / LICENSE — DRAFT — pending confirmation" with a
  "NOT yet asserted as the deal grant" caveat (`delivery.py:779-788`), and the portal
  shows "Grant of rights — Draft, pending confirmation." Editing the license re-voids
  the confirmation (`app.py:2664`). No more silent perpetual-worldwide-exclusive
  buyout-by-default. This is exactly the gate I asked for.
- **Indemnity.** Gone — and gone *thoroughly*. The module docstring documents the
  scope decision, and I grepped: there is no indemnity field, clause, or mention
  anywhere in `delivery.py` or the templates. The yellow flag that drew the eye to
  the gap is simply absent now. Correct call.
- **Honest Content-ID.** The bare "Content-ID-safe" assertion is replaced by
  `CONTENT_ID_HONEST` ("Original work — no third-party masters or samples, so no
  third-party Content-ID claims; the recording is registrable with Content ID by the
  rights-holder", `delivery.py:80`), and the default license state is "Registrable
  with Content ID." Honest, defensible language.

**The one smudge (data, not engine).** The engine is fixed, but the **seed** for
Northwind still hard-codes `_DELIVERY_DEMO_LICENSE = {... "content_id":
"Content-ID-safe"}` (`seed.py:198`). Because that's an operator-set value it
overrides the honest default, so the *delivered demo's* certificate and portal print
"Content-ID: Content-ID-safe" — the precise bare claim the rebuild set out to kill.
The fix is real; the showcase contradicts it. A buyer clicking the one finished
example sees the un-fixed string. I'm grading the item Fixed because the instrument
is right, but fix the seed — your demo is arguing against your own improvement.

### Top-4 — Finish the delivery package so "download everything" is literally true → **PARTIAL**

- **Real audio in the ZIP — engine fixed, demo still hollow.** `build_delivery_zip`
  now writes the *actual local files* into folders, converts WAV→MP3 320 best-effort,
  and — crucially — records any URL-only asset as "referenced, not bundled" in
  `Docs/README.txt` so the package is honest about what's inside (`delivery.py:1009-1048`).
  That's the right architecture. **But** every seeded version and asset has
  `filename: ""` (it points at Cloudinary demo URLs — `seed.py:309-419`), so on
  Northwind, the headline "Download everything" ZIP is *still docs-only* — exactly my
  complaint from round one. The real-upload path is built and correct; the one
  finished showcase still doesn't exercise it. To a buyer evaluating on the demo, the
  best feature still downloads everything except the music. Wire one real master into
  the Northwind seed and this flips to Fixed.
- **Operator-assigned folders → FIXED.** `asset_folder` honors an operator-assigned
  `folder` over the keyword heuristic (`delivery.py:671-693`), the route exists
  (`delivery_set_asset_folder`, `app.py:2714`), and the console gives each asset a
  folder dropdown (`delivery_console.html:245-254`). No more hoping the label contains
  the magic word.
- **Fileable cue sheet → FIXED.** `CueRow` gained `duration`, `isrc`, `iswc`
  (`delivery.py:332-334`); the CSV header is now Cue/Usage/Duration/ISRC/ISWC/
  Composer/Publisher/PRO/Share% (`cue_sheet_csv` 706); operator-fillable per cue via
  `delivery_set_cue_meta` (`app.py:2743`) and the console form. The package's Cue
  Sheet page shows the new columns. It's now a structurally fileable sheet — the
  fields a coordinator needs are present (blank-allowed, which is fine — those are
  the agency's to fill). Genuinely improved from the two-row placeholder.
- **Durable storage → still local disk.** Honestly flagged in the code comments
  (`app.py:69-71, 1918-1923`) — the ZIP lives in `UPLOAD_DIR`, not durable on Render's
  blue-green cutover. Same caveat as last round. Acceptable for a PoC, still a
  "before you put my name on it" question.

Net: three of four sub-items solidly fixed, but the headline ("download everything"
literally true *in the demo*) and durability are not, so this is a Partial — closer,
not closed.

### Top-5 — Make versions navigable and the brief a contract → **PARTIAL**

- **Navigable versions → FIXED.** This is a real, satisfying fix. The portal version
  chips are now links (`?v=<n>`, `delivery_portal.html:178-179`); `_delivery_view`
  resolves `selected_v`, loads *that* version's track into the player, and filters
  comments to that version (`app.py:2496-2531`). A "You're viewing v1 — an earlier
  round · Back to current" banner makes the state obvious. I can finally A/B v1 vs v2
  and play each — the "go back to the v1 energy" request is now answerable.
- **Prior-round notes shown, fold gone → FIXED.** The dimmed "Earlier versions'
  notes" `<details>` fold is gone; selecting a version surfaces that version's notes
  inline with an open/resolved count. The provenance is also preserved read-only
  after delivery in a "Review history" card (`delivery_portal.html:281-297`) — which
  also closes my old Stage-4 complaint that the history vanished post-handoff.
- **Brief as a contract → MISSED.** Still operator-only. On the client portal I get
  exactly one line — `brief.objective` under the hero (`delivery_portal.html:123`) —
  and nothing else; the full brief lives on the admin console. There's no way for me
  to *see* the full brief I'm held to on the review link, no acknowledge/lock step,
  and `deliverables_needed` is still free prose that is never reconciled against the
  manifest (the "Scoped" rows remain the generic standard list, `build_manifest`
  `delivery.py:438-442`). "Brief said :06 bumper → not delivered" still isn't flagged.
  This was the lowest-priority half of a low-priority item, so I don't weight it
  heavily — but it's untouched, so the overall item is Partial.

---

## (2) Stage-by-stage walk — what works now / what still bugs me

**Brief.** Same as round one for the buyer: rich on the console, one line on my link.
Vance's brief ("energetic :60 anthem… :60 anthem, :30/:15 cutdowns, :06 bumper,
stems") is a real brief — but I only see the objective, and the :06 bumper in it is
never checked against what's delivered. *Still bugs me:* the brief isn't my document
on my link, and it's not reconciled.

**One-link portal.** Still the strong center. Token link drops me straight in, no
login. *Works now:* version chips are clickable and play; the viewing-an-earlier-round
banner is clear. *Still bugs me:* it's a progress bar, not a waveform, and comments
are a list below the player rather than pins on the timeline. Both are polish I named
last round and would still take — but they're not blockers.

**Commenting (identity / resolve / reply).** This is the most improved stage. I set
my name once and every subsequent note, reply, resolve, approve, and change-request
carries it without a retype. Resolve strikes the note and updates the open count;
reply threads cleanly one level deep. *Still bugs me, mildly:* the open-link exposure
I flagged before is *partly* addressed — decision actions (approve/changes/resolve)
now require a complete name+email server-side (`app.py:3232, 3295, 3179`), so they're
attributable — but "attributable" is self-typed identity, not authenticated. Anyone
with the forwarded token can still type *any* name+email and press Approve, which
locks FINAL and assembles the package. For a convenience link that's a defensible
trade; for the single most consequential button in the product it still makes me
slightly nervous. A per-reviewer link or a lightweight verification would close it.

**Version navigation.** Fixed and genuinely nice — covered above. No remaining
complaint here beyond the missing waveform.

**Approval (confirm + attribution + operator notify).** Big improvement. The Approve
button now fires a native `confirm()` naming the version and consequences ("Approve
v2 for delivery? This locks it as FINAL and assembles your delivery package",
`delivery_portal.html:263`), the sign-off records name+email+version+date and shows
it in a "Sign-off" card, and Jon gets pushed. A new version after approval correctly
reopens to "In review" and supersedes the prior approval (`app.py:2940`). *Still bugs
me:* approval is still **whole-version, not per-asset** — the spec and both docs
still promise ":60 master APPROVED · :30 cutdown awaiting," but one button signs off
the whole current version. In real life I approve the :60 and the :30 on different
days. The `approvals` list is per-asset-shaped in the data but the portal's Approve
button only ever signs the current version wholesale.

**Delivery automation + ZIP.** The payoff card still lands emotionally — green "Your
delivery package is ready," the checklist, the one fat "Download everything." The
engine behind it is now correct (real files, folders, honest README, MP3 conversion).
*Still bugs me:* on the *demo* the ZIP is docs-only because the seed has no local
files, so the showcase undersells the exact moment that would make me buy. And the
link still lives on ephemeral local disk.

**Rights / clearance docs.** The strongest strategic asset got materially stronger:
signatory, confirmation-gated release, draft-until-confirmed language, honest
Content-ID, indemnity removed. This now reads like an instrument, not marketing copy.
*Still bugs me:* the seed's `"Content-ID-safe"` override prints the bare claim on the
finished demo (engine fixed, data not), and the Content-ID assurance — even in its
honest form — still carries no registration ID/reference, which for paid social is
the assurance I'd most want evidenced. Lesser than before, but present.

---

## (3) New issues I found this round

1. **The demo contradicts the IP3 rights fix.** `seed.py:198` hard-codes
   `content_id: "Content-ID-safe"`, so the one Released showcase prints the exact
   bare claim the engine was rebuilt to eliminate. Worse than a cosmetic bug — it's
   the demo arguing against the improvement a buyer came to see.

2. **The showcase ZIP is still hollow.** Every seeded version/asset has
   `filename: ""` (`seed.py`), so Northwind's "Download everything" yields docs only.
   The fix exists; the demo doesn't exercise it. This was my round-one complaint and
   it survived three passes — the new-build path is right, but nobody wired a real
   master into the seed to *show* it.

3. **Agency-direction notification is a known hole, not an oversight — but still a
   hole.** Honest TODO, deliberately not faked. Respect the integrity, but it means
   the "replaces email" promise is still one-directional, and that's the buyer-facing
   gap.

4. **Approve is still pressable by anyone with the link, signed as any typed name.**
   Identity is now *required* and recorded, which is better, but it's unverified
   self-identification on the action that locks FINAL and builds the package. If the
   link is forwarded to a junior stakeholder, they can approve as "anyone."

5. **Per-asset approval is promised, still not delivered.** The data model and docs
   imply per-asset sign-off; the portal only does whole-version. On multi-deliverable
   campaigns (the norm) this misrepresents how approval actually happens.

6. **Content-ID claim still has no backing reference.** Even honest, it's a state
   string with no registration ID/platform/date. For paid social, the assurance I
   most need true is the one with the least evidence behind it.

---

## (4) Updated top-5 for the next round

1. **Finish the notification loop in the agency direction.** When a new version is
   uploaded (and ideally when the operator replies), notify the reviewer at the
   captured `review_comments.email`. This is the deferred outbound-send infra — build
   it. Until I find out a new version is up *without leaving the inbox*, "one link
   replaces email" isn't true, and this is the single thing most likely to keep my
   team in their mail client.

2. **Make the showcase tell the truth — wire real local audio into the Northwind
   seed and drop the `"Content-ID-safe"` override.** Two small seed edits that make
   "Download everything" actually include music and stop the demo from printing the
   one claim you rebuilt the engine to avoid. Your best feature and your best
   differentiator are both being undersold by their own demo.

3. **Gate the Approve action behind verified identity (per-reviewer link or a
   lightweight confirm-by-email).** Required-but-typed identity is an improvement;
   for the button that locks FINAL and assembles the package, make the signer
   provably who they say they are.

4. **Deliver per-asset approval.** Let me sign off the :60 and the :30 separately, on
   different days, as the spec and both documents already promise. One whole-version
   button doesn't match how a real multi-deliverable campaign gets approved.

5. **Make the brief my document on my link, and reconcile it.** Show the full brief
   (collapsed is fine) on the client portal with an acknowledge/lock step, and parse
   `deliverables_needed` into checklist rows reconciled against delivered assets so
   "brief said :06 bumper → not yet delivered" surfaces automatically. Turns the brief
   from a note into a contract. (Waveform + comment pins are the nice-to-have I'd take
   alongside this.)

---

## (5) The verdict — and would I run my next campaign on this

**Yes-if — but a much smaller "if," and the needle moved a long way toward yes.**

Last round I held back on three things: the notification loop, the
name-retyping/resolve/reply friction, and a defensible rights certificate. **Two of
those three are now genuinely done.** The review session feels like Frame.io now — I
set my name once, I resolve and reply, I A/B and play any version, the approval is
confirmed and attributed and the history survives the hand-off. The rights
certificate is now something I'd actually hand to legal: signed, dated,
confirmation-gated, indemnity-honest. Those were two of my three blockers and they're
cleared.

What still blocks a *clean* yes is narrow and specific: **the agency-direction
notification is not built**, so coordination still leaks back to email in the one
direction that matters most to me (finding out a new version is up); and **the
finished demo undersells itself** — the ZIP is docs-only and the certificate prints
the bare Content-ID claim the engine was fixed to stop printing — so the two features
that would make me champion this internally aren't actually demonstrated working.
Both are fixable in a focused pass; neither is architectural.

So: would I run my next campaign on this? **For a campaign where I'm willing to watch
the console (or where Jon pings me himself), yes — I'd run it today**, because
everything from my comment to the approved, documented, signed delivery package is
now real and better than my Dropbox-and-email status quo. For it to be a tool my team
adopts *without* anyone babysitting the inbox — a flat, unqualified yes — close item 1
(notify me on new versions) and item 2 (make the demo honest). Do those two and I'm
not bringing you the Vance brief as a test. I'm bringing you the real one.

*— Dana Whitfield, Senior Producer*
