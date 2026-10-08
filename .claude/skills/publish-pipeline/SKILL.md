---
name: publish-pipeline
description: "Publishes approved marketing content: packages finished posts and asset references into JSON and sends them to n8n, Make, or any other incoming-webhook automation, or optionally straight to a platform API with your own credentials, only after showing the exact payload and getting explicit human approval. Use when the user asks to publish, post, ship, or send content live, trigger the automation, fire the webhook, or send a queued calendar post."
allowed-tools: Read, Write, Edit, Bash
---

# Publish Pipeline

## Purpose

Final handoff step: package finished content and any asset references into
a structured JSON payload, then send it to the user's own automation
system (n8n, Make, or anything else that accepts an incoming webhook) so
it can take over scheduling and posting. By default this skill hands off
to automation the user already owns rather than posting directly — direct
platform posting exists only as an explicit, optional alternate path (see
step 5) for users who've set up their own platform API credentials.

## Step-by-step process

**Where the shared files are.** This skill was installed into this repository
rather than as a plugin (2026-10-08), and every path below was rewritten to the
real one: shared references and scripts live under `.claude/marketing-kit/`, and
sibling skills under `.claude/skills/`. There is no `CLAUDE_PLUGIN_ROOT` to
resolve — use the paths as written.
1. **Check onboarding status.** Read
   `.claude/marketing-kit/references/brand-voice.md`. If it doesn't exist,
   or its first line is `<!-- MARKETING-SKILL:UNCONFIGURED -->`, ask the
   user this plugin's 4 setup questions (priority task; content types to
   produce; target audience + tone; default output format — same as
   `/marketing-skill:marketing-setup`) before continuing, then save the
   answers and flip the marker to `CONFIGURED` with today's date.

