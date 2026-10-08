<!-- MARKETING-SKILL:UNCONFIGURED -->
# Brand Voice & Marketing Preferences

> This file is the single source of truth every skill in this plugin reads
> before producing output. Edit it directly, or run
> `/marketing-skill:marketing-setup` for a guided conversational setup.
>
> The first line of this file is a machine-readable marker. Skills check it
> to decide whether onboarding is needed — leave it exactly as
> `<!-- MARKETING-SKILL:UNCONFIGURED -->` until you've actually set your
> preferences, then it will be updated automatically to
> `<!-- MARKETING-SKILL:CONFIGURED (last updated: YYYY-MM-DD) -->`.

## Priority Task
Not yet configured — run `/marketing-skill:marketing-setup` or edit this
directly. (This is the marketing task you want automated first: e.g.
weekly newsletters, competitor research, blog-to-social repurposing.)

## Content Types
Not yet configured. Placeholder default: "whatever content type fits the
skill in use (text/social posts, short-form video scripts, long-form
video scripts, email, images); ask if unclear which one to prioritize."
(This is the medium you actually want produced — e.g. short-form video
scripts for Reels/TikTok/Shorts, long-form video scripts, text/social
posts, email, images, or a mix — as distinct from the *structure* set
under "Default Output Format" below.)

## Target Audience
Not yet configured. Placeholder default: "general B2B software buyers."

## Brand Voice & Tone
Not yet configured. Placeholder default: "confident, plain-spoken, a little
dry; avoid corporate jargon and hype."

## Default Output Format
Not yet configured. Placeholder default: "produce all supported formats for
the skill in use, unless the user asks for one specifically."

## Banned Words & Phrases
- "game-changer"
- "revolutionary"
- "synergy"
- "seamless"
- "unlock"
- "supercharge"
- "in today's fast-paced world"
- "at the end of the day"

(Placeholder generic list — replace with your own banned words, house
style exceptions, or competitor names to avoid naming directly.)

## Formatting Constraints
- Oxford comma: yes (placeholder default)
- Emoji: none in long-form copy; sparing use allowed in social posts only
  if the user asks for it
- Heading style: sentence case
- Sentence length: prefer short-to-medium sentences; avoid run-ons

## Do / Don't Examples
- Don't: "Our revolutionary platform will supercharge your workflow!"
- Do: "The platform cuts manual steps from your workflow."

## Sonic Identity
Not yet configured. The sound of every video rendered for this project:
the same genre, tempo, key, and signature hook each time, so viewers start
to recognize it. `short-form-video` (or `/marketing-skill:marketing-setup`)
proposes two options with audio previews and saves your pick here; see
`references/sound-guide.md`. Once set, it looks like:

- Genre: tech
- Tempo: 112 BPM
- Key: C major
- Energy: 3 (of 5)
- Hook: 1 5 3 5 | 6 5 3 2
- Why: clean and optimistic, for technical buyers; no hype

## Visual Identity
Not yet configured. The look of every video rendered for this project:
its colors, a display font, and the logo and handle on the end card that
lands with the sonic logo, so every video looks like the same brand.
`short-form-video` (or `/marketing-skill:marketing-setup`) asks for it and
saves it here, and `scripts/video/brand.js` applies it to a page. Once
set, it looks like:

- Accent: #2f6fed
- Background: #0b1020
- Text: #f5f7ff
- Font: Space Grotesk
- Logo: state/videos/assets/logo.png
- Handle: @yourbrand
