# ChordOS Launch Review — ten-seat panel

**Date:** 2026-08-03 · **Method:** ten reviewers working independently, blind to each
other, each required to cite file:line, quoted code/copy, or what a rendered page
actually showed. 98 raw findings; the ones below survived cross-examination against the
code. Roughly a third of the raw findings did not and were dropped.

Seats: Principal Product Designer · Principal UX Researcher · Staff Interaction Designer ·
Principal Information Architect · Senior Software Architect · Enterprise Solutions
Architect · Creative Director · Executive Producer (daily operator) · Commercial Music
Producer (industry accuracy) · Accessibility & Performance Engineer.

## The verdict in one paragraph

The premium product exists — the papercraft film, the commission room, the Delivery
Console's five gates, the deterministic engines — but it was not connected to itself. The
public site's conversion graph was broken at nearly every edge; the console answers its own
core question ("what is waiting on me?") three different ways with three different numbers;
pricing speaks with four disagreeing voices; and the clearance certificate — the single
thing the market is asked to pay a premium for — contradicts itself as a legal document.
Almost none of this required building. It required wiring, reconciling, and deleting.

---

## The ten findings that mattered

1. **`/commission` could not convert.** All six CTAs were `href="#brief"`, and `#brief`
   was the closing section whose only content was two more `#brief` buttons. No link to
   `/start`, `/book` or any other page existed in the 2,121-line file. *(Fixed — Phase 1.)*
2. **Sitewide nav was dead at both ends.** `Work → /#reel` and `About → /#about` rendered
   on every brochure page; both anchors existed only on retired homepages. The post-submit
   thank-you page sent every fresh lead to the same dead anchor. Found independently by
   five of ten seats. *(Fixed — Phase 1.)*
3. **The homepage was a conversion dead end.** No persistent CTA, no nav to any other
   page, no way to hear a note of music, and the section nav hidden entirely below 860px.
   *(CTA fixed — Phase 1, and the requirement now rides with whatever page is the front
   door rather than one page's mechanism.)* ***"Hear the work" is closed too
   (ADR-0040):*** the hero's listen CTA played a **WebAudio oscillator** two lines under
   a promise of "never AI-generated audio". The homepage now carries the four real
   capability demonstrations, and the synth says its tone is browser-generated.
4. **Front-of-house was three homepages plus six orphans** — the root cause of 1–3.
   `/commission`, `/experience`, `/samples`, `/showreel`, `/stills`, `/delivery-sample` had
   zero inbound links; `home.html` was rendered by no route yet was the only thing linking
   `/samples`. Each retired homepage left stale links behind. ***Resolved.*** `home.html`
   was deleted, the flagship question was settled — **the Commission is the front door** —
   and the two retired homepages were then deleted outright rather than parked at second
   addresses, on the operator's call: nothing pointed at either, so keeping them would only
   have grown the orphan set that caused this finding. Their masters are archived in
   `media/masters/`, so the films themselves are re-cuttable. Front-of-house is now one
   flagship plus its brochure pages.
5. **Marking a deal Won erased its recorded value.** The board and stepper post `status`
   alone; `update_status` assigned `outcome_value` unconditionally, writing NULL.
   Reproduced live on seeded data. *(Fixed — Phase 1, with a regression test.)*
6. **Three answers to "what is waiting on me?"** Dashboard said 2, `/queue` said 11, on the
   same database — separately coded aggregators. The next-action ladder ignored recorded
   stage, so a **Won** deal in active delivery showed "Schedule the discovery call" as the
   featured move. ***Fixed — Phase 2 (ADR-0029).*** `queue.compute_queue()` is the only
   computation; the dashboard reports its length and links to `/queue`, its inline sum is
   deleted, and the duplicate "▶ Your move" table is gone. The ladder now treats the
   recorded stage as a floor. **The three money ledgers are fixed too (ADR-0030):**
   `db.open_pipeline()` is the only valuation — our bid, else the disclosed budget's
   midpoint, else counted as unknown — and it returns its own composition so the figure
   can be explained. `/revenue` no longer sources open pipeline from `proposals`, a table
   that cannot hold a row until the deal is already won.
7. **Pricing spoke with four voices.** Public `/commission` band $9–18k for a national
   :30; the engine priced the same brief at $4,847; the client-facing band rendered
   ≈$3.1–6.6k. The estimator also classified a brief by its **smallest** duration — ":60
   anthem with :30 and :15 cutdowns" priced as a :15 spot at half the bare :30 — and had
   no cost line for session players. ***Fixed — Phase 2 (ADR-0028).*** The public band is
   now the single prior, rendered into the page from `estimation.PUBLIC_BANDS`; role hours
   describe a campaign cue rather than a demo; players and the room are a real session
   line instead of a ×4 on desk hours; usage is a fee on price, not a production cost. The
   engine now lands inside the public band ($10,414 against $9–18k), and tests assert it.
   ***The nine call sites are closed too (ADR-0033):*** `web.estimate.estimate_for` is the
   only way the web layer prices anything. Two of the nine — the dashboard KPI and the
   project estimate — skipped the qualified-fallback, so a disqualified deal priced at
   **$7,810 on the dashboard and $8,350 on its own estimate page**; and only one of the
   nine resolved assigned rates. ***The last thread — the outreach cadence — is closed
   too (ADR-0034), and pulling it found three more:*** four surfaces derived a client
   quote four ways. The two the **same buyer reads** disagreed — the Campaign Brief
   showed Brightline **$7,200–$15,100** while the Commercial Review showed
   **$20,000–$40,000** — and the pursuit checklist printed our *production cost*
   ($4,342–$9,018) labelled "Provide an indicative quote". It reached the money as well:
   a generated proposal totalled **$9,712** where the client's own review implied
   **$8,000**. `capabilities.quote_band` is now the only authority — client brief,
   commercial review, checklist, cadence, proposal total and deposit all render it.
8. **The clearance certificate contradicted itself.** "Full buyout / work-made-for-hire"
   coexists with Chordential-as-100%-publisher cue sheets and category-limited
   exclusivity; the cue sheet credited mixers and PMs as composers and hardcoded BMI; the
   licence has no media dimension. The portal stamped CLEARED over draft terms and marked
   items "Delivered" on upload, before sign-off. *(Seal gating + the Delivered/Uploaded
   wording fixed — Phase 1.)* **The cue sheet is fileable now (ADR-0031):** writers only
   in the composer column, writer and publisher share as separate accounts, PRO per writer
   from `talent.pro`, and usage derived from the brief instead of asserting `VV` — a sung
   on-camera performance — for every campaign bed. Reproduced before: `composers='Maya
   Chen, Leo Park, Ana Ruiz, Sam Diaz'` — the mixer, the editor and the project manager
   all filed as authors. ***And the rights model is settled (ADR-0032, operator ruling):***
   the client buys the **master** outright with a **perpetual sync licence** across every
   campaign medium; the **composition's publishing is retained**, which is what makes the
   cue sheet — and the royalties it collects — coherent. The licence gained the missing
   `media` dimension and an explicit `publishing` term, both now printed on the
   certificate. The sales copy moved with it: "you own it" → "you own the recording and
   the right to use it forever", and "no PRO surprises" (beside a cue sheet we file *with*
   a PRO) → "nothing to clear but ours". **Finding 8 is closed.**