2. **Confirm scope.**
   - Which content pieces are ready to send (from `content-repurposer`,
     `visual-brief-generator`, `short-form-video`, `community-post-generator`,
     a row in `state/content-calendar.md`, or pasted directly)?
   - If the source is `community-post-generator`, confirm its Go/No-Go
     section actually said go — never send a draft that skill flagged as
     blocked by the target community's own rules.
   - If the user is pointing at a calendar entry (e.g. "send the queued
     post for Tuesday"), read
     `.claude/marketing-kit/state/content-calendar.md`, find the matching
     row, then **read the post file named in that row's Notes column**
     (`state/posts/<date>-<platform-slug>.md`) — that file, not the
     calendar table, holds the actual content to send. A row with no
     post-file path in Notes, or whose named file doesn't exist, isn't a
     usable source — say so and stop rather than improvising content
     from the short Topic/Hook label. Refuse to re-send a row already
     marked `Sent` without the user explicitly confirming they want to
     send it again.
   - Destination webhook URL, if not already set via `MARKETING_WEBHOOK_URL`.
   - Is this a real send, or a dry run to inspect the payload first?

3. **Assemble the JSON payload** using the exact structure below.

4. **Show a clear, human-readable confirmation before any real send —
   never a raw JSON dump as the only thing shown — and get explicit user
   go-ahead.** This step fires an external side effect the user may not
   be able to easily undo — never skip it, even if the original request
   sounded like blanket authorization (e.g. "just publish it"). **Silence,
   a timeout, or no reply in this conversation is never a yes** — only an
   actual affirmative reply counts, and if none arrives, stop here without
   sending. This applies exactly the same way whether an interactive chat
   or something else (a scheduled or automated trigger) invoked this
   skill — there is no framing of "the run itself is standing
   authorization" that substitutes for a real reply.
   - **Single item:** show four labeled lines before anything else —
     **Account** (which identity this goes out as: the destination
     automation itself for a webhook handoff, e.g. "your n8n webhook," or
     the specific platform identity for a direct post, e.g. "dev.to —
     personal account, not the Organization" or "Instagram Business
     account linked to [Page]"), **Destination** (URL, subreddit, channel,
     or recipient), **Attachments** (each asset's type and source, or
     "none"), and **Final Text** (the actual post/message body, in full,
     not a summary) — then the JSON payload or script command underneath
     as the technical detail, not the primary thing being confirmed.
   - **Batch (more than one item ready at once):** never loop through
     items one at a time asking "send this? ... send this? ..." — that
     pattern gets a "yes" to everything without anyone actually reading
     past the first item or two. Instead list every ready item together,
     numbered, each with its own Account/Destination/Attachments/Final
     Text breakout, and require the reply to name specific numbers (e.g.,
     "1 and 3, yes — skip 2") rather than accepting an unqualified
     "approve all"/"send them" with no numbers attached — treat an
     unqualified blanket reply to a numbered list the same as silence for
     any item it doesn't actually name. Cap a single batch at 10 items; if
     more than 10 are ready, present them in waves of 10 or fewer instead
     of one long list, so the format itself never invites skimming.
   - **Staleness.** For any item sourced from a `state/content-calendar.md`
     or `state/outreach-log.md` row, compare that row's `Date` to today.
     Flag anything more than 14 days old (7 days for an outreach-log row,
     since personalized prospect research ages faster) as **Stale** right
     in the listing, not in a separate report — a batch mixing fresh and
     stale items must show the flag per-row so it can't be missed inside a
     larger "yes to all." Don't refuse to send a stale item outright; just
     make its age impossible to approve past without seeing it.
   - If the source is a `state/content-calendar.md` row, this is the
     point where — and only where — its Status may move to `Approved`,
     immediately after the affirmative reply and immediately before
     sending, and only for the specific numbers actually named. No skill
     in this plugin sets `Approved` at any other time; `content-calendar`
     in particular never writes it.

5. **Send it:**
   - Write the JSON payload to a temporary file (e.g. via `mktemp`).
   - Resolve the webhook URL in this order: an explicit URL the user gave
     > the `MARKETING_WEBHOOK_URL` environment variable > ask the user for
     one if neither is available.
   - Run via Bash:
     `python3 .claude/marketing-kit/scripts/publish_webhook.py --payload-file <tmp-path> --dry-run`
     to preview, then, only after step 4's confirmation,
     `python3 .claude/marketing-kit/scripts/publish_webhook.py --payload-file <tmp-path> --confirmed`
     to actually send. The script refuses to run without one of those two
     flags — there is no default-sends behavior to be careful about.
   - Remove the temporary file afterward regardless of outcome.
   - If the source was a calendar row, update it to `Sent` in
     `state/content-calendar.md` immediately after a successful send
     (keep the row — this is the history log, don't delete it).
   - **Alternate path (optional, not the default): Make MCP.** If a Make
     MCP connector is connected in this session (tools like
     `scenarios_run`, `scenarios_list`), you may call `scenarios_run`
     directly instead of the webhook script, if the user prefers that.
     Don't assume it's connected — check available tools first.
   - **Alternate path (optional, not the default): direct platform
     posting.** If the user wants to post straight to LinkedIn, X, Meta,
     Reddit, Discord, Slack, Telegram, or dev.to rather than handing off to
     their own automation, see `.claude/marketing-kit/scripts/publish_direct.py
     --help`. It only works if the user has already set up real API
     credentials for that platform (see the plugin's `docs/publishing.md`) — check with
     `--dry-run` first, same confirmation rules as above apply, and be
     explicit that this path is less proven than the webhook path since it
     talks to live platform APIs this plugin's author can't verify from
     here. For Reddit specifically, a successful API response doesn't
     guarantee the post survives that subreddit's AutoModerator — confirm
     the content actually came from a `community-post-generator` go (not a
     no-go) before sending. For Discord, Slack, or Telegram specifically,
     confirm the content came from a go too — and since a Discord or Slack
     go is always `User-Supplied` confidence (this skill never
     independently verified that server's/workspace's rules), and a
     Telegram go is `User-Supplied` for a private channel/group but can be
     `Primary`/`Secondary`/`Mixed` for a public one, check which tier this
     specific draft actually rests on rather than assuming — that's one
     more reason not to skip step 4's confirmation just because the
     request "sounds routine." For Slack in particular, also confirm the
     user actually has (or can get) the workspace permission a webhook
     needs before treating the send as a quick step — it isn't guaranteed
     self-serve the way Discord's is. For Telegram in particular, confirm
     the bot has actually been added to the target chat by one of its
     admins — creating the bot itself needs no approval from anyone, but
     that's only the first of two gates, not the whole thing. For dev.to in
     particular, confirm the content came from a go too, and if
     `community-post-generator`'s research couldn't confirm the Code of
     Conduct's self-promotion wording directly, say so before sending — a
     2xx from dev.to's API means the article was accepted, not that a Tag
     Moderator won't strip a tag from it afterward. **Product Hunt, Hacker
     News, and Indie Hackers have no equivalent direct-send path, for
     different reasons** (see `docs/publishing.md`): Product Hunt's write API requires
     special approval from Product Hunt itself; Hacker News's API has no
     write/submit endpoint at all, for anyone; and Indie Hackers' API
     situation is unverified rather than confirmed either way, so it's
     treated as manual-only too — all three always go out by pasting the
     draft in manually (producthunt.com, news.ycombinator.com, or
     indiehackers.com), never through this script, and that's permanent
     for Hacker News, not a "not yet approved" situation. Discord, Slack,
     Telegram, and dev.to each have a real send path but don't share one
     friction profile — Discord's webhook needs no approval step, Slack's
     app often needs Workspace Owner/Admin approval before creation,
     Telegram's bot needs no approval to create but does need a chat admin
     to add it before it can post, and dev.to's API key needs no approval
     process found in this skill's research at all (the simplest of the
     four, though that's about access, not about whether a Tag Moderator
     is happy with the result) — so don't lump any of the four into "every
     non-Reddit platform here is manual-only," and don't lump them into
     each other's ease either.
   - **YouTube, Instagram, and TikTok (`--platform youtube`/`instagram`/
     `tiktok`)** are a different shape from every platform above — all
     three post actual video, and confirm the content came from
     `short-form-video`, not this skill improvising a caption. Don't
     present any of the three with borrowed ease from another:
     - **YouTube** is the most self-serve of the three: the user's own
       Google Cloud OAuth client, authorized against their own channel, is
       enough — no platform-side approval queue the way Reddit or TikTok
       have. It's also the one platform here that uploads a local file
       (`--video-path`) rather than pointing at a hosted URL; confirm the
       asset entry has a real `path`, not just a `url`, before offering this
       path. `--privacy-status` defaults to `private` in the script itself —
       flag that plainly so "just post it" doesn't quietly mean "post it
       where only you can see it."
     - **Instagram Reels** needs the heaviest setup of the three: a Business
       or Creator IG account linked to a Facebook Page, a Meta app with
       `instagram_business_content_publish` actually approved (not just
       Development Mode), and — unlike YouTube — the video already hosted
       at a public URL, since Instagram's API fetches from a URL rather than
       accepting an upload; confirm the asset entry has a real `url` before
       offering this path, and that step 4's confirmation makes clear this
       is a three-step, several-second-to-minutes process (container
       creation, processing, then publish), not instant.
     - **TikTok** needs an app approved for the `video.publish` scope, and —
       critically — **until the app passes TikTok's own audit, TikTok only
       accepts a private (`SELF_ONLY`) post to a creator account that is
       itself set to private, and rejects anything else outright** — it
       doesn't quietly downgrade a public request. The script checks the
       requested privacy level against the creator's allowed options
       (TikTok's required creator_info step) before posting, and stops if
       it isn't one of them. Never present a TikTok send as reaching a public
       audience without the user confirming their app's audit status
       directly in TikTok's developer portal first; a 2xx response only
       means TikTok accepted and queued the request, not that the video is
       live, since TikTok fetches and processes it asynchronously
       afterward. Also needs the video at a public URL, same as Instagram,
       with that URL's domain pre-verified in TikTok's developer portal.

6. **Report the result** plainly: exit code, HTTP status if a real send
   was made, and a one-line human-readable summary of what went where.
   Never report success if the script exited non-zero.

## When to use this skill

Trigger on requests like:
- "Publish this"
- "Send this to n8n / Make"
- "Trigger the automation"
- "Fire the webhook"
- "Send the queued post for [date]" / "approve and send calendar item"

## Payload structure (required)

```json
{
  "run_id": "<uuid or timestamp-based id>",
  "timestamp": "<ISO 8601>",
  "source_skill": "publish-pipeline",
  "content": {
    "linkedin_post": "...",
    "twitter_thread": ["...", "..."],
    "newsletter_blurb": "...",
    "reddit_post": { "subreddit": "...", "title": "...", "body": "..." },
    "discord_message": "...",
    "slack_message": "...",
    "telegram_message": "...",
    "devto_post": { "title": "...", "body": "...", "tags": ["...", "..."] },
    "youtube_short": { "title": "...", "description": "...", "tags": ["...", "..."], "privacy_status": "private|unlisted|public" },
    "instagram_reel": { "caption": "..." },
    "tiktok_video": { "caption": "..." }
  },
  "assets": [
    { "type": "image|video", "description": "...", "url": "...or null", "path": "...or null", "prompt_reference": "...", "platform": "youtube_short|instagram_reel|tiktok_video|..." }
  ],
  "metadata": { "campaign": "...", "brand_voice_version": "..." }
}
```

Omit fields that don't apply (e.g. no `assets` if none were generated),
but keep the top-level shape stable so downstream n8n/Make workflows can
rely on it. For a `youtube_short`/`instagram_reel`/`tiktok_video` entry,
the matching `assets` item needs either `path` (a local file — the only
form YouTube's direct-post option in step 5 can use) or `url` (a
publicly-reachable hosted link — required for Instagram's and TikTok's
direct-post options in step 5, which fetch the video themselves rather
than accepting an upload); which one is available depends on whether
`short-form-video` generated the clip via a connected tool (may produce
either) or the user is supplying their own already-hosted video.

## Formatting rules

- Never claim a send succeeded if the script returned a non-zero exit
  code — report the actual failure and exit code instead.
- Never fire a real send without showing the exact payload and getting
  explicit confirmation first — and never pass `--confirmed` without
  having received an actual affirmative reply in this conversation first.
- Keep the payload's top-level keys stable across runs; add new content
  under `content` rather than renaming existing keys.
- Never write `Approved` to `state/content-calendar.md` except in step 4,
  immediately after a real human reply, immediately before sending.
- Never present a raw JSON payload as the only confirmation surface —
  always break out Account, Destination, Attachments, and Final Text as
  labeled lines first, for both a single item and every item in a batch.
- Never list more than 10 items in one batch confirmation, and never treat
  an unqualified "approve all"/"send them" reply to a numbered list as
  approval for items it doesn't specifically name — only named numbers
  move to `Approved`.
- Never let an item more than 14 days old (7 for an outreach-log row) pass
  through a confirmation listing without a visible Stale flag on that row.
- For `youtube`/`instagram`/`tiktok` sends specifically: never report a
  2xx response as "the video is live" — Instagram and TikTok both process
  the video asynchronously after that response, so report exactly what the
  script itself reported (queued/processing vs. confirmed published), and
  never claim a TikTok send reached a public audience without the user
  having confirmed their app's audit status.

## Example output

**Confirmation display, single item** (shown before the dry run below,
never replaced by it):
```
Account: your n8n webhook (automation handoff, not a direct platform post)
Destination: https://your-n8n-host/webhook/abc123
Attachments: none
Final Text:
  Speed got us here. It won't be the only thing that keeps us here...
  (full LinkedIn post text)

Reply to confirm this exact send, or say what to change first.
```

**Confirmation display, batch of three, one stale:**
```
Three rows are ready to send. Reply with the numbers to approve (e.g.
"1 and 3, skip 2") — an unqualified "send them all" won't be treated as
approving any of these.

1. [Stale — queued 19 days ago] Account: your n8n webhook · Destination:
   https://your-n8n-host/webhook/abc123 · Attachments: none · Final Text:
   "Most teams lose an afternoon a month to manual exports..."
2. Account: dev.to — personal account · Destination: dev.to (tags:
   showdev, saas) · Attachments: none · Final Text: "I built this because
   our own export flow was the thing customers complained about most..."
3. Account: your n8n webhook · Destination: https://your-n8n-host/webhook/abc123
   · Attachments: 1 image (state/assets/export-diagram.png) · Final Text:
   "One-click export is live today for every customer..."
```
Reported this way regardless of how the request was phrased ("send the
ready ones," "go ahead with today's batch") — a reply naming specific
numbers is the only thing that moves those rows to `Approved`.

**Dry run** (the technical payload behind a single confirmed item):
```
$ python3 .claude/marketing-kit/scripts/publish_webhook.py --payload-file /tmp/payload.json --dry-run
=== DRY RUN: no request sent ===
Method: POST
URL: https://your-n8n-host/webhook/abc123
Headers:
  Content-Type: application/json
Body (application/json, 412 bytes):
{
  "run_id": "2026-09-25T14-30-00",
  "timestamp": "2026-09-25T14:30:00Z",
  ...
}
=== END DRY RUN ===
```
Reported to the user as: "Dry run only — nothing was sent. Here's the
exact payload and destination above; confirm to send for real."

**Real send, success:**
```
Sent to https://your-n8n-host/webhook/abc123
Status: 200 OK
Response: (empty body)
```
Reported as: "Sent successfully (200 OK) to your n8n webhook."

**Real send, failure:**
```
Webhook returned non-2xx status
Status: 500 Internal Server Error
Response: {"error": "workflow disabled"}
```
Reported as: "Send failed — the endpoint returned 500 (workflow
disabled). Nothing further was attempted."
