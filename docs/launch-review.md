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
3. **The homepage was a conversion dead end.** No persistent CTA (the scroll engine has
   supported one all along at `scrub-engine.js:123`; `world.html` never passed it), no nav
   to any other page, no way to hear a note of music, and the section nav is hidden
   entirely below 860px. *(CTA fixed — Phase 1; "hear the work" is Phase 2.)*
4. **Front-of-house was three homepages plus six orphans** — the root cause of 1–3.
   `/commission`, `/experience`, `/samples`, `/showreel`, `/stills`, `/delivery-sample` had
   zero inbound links; `home.html` was rendered by no route yet was the only thing linking
   `/samples`. Each retired homepage left stale links behind. *(`home.html` deleted —
   Phase 1; the rest is Phase 2's "one flagship, chapters not competitors".)*
5. **Marking a deal Won erased its recorded value.** The board and stepper post `status`
   alone; `update_status` assigned `outcome_value` unconditionally, writing NULL.
   Reproduced live on seeded data. *(Fixed — Phase 1, with a regression test.)*
6. **Three answers to "what is waiting on me?"** Dashboard said 2, `/queue` said 11, on the
   same database — separately coded aggregators. The next-action ladder ignores recorded
   stage, so a **Won** deal in active delivery showed "Schedule the discovery call" as the
   featured move. Three money ledgers disagree the same way ($15,000 / $4,847 / $0).
   *(Phase 2.)*
7. **Pricing speaks with four voices.** Public `/commission` band $9–18k for a national
   :30; the engine prices the same brief at $4,847; the client-facing band renders
   ≈$3.1–6.6k; outreach says quote ~$8,694 while the commercial engine quotes $15–30k. The
   estimator also classifies a brief by its **smallest** duration — ":60 anthem with :30
   and :15 cutdowns" prices as a :15 spot at half the bare :30 — and has no cost line for
   session players. The estimate idiom is copy-pasted at nine divergent call sites.
   *(Phase 2.)*
8. **The clearance certificate contradicted itself.** "Full buyout / work-made-for-hire"
   coexists with Chordential-as-100%-publisher cue sheets and category-limited
   exclusivity; the cue sheet credits mixers and PMs as composers and hardcodes BMI; the
   license has no media dimension. The portal stamped CLEARED over draft terms and marked
   items "Delivered" on upload, before sign-off. *(Seal gating + the Delivered/Uploaded
   wording fixed — Phase 1; the rights model itself is Phase 2.)*
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
| Persistent homepage CTA via the engine's existing `config.cta` | `scrub-engine.js:123` unused |
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

One waiting-on-me aggregator (`queue.py` owns it; delete the dashboard's parallel
computation) and stage-floored next actions · one pricing voice (`estimate_for()`, the
duration-ordering fix, band reconciliation, a session/recording cost block) · one
open-pipeline number · brand-unified `/start` `/book` `/thanks` with a budget field ·
console nav diet (remove `/lanes`, the three filter quick-links; `/incoming` as the only
triage surface) · portal ordered by court-state · fileable cue sheets (writers only as
composers, split writer/publisher shares, per-contributor PRO, media on the license) ·
naming system stops fabricating `_60_MASTER` on :30 spots · real byte-progress on console
uploads · share-token rotation · one flagship with `/commission` as its linked chapter and
"hear the work" on the homepage · finish the contrast pass: `--olive` (#737469) is a brand
token used as body text on internal surfaces at 4.47:1, marginally under AA — changing it
is a palette decision, not a bug fix, so it was left out of Phase 1.

## Phase 3 — strategic architecture

Object storage (resolves three findings at once) · `app.py` (9,019 lines, 253 routes) into
domain routers with the delivery and pipeline state machines moved into the engines ·
request-scoped connections, pooling, indexes (there are none), batched dashboard context ·
`delivery_json` concurrency — promote `asset_approvals` / `versions` to rows · scheduler
advisory locks before the blue-green cutover · Postgres in CI so the regex dialect shim
cannot corrupt silently · buyer identity as a canonical entity.

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
