# Reddit Discovery Setup — the cap-free F5Bot replacement

Polls a short allowlist of high-intent subreddits directly through Reddit's
official API and lands real music gigs on the Signal Radar (with a phone alert),
through the same `is_music_gig` filter the rest of the engine uses. Unlike F5Bot
there's **no 50/day cap and no silent auto-disable** — Chordential controls the
polling.

## Why credentials are required

Reddit blocks unauthenticated API traffic from datacenters (Render), so the feed
only activates once app credentials are set — otherwise it would just 403. App
credentials are an *app's* client id/secret (client-credentials grant), **never
your Reddit password**.

## One-time: create a Reddit app

1. Sign in at **reddit.com**, then go to
   **reddit.com/prefs/apps** (Settings → Safety & Privacy → "Manage third-party
   app authorization" → developer apps).
2. **Create another app…** →
   - **name:** `chordential-discovery`
   - **type:** **script**
   - **redirect uri:** `http://localhost` (unused, but required)
3. Create. You'll see:
   - the **client id** (the short string just under the app name), and
   - the **secret**.

## Render env vars

| Variable | Value |
|---|---|
| `REDDIT_CLIENT_ID` | the client id |
| `REDDIT_CLIENT_SECRET` | the secret (mark secret) |

That's it — the feed auto-activates on the next deploy (it's already enabled by
`CHORDENTIAL_ENABLE_SCRAPE`, which you have on). Optional knobs:

| Variable | Default |
|---|---|
| `CHORDENTIAL_REDDIT` | `1` (set `0` to pause without removing creds) |
| `CHORDENTIAL_REDDIT_QUERIES` | a curated set of subreddit searches (r/gameDevClassifieds, r/INAT, r/forhire, r/composer); comma-separate your own subreddit search URLs to override |

## What it does

Each scheduler cycle it fetches the configured subreddit searches, keeps only
posts that pass the strict music-gig filter (real role + hiring/paid intent, no
hobby/rev-share, [For Hire] self-promo dropped), dedups on the post URL, lands
them as `reddit` signals, and fires a new-gig phone alert — same as a live gig.
Reddit's poster handle is carried so the channel-aware Respond button can DM
them.

Once this is running you can let F5Bot lapse entirely — this is its coverage,
cap-free and operator-controlled.
