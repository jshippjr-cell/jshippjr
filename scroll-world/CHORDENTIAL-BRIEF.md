# Chordential scroll-world — build brief (LOCKED)

Resumable spec for the scroll-world landing page. Bootstrap is done; only Higgsfield
auth + credits remain before generation.

## Bootstrap status
- [x] Python 3 + Pillow
- [x] ffmpeg / ffprobe v7.0 (static, no-admin, symlinked ~/.local/bin)
- [x] scroll-world skill installed (~/.claude/skills/scroll-world)
- [x] Higgsfield CLI 1.1.18 (npm global)
- [ ] `higgsfield auth login`  ← USER (interactive OAuth; agent cannot run)
- [ ] Higgsfield credits funded ← USER (payment)

## Creative brief
- **Subject:** Chordential — "procurement-grade original music, from brief to cleared master."
- **Art direction (style preamble, reused verbatim in every scene prompt):**
  soft matte low-poly CLAY DIORAMA, isometric, tilt-shift miniature, warm light.
- **Brand palette (from repo, OKLCH source):**
  - accent/orange `#E4671F` (primary/go)
  - wine (deep) `#44161E`
  - cream `oklch(0.98 0.005 3.336)`, sand `oklch(0.851 0.033 85.479)`
  - olive `oklch(0.555 0.017 111.153)`, slate `oklch(0.499 0.028 234.95)`
  - ink `oklch(0.236 0.002 17.265)`
- **Camera architecture:** B (diorama dives + aerial connectors) — fits the miniature look.
- **Mobile:** YES — native 9:16 portrait chain (not a crop).
- **Render tier:** FREE TRIAL mode — `seedance_2_0` @ **720p** (trial cap), 8s max.
  Desktop masters are 720p, not 1080p; re-render finals at 1080p only if paid later.
- **Stills model:** **`nano_banana_pro`** @ 2K (trial's image model; not gpt_image_2).
- **Billing:** 1-Day Free Unlimited Trial. $0 today, card required. AUTO-RENEWS to
  Plus $59/mo in 24h → USER MUST CANCEL within 24h. All generation must finish in-window.
- **First action after auth:** test-meter 1 still + 1 video to confirm the CLI can use
  the trial (trials are sometimes web-UI only).

## Journey (6 scenes — LOCKED, user-authored 2026-07-17)
Emotional arc: pressure → intention → emotion → payoff → quiet reveal → resolution.
Pacing (engine `linger`/`scroll`): Scene 4 (Approval) is the emotional CLIMAX → high
linger; Scene 6 (Hero) is the resolution → high scroll + linger. Transit scenes brisk.

**HARD "do NOT show" guardrails (bake into every prompt):**
no AI imagery, no prompts/robots, no dashboards/screens/UI, no logos, no marketplace grid.

1. **The Brief** — *"Every campaign starts with a creative brief."*
   The problem. An agency with a campaign: quiet pressure, deadline, expectation —
   NOT chaos. Composed tension in a creative agency space.
2. **The Match** — *"We assemble the right creative team for the work."*
   Answers "Why Chordential?" — the right creative team assembled with intention.
   The "Creative Network" concept, NOT a marketplace/dashboard. People, not AI.
3. **The Composer's Studio** — *"Original music begins with people—not prompts."*
   Emotion enters; music is finally heard. Hands on keys, notation, strings, the
   creative process. The moment you're unmistakably a music company.
4. **Approval** — *"Built to survive approval."*  ← MOVED before Delivery OS; CLIMAX.
   The emotional payoff agencies actually celebrate. Client smiles, Creative Director
   approves, producer relaxes — everything aligned.
5. **Delivery OS** — *"Everything arrives organized, cleared, and ready."*
   Reveal the machine as INVISIBLE INFRASTRUCTURE, not the hero. Organized assets,
   stems, cue sheet, versions, rights, delivery package. Reveal — don't explain.
   (Sell confidence, not software; ChordOS stays hidden.)
6. **Hero** — end tag: *"Original music for campaigns. Composed. Cleared. Delivered."*
   NOT ChordOS, NOT the logo, NOT dashboards. The campaign itself: the commercial,
   the film, the brand, the audience — the music living where it belongs.

## Cost estimate (confirm by test-metering 1 still + 1 video vs live balance)
- Assets: 6 stills + 22 videos (11 desktop dives+connectors, 11 mobile).
- Standard tier ballpark: ~1190 credits + ~15% reroll headroom ≈ **~1370 credits.**
- Buy a little extra (interiors/studio scenes trip the NSFW filter → rerolls).

## Next actions once authed (agent will do)
test-meter cost → generate 6 stills → USER reviews cohesion → dives (seq/parallel per arch)
→ connectors (frame-locked seams) → encode (crf20, -g8, blob) → mobile 9:16 chain
→ wire scrub-engine.js into FastAPI/Jinja site (new route) → QA seams headless.