9. **Client media was not durable.** `render.yaml` never set `CHORDENTIAL_UPLOAD_DIR`, so
   prod uploads landed in the installed package — wiped on every deploy, and `autoDeploy`
   means every push. Files over the 64 MB mirror cap had no durable copy at all; under it
   they are double-stored as file + DB blob on a 1 GB disk. *(Pointed at the persistent
   disk — Phase 1; object storage is Phase 3 and remains the real fix.)*
10. **Trust surfaces contradicted their own promises.** Three in-code claims that share-link
    guests cannot approve, against code that deliberately allows it; no share-token
    revocation; lost-update races on `delivery_json`; and the AI cost confirm fired *after*
    the capture-phase handler had already dispatched the paid request, under a fabricated
    ease-to-90% progress bar. *(Copy reconciled, guard and fake progress fixed — Phase 1;
    concurrency and revocation are Phase 3.)*

---

## Phase 1 — shipped before launch

| Fix | Evidence it addressed |
|---|---|
| Six `/commission` CTAs → `/start` / `/book`; wordmark links home | `commission.html:554–769` |
| `Work` → `/samples`, `About` deleted, `/reel` → `/samples`, thanks-page CTA repointed | `public_base.html:19–21`, `thanks.html:34` |
| Persistent homepage CTA (header + fixed dock on the Commission) | the film's only CTAs sat after five viewport-heights |
| `home.html` deleted | rendered by no route |
| `update_status` COALESCEs `outcome_value` | reproduced data loss |
| Shadowed second `/webhooks/stripe` handler deleted | `app.py:8839–8877`, divergent logic |
| `CHORDENTIAL_UPLOAD_DIR` → `/var/data/uploads` | uploads on ephemeral disk |
| Spend guard moved into the capture handler (`data-confirm`) | Cancel did not cancel the charge |
| Ease-to-90% fake progress deleted outright | three loading states, one fabricated |
| CLEARED seal gated on confirmed grant + certified version | seal over draft terms |
| Client-facing "Delivered" → "Uploaded" | status fires on upload, pre-sign-off |
| Portal contributors show roles, not names | anonymity model |
| Approval-gate copy matches ADR-0020 behaviour | three false claims |
| GZip, but never on Range responses or already-compressed media | nothing was compressed |
| `--accent-text` / `--accent-solid` contrast tokens in `style.css`, `site.css` **and** `delivery_portal.html` | ember text at 3.16:1, failing AA |
| Real trademark out of the demo brief | invented-brands rule |

Measured after: `/commission` 718 KB → 187 KB transferred; ember text 5.0–5.7:1 and white
on ember 4.69:1 (all pass AA); the client delivery portal went from 8 measured AA failures
to 0; zero dead anchors on any live page; the Won-erases-value reproduction now preserves
the number.

Two things worth knowing for the next pass. **Compression is not a one-liner here.**
Starlette's `GZipMiddleware` compresses on size alone with no notion of Range, so adding
it naively gzipped 206 bodies while leaving `content-range` describing the uncompressed
extent — which would have broken the homepage film, since the scroll scrub *is* a series
of range requests. `SelectiveGZip` bypasses Range requests and already-compressed
extensions; there are tests for both. **And the palette lives in more than one place:**
`delivery_portal.html` carries its own `:root`, so the shared token fix did not reach the
one page a client's accessibility review will actually open. Any future palette change
has to touch `style.css`, `site.css`, and the standalone templates.

---

## Phase 2 — high-impact, post-launch

~~One waiting-on-me aggregator (`queue.py` owns it; delete the dashboard's parallel
computation) and stage-floored next actions~~ ✔ · ~~one pricing voice (the
duration-ordering fix, band reconciliation, a session/recording cost block)~~ ✔ ·
~~one estimate call path (`estimate_for()`)~~ ✔ · ~~one
open-pipeline number~~ ✔ · ~~fileable cue sheets~~ ✔ · ~~one rights basis~~ ✔ ·
~~console nav diet~~ ✔ · ~~portal ordered by court-state~~ ✔ ·
~~brand-unified `/start` `/book` `/thanks` with a budget field~~ ✔ ·
~~naming system stops fabricating `_60_MASTER` on :30 spots~~ ✔ · ~~real byte-progress on console
uploads~~ ✔ · ~~share-token rotation~~ ✔ · ~~"hear the work" on the homepage~~ ✔ ·
~~finish the contrast pass: `--olive`~~ ✔ — ruled by the operator and darkened to
`#65665B` (ADR-0041). It was worse than filed: under AA on **three** of four console
surfaces, and the same value survived unfixed in `brief.css` and `first_touch.html`,
two documents a **client** reads.

**Phase 2 is complete.**

## Phase 3 — strategic architecture

~~Object storage (resolves three findings at once)~~ — **the seam is in** (ADR-0043):
every write and read now goes through `storage.get_object_store()`, local by default,
S3/R2 on a flag. Four of five uploaded files had exactly one copy before it, because
three routes bypassed the mirroring helper. *The bucket migration itself is an ops step
and is not done.* · ~~`app.py` into modules~~ — the large groups are **done** (ADR-0044):
~~`app.py` into modules~~ — **done** (ADR-0044): `shell.py` + twelve route modules + the
helper layer (`uploads`, `billing`, `delivery_ops`, `opportunity_ops`), **9,133 → 655
lines, 251 → 15 routes**, with all 252 route declarations conserved. What is left in
`app.py` is only the application object. Was:
domain routers with the delivery and pipeline state machines moved into the engines ·
request-scoped connections, pooling, indexes (there are none), batched dashboard context ·
`delivery_json` concurrency — promote `asset_approvals` / `versions` to rows · scheduler
advisory locks before the blue-green cutover · ~~Postgres in CI so the regex dialect shim cannot corrupt silently~~ ✔ (ADR-0045) —
it had never met a Postgres; running one found **three** cutover-day defects, incl.
a migration that crashed mid-copy on production data · buyer identity as a canonical entity.

## Phase 4 — long-term

Multi-user auth with actor identity on every decision (precondition for the first hire) ·
one Relationship Intelligence layer (the Buyer Graph and Relationship Management are
disjoint tables today) · minutes-of-music estimation so the film/TV engagement can be
priced · real e-signature · token lifecycle and delegated client access.

---

## Note on method

Findings were required to be provable. Where seats disagreed the code decided: the
guest-approve contradiction was resolved in favour of the code (ADR-0020 makes the
client's single approval the award, so it must not depend on a link they may not have)
and the false docstrings were corrected instead. The "promote or cut `/commission`"
split was resolved as promote-and-link, because the page was built deliberately and its
only defect was that nothing pointed at it or out of it.
