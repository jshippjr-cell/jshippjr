#!/usr/bin/env python3
"""
Scaffolding for posting directly to LinkedIn, X, Meta (Facebook Page),
Reddit, Discord, Slack, Telegram, dev.to, YouTube (Shorts), Instagram
(Reels), or TikTok - no n8n/Make in between.

WARNING - read this before using it for anything real:

This talks to live, versioned platform APIs. It was written without a
connected account or working credentials for any of these platforms to
test against, so treat every request shape below as best-effort against
each platform's last publicly documented stable API, not a verified
integration. Before relying on it:

  - Confirm you actually have the right kind of API access first. Each
    platform gates posting behind its own developer-app review, X
    additionally requires a paid API tier for write access, and Reddit
    closed instant self-service app registration in late 2025 in favor of
    a manual approval queue - see the "reddit" note below. Discord needs
    no app review at all - see "discord" below. Slack sits in between:
    no OAuth review from Slack itself, but many workspaces require a
    Workspace Owner/Admin to approve new apps before a webhook can even
    be created - see "slack" below, don't assume it's as simple as
    Discord. Telegram bot creation itself needs no approval either, but
    posting into a specific chat still needs that chat's own admin to add
    the bot first - see "telegram" below. dev.to's write API needs no
    approval process found in its docs at all - just an API key generated
    from your own account settings - see "devto" below; that's about
    access, though, not content - a Tag Moderator can still strip a tag
    that doesn't fit it, or a post can still be reported through the
    sitewide Code of Conduct. YouTube, Instagram, and TikTok are a
    different shape again - all three post actual video, not text, and
    each has its own access story: see "youtube", "instagram", and
    "tiktok" below - TikTok in particular rejects every post from an
    unaudited app unless it's private (SELF_ONLY) to an account that is
    itself set to private.
  - Confirm the endpoint/version below is still current - check
    developers.linkedin.com, developer.x.com, developers.facebook.com,
    Reddit's own API docs, Discord's own API docs, Slack's own API docs,
    core.telegram.org/bots/api, developers.forem.com/api (dev.to's own
    docs), developers.google.com/youtube/v3 (YouTube), and
    developers.tiktok.com/docs/en/content-posting-api-get-started (TikTok)
    directly, since these APIs change and this script cannot check for
    you.
  - Run with --dry-run and compare the printed request against that
    platform's current docs before ever passing --confirmed.
  - Do one manual --confirmed test post yourself before wiring this into
    anything scheduled or unattended.
  - For Reddit specifically: a 2xx response here only means the API
    accepted the submission - a subreddit's AutoModerator can still remove
    it silently seconds later for violating that subreddit's own rules
    (missing flair, self-promo policy, karma/age minimums, banned
    domains). Run the `community-post-generator` skill against the target
    subreddit first and resolve everything it flags before sending.
  - For Discord and Slack specifically, and for a *private* Telegram
    group/channel: `community-post-generator` can't independently verify
    that target's rules the way it can for Reddit/Product Hunt/Hacker
    News/Indie Hackers, since most private servers, workspaces, and
    groups have no public page to check at all - it works from whatever
    rules you (as an actual member) supply it. Confirm that's still
    current yourself before sending, same as you would before posting by
    hand. A *public* Telegram channel/group is the exception - see
    "telegram" below.
  - For dev.to specifically: `community-post-generator`'s research could
    not directly confirm the Code of Conduct's specific self-promotion/
    spam wording (dev.to's own domain was unreachable during that
    research). The #showdev tag and the Organizations feature both
    suggest self-promotion is structurally welcome, but that's not the
    same as a confirmed rule - a 2xx response here just means the API
    accepted the article, not that a Tag Moderator won't strip a tag that
    doesn't fit it afterward. See "devto" below.
  - For YouTube, Instagram, and TikTok specifically: run the
    `short-form-video` skill first for the actual script/caption/hashtag
    content and its best-time-to-post guidance - this script only sends
    what you give it, it doesn't draft anything. A 2xx from TikTok's init
    call or a successful Instagram container creation is not the same
    thing as "the video is live" - both process the video after this
    script's request returns (see their notes below for what to check).

Text-only for the first eight platforms. None of their media-attachment
flows are implemented here beyond that (a plain Facebook Page post via
--platform meta is text-only; Instagram has no text-only post endpoint at
all, which is why it isn't reachable via --platform meta - see
"instagram" below for the separate video flow that does exist).

YouTube, Instagram, and TikTok are video-native - see their notes below
for how each one actually receives the video (a local file YouTube pulls
the bytes from directly via a resumable upload, vs. a public URL YouTube,
Instagram, and TikTok fetch from). There is no hashtag field for
Instagram or TikTok; include hashtags directly in the caption text the
same way you'd type them in the app. YouTube's --tags is its actual
video-tags metadata (search keywords), not hashtags - put any #Shorts-
style hashtags in the description text instead.

Same safety pattern as publish_webhook.py: refuses to send unless you
pass --dry-run or --confirmed explicitly, and never sends without one.
--dry-run never makes a network call, even for the multi-step flows below
(YouTube's upload, Instagram's container-then-publish, and to a lesser
extent Reddit/Telegram/dev.to's validation) - where a later step depends
on an earlier step's real response, the preview says so explicitly rather
than faking one.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


META_GRAPH_API_VERSION = os.environ.get("META_GRAPH_API_VERSION", "v26.0")

NOTES = {
    "linkedin": "Uses the legacy UGC Posts API (v2/ugcPosts). LinkedIn has "
                "been migrating products to a newer versioned Posts API "
                "(/rest/posts, requires a LinkedIn-Version header) - check "
                "which one your app's product access actually grants.",
    "x": "Requires a user-context OAuth2 access token with tweet.write "
         "scope (3-legged OAuth) - an app-only bearer token cannot post on "
         "someone's behalf. X also gates write access behind a paid API "
         "tier as of recent pricing - confirm your access level.",
    "meta": "Facebook Page text posts only. Instagram has no text-only "
            "post endpoint - see --platform instagram for the separate "
            "video (Reels) flow that does exist, which is a different API "
            "surface (the IG Business account, not this Page-feed "
            "endpoint) and needs its own credentials.",
    "reddit": "Requires an OAuth2 access token with 'submit' scope, from "
              "your own registered Reddit app (reddit.com/prefs/apps). As "
              "of late 2025 Reddit closed instant self-service app "
              "registration - new apps go through a manual approval queue "
              "(reportedly weeks), though already-approved credentials "
              "keep working; confirm your current registration status "
              "before assuming this just works. Also requires a "
              "descriptive User-Agent identifying your app (Reddit rate- "
              "limits or blocks generic ones). Submits a text (self) post "
              "only - no link/image/video posts. A 2xx response does not "
              "guarantee the post survives AutoModerator; run "
              "community-post-generator against the target subreddit "
              "first.",
    "discord": "One of the easiest to set up: a webhook needs no OAuth "
               "app review, just MANAGE_WEBHOOKS permission on the target "
               "channel to create one (Channel Settings > Integrations > "
               "Webhooks). The webhook URL itself is the credential - "
               "anyone with it can post, so treat it like a password "
               "(this script redacts it in --dry-run output, same as "
               "other platforms' tokens). Sends a plain chat message "
               "(2000-character limit; longer text is rejected outright, "
               "not truncated, by Discord's API) - no title field exists, "
               "this isn't a self-post the way Reddit is. Unlike the "
               "other platforms, community-post-generator did not "
               "independently verify the target server's rules for this "
               "draft - it worked from what you supplied - so recheck the "
               "server's own rules channel yourself before sending.",
    "slack": "Not as simple as Discord, despite looking similar: the "
             "direct-webhook-URL path is legacy, and creating a webhook "
             "now means creating a Slack App, which many workspaces "
             "require a Workspace Owner/Admin to approve before it can "
             "even be installed - confirm your workspace's app-approval "
             "setting before assuming self-serve setup. The webhook URL "
             "itself is the credential, same as Discord (redacted in "
             "--dry-run output). Sends plain text - format it in Slack's "
             "own 'mrkdwn' syntax, not standard Markdown: a single "
             "asterisk (*bold*) is bold in Slack, not italic, the "
             "opposite of standard Markdown - community-post-generator "
             "drafts in mrkdwn for this platform for exactly that reason. "
             "Hard-capped at 40000 characters (rejected, not truncated, "
             "past that by this script; Slack itself recommends staying "
             "under 4000 for how the message actually displays - this "
             "script only warns, doesn't block, between 4000 and 40000). "
             "Same as Discord: this skill worked from whatever rules you "
             "supplied, not independent verification, so recheck the "
             "workspace's actual rules yourself before sending.",
    "telegram": "Bot creation itself needs no approval - message @BotFather, "
                "get a token in seconds - but that only creates the bot; "
                "posting into a *specific* chat still requires that chat's "
                "own admin to add the bot to it first, so a working token "
                "doesn't mean you can post anywhere yet. Uses the Bot API's "
                "sendMessage (api.telegram.org/bot<TOKEN>/sendMessage) - the "
                "token is embedded in the URL itself, same credential-in-URL "
                "pattern as Discord/Slack (redacted in --dry-run output). "
                "Defaults to HTML parse_mode over Telegram's MarkdownV2 on "
                "purpose: MarkdownV2 requires escaping a long list of "
                "special characters anywhere they appear as literal text, "
                "and getting it wrong fails the whole send with a parse "
                "error, not just a rendering glitch - HTML only needs "
                "'<', '>', and '&' escaped. Pass --parse-mode MarkdownV2 to "
                "override, at your own risk. Hard-capped at 4096 characters "
                "(rejected outright, not truncated - Telegram's API returns "
                "'message is too long' and sends nothing). For a *private* "
                "group/channel, community-post-generator worked from "
                "whatever rules you supplied, same as Discord/Slack - "
                "recheck them yourself before sending. A *public* channel "
                "(has an @username) is the one case among these six where "
                "the skill may have actually verified the rules directly "
                "(via the public t.me/s/<username> preview), so check its "
                "Source Confidence line rather than assuming User-Supplied.",
    "devto": "Uses the Forem API (POST dev.to/api/articles). Needs an API "
             "key from your dev.to account settings, sent as a custom "
             "'api-key' header - no OAuth flow, no app review found in its "
             "docs, the simplest credential model of any platform here. "
             "Posts a full title+body article (body_markdown, standard "
             "Markdown), not a short chat message - closer in shape to "
             "Reddit's self-post than to Discord/Slack/Telegram. Up to 4 "
             "tags via --tags (comma-separated; dev.to enforces this cap, "
             "and so does this script, before sending). Optional --org-id "
             "posts under a dev.to Organization/company page instead of "
             "your personal account, if you're actually a member of one - "
             "leave it unset for a personal-account post. No documented "
             "hard character limit on articles, unlike the chat platforms "
             "above - long-form is the point here. Publishes live "
             "immediately (published: true) once --confirmed is passed; "
             "there's no separate draft-save step exposed here even "
             "though dev.to's API supports one. See the WARNING section "
             "above on the Code of Conduct gap before trusting a 2xx "
             "response as the same thing as 'this was welcome.'",
    "youtube": "Uses the standard YouTube Data API v3 (videos.insert via "
               "its resumable upload endpoint) - there's no separate "
               "'Shorts API'; a video becomes a Short by being vertical "
               "(9:16), under the length YouTube currently treats as Short-"
               "eligible, and (as a belt-and-suspenders signal) tagged "
               "#Shorts in the description. Needs an OAuth2 access token "
               "with the youtube.upload scope from your own Google Cloud "
               "project, authorized against the channel you're uploading "
               "to - getting that token (the OAuth consent flow itself) "
               "isn't handled by this script. Since a mid-2026 quota "
               "change, uploads draw from a separate ~100-per-day 'Video "
               "Uploads' bucket on your project rather than the old shared "
               "10,000-unit pool, so normal personal/small-team posting "
               "volume shouldn't need extra quota approval the way it "
               "used to - confirm your project's current bucket size in "
               "Google Cloud Console rather than assuming. Takes a local "
               "file via --video-path (this is the one platform here that "
               "uploads real bytes rather than pointing at a hosted URL) "
               "and requires --made-for-kids true|false explicitly - "
               "that's YouTube's own mandatory COPPA self-declaration on "
               "every upload, not something this script can default on "
               "your behalf. --privacy-status defaults to private so a "
               "--confirmed run never goes public by accident; pass "
               "--privacy-status public or unlisted yourself once you've "
               "actually reviewed the result.",
    "instagram": "Publishes a Reel via the Instagram Graph API - a "
                 "different flow from --platform meta's Facebook Page "
                 "post, and needs different credentials: an Instagram "
                 "Business or Creator account linked to a Facebook Page, "
                 "and a Meta app with the instagram_business_content_"
                 "publish permission actually approved (Meta's app review, "
                 "not just Development Mode - Development Mode only lets "
                 "your app's own admins/developers/testers post, which is "
                 "fine for posting to your own account but won't work for "
                 "anyone else's). Needs IG_USER_ID (the Instagram Business "
                 "account's own ID, not the Facebook Page ID) alongside "
                 "META_PAGE_ACCESS_TOKEN. Unlike YouTube or TikTok's file-"
                 "based paths, Instagram has no raw-upload endpoint at "
                 "all - pass --video-url pointing at the video already "
                 "hosted somewhere public; Instagram's own servers fetch "
                 "it from there. The real flow is three steps, not one: "
                 "create a media container (media_type=REELS), poll it "
                 "until Instagram finishes fetching/processing the video "
                 "(status_code=FINISHED - this script polls for up to "
                 "--upload-timeout seconds, default 600), then publish the "
                 "container. A --dry-run only previews step 1, since steps "
                 "2 and 3 need step 1's real container ID to exist first. "
                 "No separate hashtag field - put hashtags directly in "
                 "--text (the caption), the same as typing them in the "
                 "app.",
    "tiktok": "Uses TikTok's Content Posting API with PULL_FROM_URL as the "
              "source, so pass --video-url rather than a local file - "
              "TikTok's own servers fetch it from there, and that URL's "
              "domain has to already be verified for your app in TikTok's "
              "developer portal or the call is rejected outright. Two "
              "calls per send: first POST /v2/post/publish/creator_info/"
              "query/, which TikTok requires before every post - "
              "--privacy-level must be one of the privacy_level_options it "
              "returns (a public account offers PUBLIC_TO_EVERYONE, "
              "MUTUAL_FOLLOW_FRIENDS, SELF_ONLY; a private one offers "
              "FOLLOWER_OF_CREATOR in place of PUBLIC_TO_EVERYONE), and "
              "duet/comment/stitch are sent as disabled wherever the "
              "creator has turned them off - then POST /v2/post/publish/"
              "video/init/. Needs an app approved for the video.publish "
              "scope, and the specific creator has to have authorized "
              "that scope for your app - getting either of those isn't "
              "handled by this script. **Until your app passes TikTok's "
              "own audit, TikTok only accepts SELF_ONLY (private, visible "
              "only to the poster), posted to a creator account that is "
              "itself set to private - anything else is rejected "
              "(unaudited_client_can_only_post_to_private_accounts), not "
              "quietly posted as private instead** - TikTok's guidelines "
              "also cap an unaudited app at 5 posting creators per 24 "
              "hours. Audit review reportedly takes anywhere from a few days to "
              "about two weeks, and this script has no way to check your "
              "app's audit status for you, so confirm it directly in "
              "TikTok's developer portal before requesting anything but "
              "SELF_ONLY. A 2xx response from the second call means "
              "TikTok accepted the request and queued it - fetching and "
              "posting the video happens asynchronously afterward, so "
              "that response is not confirmation the video is actually "
              "live; check TikTok's own status-fetch endpoint or your "
              "app's activity to confirm. No separate hashtag field, same "
              "as Instagram - put hashtags directly in --text (used as "
              "TikTok's post title/caption field).",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Post directly to LinkedIn, X, Meta (Facebook Page), Reddit, Discord, Slack, Telegram, "
                    "dev.to, YouTube (Shorts), Instagram (Reels), or TikTok. "
                    "Scaffolding only - read the module docstring before using for real.",
        epilog=(
            "Required environment variables per platform:\n"
            "  linkedin  LINKEDIN_ACCESS_TOKEN, LINKEDIN_AUTHOR_URN\n"
            "  x         X_ACCESS_TOKEN  (user-context OAuth2, tweet.write scope)\n"
            "  meta      META_PAGE_ACCESS_TOKEN, META_PAGE_ID\n"
            "            (optional: META_GRAPH_API_VERSION, defaults to "
            f"{META_GRAPH_API_VERSION})\n"
            "  reddit    REDDIT_ACCESS_TOKEN, REDDIT_USER_AGENT\n"
            "            (also requires --subreddit and --title; --flair-id optional)\n"
            "  discord   DISCORD_WEBHOOK_URL  (the full webhook URL - itself the credential)\n"
            "  slack     SLACK_WEBHOOK_URL  (the full webhook URL - itself the credential)\n"
            "  telegram  TELEGRAM_BOT_TOKEN  (also requires --chat-id; --parse-mode optional,\n"
            "            defaults to HTML)\n"
            "  devto     DEVTO_API_KEY  (also requires --title; --tags optional, comma-\n"
            "            separated, max 4; --org-id optional)\n"
            "  youtube   YOUTUBE_ACCESS_TOKEN  (also requires --video-path, --title,\n"
            "            --made-for-kids true|false; --privacy-status defaults to private,\n"
            "            --tags/--category-id optional)\n"
            "  instagram META_PAGE_ACCESS_TOKEN, IG_USER_ID  (also requires --video-url;\n"
            "            --upload-timeout controls how long this script polls for Instagram\n"
            "            to finish processing the video, default 600s)\n"
            "  tiktok    TIKTOK_ACCESS_TOKEN  (also requires --video-url; --privacy-level\n"
            "            defaults to SELF_ONLY - see the tiktok note on why)\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--platform", required=True,
                         choices=["linkedin", "x", "meta", "reddit", "discord", "slack", "telegram", "devto",
                                  "youtube", "instagram", "tiktok"],
                         help="Which platform to post to.")
    parser.add_argument("--text", help="Post text (caption/description/message, depending on platform). Reads stdin if omitted.")
    parser.add_argument("--subreddit", help="Target subreddit, no 'r/' prefix. Required for --platform reddit.")
    parser.add_argument("--title", help="Post title. Required for --platform reddit, devto, and youtube (video title) - the chat platforms and instagram/tiktok are body/caption-only.")
    parser.add_argument("--flair-id", help="Optional flair template ID, --platform reddit only, if the subreddit requires one.")
    parser.add_argument("--chat-id", help="Target chat: a numeric ID, or '@channelusername' for a public channel. Required for --platform telegram.")
    parser.add_argument("--parse-mode", default="HTML", choices=["HTML", "MarkdownV2"],
                         help="Telegram formatting mode (default: HTML, simpler escaping than MarkdownV2). --platform telegram only.")
    parser.add_argument("--tags", help="Comma-separated tags. --platform devto: max 4, a real taxonomy field. "
                                        "--platform youtube: video search-keywords metadata, NOT hashtags (put "
                                        "#Shorts-style hashtags in --text instead). Not used by instagram/tiktok - "
                                        "neither has a separate hashtag field, so put hashtags directly in --text.")
    parser.add_argument("--org-id", help="Post under this dev.to Organization ID instead of your personal account. --platform devto only, optional.")
    parser.add_argument("--video-path", help="Local path to the video file to upload. --platform youtube only - "
                                              "the one platform here that uploads raw bytes rather than pointing at a hosted URL.")
    parser.add_argument("--video-url", help="Public URL the platform's own servers fetch the video from. "
                                             "Required for --platform instagram and --platform tiktok - neither "
                                             "accepts a raw file upload the way youtube does.")
    parser.add_argument("--category-id", help="YouTube video category ID (e.g. '22' for People & Blogs, '24' for "
                                                "Entertainment). --platform youtube only, optional - omitted entirely "
                                                "from the request if not given, rather than guessing one.")
    parser.add_argument("--privacy-status", default="private", choices=["private", "unlisted", "public"],
                         help="--platform youtube only. Defaults to private so a --confirmed run never goes public "
                              "by accident - pass unlisted or public explicitly once you've reviewed the result.")
    parser.add_argument("--made-for-kids", choices=["true", "false"], default=None,
                         help="--platform youtube only, required. YouTube's own mandatory COPPA self-declaration - "
                              "there is no default this script will guess on your behalf.")
    parser.add_argument("--privacy-level", default="SELF_ONLY",
                         choices=["SELF_ONLY", "PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR"],
                         help="--platform tiktok only. Defaults to SELF_ONLY (private), the only level TikTok accepts "
                              "until your app passes its audit. Checked against the creator's own allowed options "
                              "(creator_info) before posting.")
    parser.add_argument("--cover-ms", type=int,
                         help="--platform tiktok and instagram only: the frame to use as the cover, in milliseconds "
                              "from the start (TikTok's video_cover_timestamp_ms, Instagram's thumb_offset). "
                              "render.js --cover prints the value for the frame it checked. Without it, both "
                              "use their own default (TikTok: the first frame).")
    parser.add_argument("--cover-url", help="--platform instagram only: a public URL of a 9:16 cover image (Instagram's "
                                             "cover_url, e.g. the render.js --cover PNG, hosted). Takes priority over "
                                             "--cover-ms if both are given.")
    parser.add_argument("--disable-duet", action="store_true", help="--platform tiktok only. Off (duets allowed) unless passed.")
    parser.add_argument("--disable-comment", action="store_true", help="--platform tiktok only. Off (comments allowed) unless passed.")
    parser.add_argument("--disable-stitch", action="store_true", help="--platform tiktok only. Off (stitching allowed) unless passed.")
    parser.add_argument("--upload-timeout", type=float, default=600,
                         help="--platform youtube and instagram (default: 600s). YouTube: timeout for sending "
                              "the video bytes. Instagram: how long to keep polling the media container while "
                              "it processes the video before giving up.")
    parser.add_argument("--timeout", type=float, default=15, help="Request timeout in seconds for ordinary (non-upload) calls (default: 15).")
    parser.add_argument("--metrics", action="store_true",
                         help="Read a posted video's numbers instead of posting (--platform youtube, instagram, or "
                              "tiktok, with --video-id). Read-only, so it needs neither --dry-run nor --confirmed; "
                              "--dry-run still previews the request. Prints a row for state/video-log.md.")
    parser.add_argument("--video-id", help="--metrics only: the platform's ID for the posted video (YouTube video ID, "
                                            "Instagram media ID, TikTok video ID).")
    parser.add_argument("--dry-run", action="store_true", help="Print the request(s) instead of sending them. Never makes a network call.")
    parser.add_argument("--confirmed", action="store_true",
                         help="Required to actually send. Only pass this after a human has seen the exact "
                              "request and explicitly said to proceed, in this conversation.")
    return parser.parse_args()


def load_text(text_arg):
    text = text_arg if text_arg is not None else sys.stdin.read()
    text = text.strip()
    if not text:
        print("No post text given. Pass --text or pipe it via stdin.", file=sys.stderr)
        sys.exit(2)
    return text


def require_env(*names):
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        print(f"Missing required environment variable(s): {', '.join(missing)}", file=sys.stderr)
        sys.exit(2)
    return {n: os.environ[n] for n in names}


def build_linkedin_request(text):
    env = require_env("LINKEDIN_ACCESS_TOKEN", "LINKEDIN_AUTHOR_URN")
    url = "https://api.linkedin.com/v2/ugcPosts"
    headers = {
        "Authorization": f"Bearer {env['LINKEDIN_ACCESS_TOKEN']}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }
    body = {
        "author": env["LINKEDIN_AUTHOR_URN"],
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }
    return url, headers, json.dumps(body).encode("utf-8"), [env["LINKEDIN_ACCESS_TOKEN"]]


def build_x_request(text):
    env = require_env("X_ACCESS_TOKEN")
    url = "https://api.twitter.com/2/tweets"
    headers = {
        "Authorization": f"Bearer {env['X_ACCESS_TOKEN']}",
        "Content-Type": "application/json",
    }
    body = {"text": text}
    return url, headers, json.dumps(body).encode("utf-8"), [env["X_ACCESS_TOKEN"]]


def build_meta_request(text):
    env = require_env("META_PAGE_ACCESS_TOKEN", "META_PAGE_ID")
    url = f"https://graph.facebook.com/{META_GRAPH_API_VERSION}/{env['META_PAGE_ID']}/feed"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    body = urllib.parse.urlencode({
        "message": text,
        "access_token": env["META_PAGE_ACCESS_TOKEN"],
    }).encode("utf-8")
    return url, headers, body, [env["META_PAGE_ACCESS_TOKEN"]]


def build_reddit_request(text, subreddit, title, flair_id):
    env = require_env("REDDIT_ACCESS_TOKEN", "REDDIT_USER_AGENT")
    url = "https://oauth.reddit.com/api/submit"
    headers = {
        "Authorization": f"Bearer {env['REDDIT_ACCESS_TOKEN']}",
        "User-Agent": env["REDDIT_USER_AGENT"],
        "Content-Type": "application/x-www-form-urlencoded",
    }
    fields = {
        "sr": subreddit,
        "kind": "self",
        "title": title,
        "text": text,
        "api_type": "json",
    }
    if flair_id:
        fields["flair_id"] = flair_id
    body = urllib.parse.urlencode(fields).encode("utf-8")
    return url, headers, body, [env["REDDIT_ACCESS_TOKEN"]]


def build_discord_request(text):
    env = require_env("DISCORD_WEBHOOK_URL")
    url = env["DISCORD_WEBHOOK_URL"]
    if len(text) > 2000:
        print(
            f"Message is {len(text)} characters; Discord rejects messages over 2000 "
            "characters outright rather than truncating them. Shorten it before sending.",
            file=sys.stderr,
        )
        sys.exit(2)
    headers = {"Content-Type": "application/json"}
    body = json.dumps({"content": text}).encode("utf-8")
    # The webhook URL itself is the credential (no separate token/header) - redact the
    # whole thing, not just a header value, or --dry-run would print it in the clear.
    return url, headers, body, [url]


def build_slack_request(text):
    env = require_env("SLACK_WEBHOOK_URL")
    url = env["SLACK_WEBHOOK_URL"]
    if len(text) > 40000:
        print(
            f"Message is {len(text)} characters; Slack rejects messages over 40000 "
            "characters outright. Shorten it before sending.",
            file=sys.stderr,
        )
        sys.exit(2)
    if len(text) > 4000:
        print(
            f"Warning: message is {len(text)} characters. Slack technically allows up to "
            "40000, but recommends staying under 4000 for how the message actually "
            "displays (longer messages get collapsed behind a 'see more' link). Not "
            "blocking the send, just flagging it - not the same as Discord, which draws "
            "the line at a hard 2000-character cutoff.",
            file=sys.stderr,
        )
    headers = {"Content-Type": "application/json"}
    body = json.dumps({"text": text}).encode("utf-8")
    # The webhook URL itself is the credential, same as Discord - redact the whole thing.
    return url, headers, body, [url]


def build_telegram_request(text, chat_id, parse_mode):
    env = require_env("TELEGRAM_BOT_TOKEN")
    if len(text) > 4096:
        print(
            f"Message is {len(text)} characters; Telegram rejects messages over 4096 "
            "characters outright ('message is too long') rather than truncating them. "
            "Shorten it before sending.",
            file=sys.stderr,
        )
        sys.exit(2)
    url = f"https://api.telegram.org/bot{env['TELEGRAM_BOT_TOKEN']}/sendMessage"
    headers = {"Content-Type": "application/json"}
    body = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }).encode("utf-8")
    # The bot token is embedded in the URL path itself, not a header - redact the
    # token value so it doesn't leak in --dry-run output (URL structure stays visible).
    return url, headers, body, [env["TELEGRAM_BOT_TOKEN"]]


def build_devto_request(text, title, tags, org_id):
    env = require_env("DEVTO_API_KEY")
    if tags and len(tags) > 4:
        print(
            f"{len(tags)} tags given; dev.to allows a maximum of 4 tags per "
            "article. Trim the list before sending.",
            file=sys.stderr,
        )
        sys.exit(2)
    url = "https://dev.to/api/articles"
    headers = {
        "api-key": env["DEVTO_API_KEY"],
        "Content-Type": "application/json",
    }
    article = {
        "title": title,
        "body_markdown": text,
        "published": True,
        "tags": tags or [],
    }
    if org_id:
        article["organization_id"] = org_id
    body = json.dumps({"article": article}).encode("utf-8")
    # A static API key in a custom header, not a URL - redact the key value
    # itself, same pattern as LinkedIn/X's bearer tokens.
    return url, headers, body, [env["DEVTO_API_KEY"]]


BUILDERS = {
    "linkedin": build_linkedin_request,
    "x": build_x_request,
    "meta": build_meta_request,
    "discord": build_discord_request,
    "slack": build_slack_request,
}


def redact(text, secrets):
    for secret in secrets:
        if secret:
            # Form-encoded bodies (meta, instagram) carry the token percent-encoded, so a
            # token containing '+', '/' or '=' would slip past a raw-string match alone.
            for form in (secret, urllib.parse.quote_plus(secret), urllib.parse.quote(secret, safe="")):
                text = text.replace(form, "<redacted>")
    return text


def run_youtube(args):
    """Two real HTTP steps: initiate a resumable upload session (JSON), then
    PUT the actual video bytes to the URL that session returns. --dry-run
    only ever shows step 1 in full - step 2's URL doesn't exist until step 1
    is actually sent, so it's described rather than faked."""
    if not args.video_path:
        print("--platform youtube requires --video-path (a local video file).", file=sys.stderr)
        return 2
    if not os.path.isfile(args.video_path):
        print(f"No file found at --video-path {args.video_path}", file=sys.stderr)
        return 2
    if not args.title:
        print("--platform youtube requires --title.", file=sys.stderr)
        return 2
    if len(args.title) > 100:
        print(
            f"--title is {len(args.title)} characters; YouTube rejects titles over 100 "
            "characters outright rather than truncating them. Shorten it before sending.",
            file=sys.stderr,
        )
        return 2
    if args.made_for_kids is None:
        print(
            "--platform youtube requires --made-for-kids true|false. YouTube requires "
            "every upload to self-declare this (its COPPA compliance question) - there "
            "is no default this script will guess on your behalf.",
            file=sys.stderr,
        )
        return 2

    env = require_env("YOUTUBE_ACCESS_TOKEN")
    description = load_text(args.text)
    if len(description.encode("utf-8")) > 5000:
        print(
            f"Description is {len(description.encode('utf-8'))} bytes; YouTube rejects "
            "descriptions over 5000 bytes (bytes, not characters - emoji count extra). "
            "Shorten it before sending.",
            file=sys.stderr,
        )
        return 2
    # YouTube's videos resource allows any UTF-8 in title/description *except* < and >,
    # and rejects the whole upload otherwise - easy to hit with hook copy like "old -> new".
    for field, value in (("--title", args.title), ("the description (--text)", description)):
        if "<" in value or ">" in value:
            print(
                f"YouTube rejects '<' and '>' anywhere in a video's title or description - "
                f"remove them from {field} (e.g. write '->' as 'to' or '→').",
                file=sys.stderr,
            )
            return 2
    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
    video_size = os.path.getsize(args.video_path)

    init_url = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
    init_headers = {
        "Authorization": f"Bearer {env['YOUTUBE_ACCESS_TOKEN']}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "video/*",
        "X-Upload-Content-Length": str(video_size),
    }
    snippet = {"title": args.title, "description": description}
    if tags:
        snippet["tags"] = tags
    if args.category_id:
        snippet["categoryId"] = args.category_id
    init_body = json.dumps({
        "snippet": snippet,
        "status": {
            "privacyStatus": args.privacy_status,
            "selfDeclaredMadeForKids": args.made_for_kids == "true",
        },
    }).encode("utf-8")
    secrets = [env["YOUTUBE_ACCESS_TOKEN"]]

    if args.dry_run:
        print("=== DRY RUN: no request sent ===")
        print("Platform: youtube")
        print(f"Note: {NOTES['youtube']}")
        print("Step 1/2 - initiate resumable upload session:")
        print("  Method: POST")
        print(f"  URL: {redact(init_url, secrets)}")
        print("  Headers:")
        for name, value in init_headers.items():
            print(f"    {name}: {redact(value, secrets)}")
        print(f"  Body ({len(init_body)} bytes):")
        print("  " + redact(init_body.decode("utf-8"), secrets))
        print(
            f"Step 2/2 - would PUT {video_size} bytes read from {args.video_path} to "
            "the upload URL returned in Step 1's real response 'Location' header. "
            "Step 1 was not actually sent during --dry-run, so that URL doesn't exist "
            "yet - this step can't be previewed any further than that."
        )
        print("=== END DRY RUN ===")
        return 0

    init_request = urllib.request.Request(init_url, data=init_body, headers=init_headers, method="POST")
    try:
        with urllib.request.urlopen(init_request, timeout=args.timeout) as response:
            upload_url = response.getheader("Location")
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        print("YouTube API rejected the upload session (Step 1/2)", file=sys.stderr)
        print(f"Status: {e.code} {e.reason}", file=sys.stderr)
        print(f"Response: {error_body[:500] or '(empty body)'}", file=sys.stderr)
        return 4
    except (urllib.error.URLError, OSError) as e:
        print(f"Failed to reach YouTube's API: {e}", file=sys.stderr)
        return 3

    if not upload_url:
        print("YouTube accepted Step 1 but returned no upload URL (Location header) - cannot continue.", file=sys.stderr)
        return 4

    with open(args.video_path, "rb") as f:
        video_bytes = f.read()

    upload_request = urllib.request.Request(
        upload_url,
        data=video_bytes,
        headers={"Content-Type": "video/*", "Content-Length": str(video_size)},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(upload_request, timeout=args.upload_timeout) as response:
            status = response.getcode()
            reason = response.reason
            response_body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        print("YouTube API rejected the video upload (Step 2/2)", file=sys.stderr)
        print(f"Status: {e.code} {e.reason}", file=sys.stderr)
        print(f"Response: {error_body[:500] or '(empty body)'}", file=sys.stderr)
        return 4
    except (urllib.error.URLError, OSError) as e:
        print(f"Failed to reach YouTube's upload URL: {e}", file=sys.stderr)
        return 3

    print("Uploaded to YouTube")
    print(f"Status: {status} {reason}")
    print(f"Response: {response_body[:500] or '(empty body)'}")
    return 0


def run_instagram(args):
    """Three real steps: create a Reels media container from a hosted video
    URL, poll it until Instagram finishes fetching/processing the video,
    then publish it. --dry-run only shows step 1 - steps 2 and 3 need step
    1's real container ID, which doesn't exist yet during a dry run."""
    env = require_env("META_PAGE_ACCESS_TOKEN", "IG_USER_ID")
    if not args.video_url:
        print(
            "--platform instagram requires --video-url - a URL Instagram's own "
            "servers can fetch the video from. This API has no raw-file-upload path; "
            "host the video somewhere public first and pass that URL here.",
            file=sys.stderr,
        )
        return 2
    caption = load_text(args.text)
    if len(caption) > 2200:
        print(
            f"Caption is {len(caption)} characters; Instagram rejects captions over 2200 "
            "characters outright. Shorten it before sending.",
            file=sys.stderr,
        )
        return 2
    secrets = [env["META_PAGE_ACCESS_TOKEN"]]
    base = f"https://graph.facebook.com/{META_GRAPH_API_VERSION}/{env['IG_USER_ID']}"
    create_url = f"{base}/media"
    fields = {
        "media_type": "REELS",
        "video_url": args.video_url,
        "caption": caption,
    }
    # the cover: an image URL, or a frame of the video (cover_url wins if both are sent)
    if args.cover_url:
        fields["cover_url"] = args.cover_url
        if args.cover_ms is not None:
            print("Note: both --cover-url and --cover-ms given; Instagram uses cover_url and ignores thumb_offset.", file=sys.stderr)
    if args.cover_ms is not None:
        fields["thumb_offset"] = str(args.cover_ms)
    fields["access_token"] = env["META_PAGE_ACCESS_TOKEN"]
    create_body = urllib.parse.urlencode(fields).encode("utf-8")

    if args.dry_run:
        print("=== DRY RUN: no request sent ===")
        print("Platform: instagram")
        print(f"Note: {NOTES['instagram']}")
        print("Step 1/3 - create the Reels media container:")
        print("  Method: POST")
        print(f"  URL: {redact(create_url, secrets)}")
        print(f"  Body: {redact(create_body.decode('utf-8'), secrets)}")
        print(
            "Step 2/3 - would poll GET <container-id>?fields=status_code (up to "
            f"--upload-timeout={args.upload_timeout:.0f}s) until status_code=FINISHED - "
            "Instagram has to fetch and process the video from video_url first."
        )
        print(
            f"Step 3/3 - would POST {redact(base, secrets)}/media_publish with the "
            "container's creation ID once FINISHED."
        )
        print(
            "Steps 2 and 3 depend on Step 1's real container ID, which doesn't exist "
            "yet during --dry-run, so they can't be previewed any further than this."
        )
        print("=== END DRY RUN ===")
        return 0

    try:
        with urllib.request.urlopen(
            urllib.request.Request(create_url, data=create_body, method="POST"),
            timeout=args.timeout,
        ) as response:
            container = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        print("Instagram API rejected creating the media container (Step 1/3)", file=sys.stderr)
        print(f"Status: {e.code} {e.reason}", file=sys.stderr)
        print(f"Response: {error_body[:500] or '(empty body)'}", file=sys.stderr)
        return 4
    except (urllib.error.URLError, OSError) as e:
        print(f"Failed to reach Instagram's API: {e}", file=sys.stderr)
        return 3

    container_id = container.get("id")
    if not container_id:
        print(f"Instagram accepted Step 1 but returned no container id: {container}", file=sys.stderr)
        return 4

    status_url = f"{base.rsplit('/', 1)[0]}/{container_id}?fields=status_code&access_token={urllib.parse.quote(env['META_PAGE_ACCESS_TOKEN'])}"
    deadline = time.time() + args.upload_timeout
    status_code = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(status_url, timeout=args.timeout) as response:
                status_code = json.loads(response.read().decode("utf-8")).get("status_code")
        except (urllib.error.HTTPError, urllib.error.URLError, OSError) as e:
            print(f"Warning: status check failed, retrying: {e}", file=sys.stderr)
        if status_code == "FINISHED":
            break
        if status_code == "ERROR":
            print("Instagram failed to process the video (container status_code=ERROR).", file=sys.stderr)
            return 4
        time.sleep(5)
    else:
        print(
            f"Instagram hadn't finished processing the video after "
            f"{args.upload_timeout:.0f}s (last status: {status_code}). It may still "
            f"finish - check container {container_id} manually, or rerun with a "
            "longer --upload-timeout (the container stays valid for a while).",
            file=sys.stderr,
        )
        return 4

    publish_body = urllib.parse.urlencode({
        "creation_id": container_id,
        "access_token": env["META_PAGE_ACCESS_TOKEN"],
    }).encode("utf-8")
    try:
        with urllib.request.urlopen(
            urllib.request.Request(f"{base}/media_publish", data=publish_body, method="POST"),
            timeout=args.timeout,
        ) as response:
            status = response.getcode()
            reason = response.reason
            response_body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        print("Instagram API rejected publishing the Reel (Step 3/3)", file=sys.stderr)
        print(f"Status: {e.code} {e.reason}", file=sys.stderr)
        print(f"Response: {error_body[:500] or '(empty body)'}", file=sys.stderr)
        return 4
    except (urllib.error.URLError, OSError) as e:
        print(f"Failed to reach Instagram's API: {e}", file=sys.stderr)
        return 3

    print("Published to Instagram Reels")
    print(f"Status: {status} {reason}")
    print(f"Response: {response_body[:500] or '(empty body)'}")
    return 0


TIKTOK_UNAUDITED_ERROR = "unaudited_client_can_only_post_to_private_accounts"
TIKTOK_UNAUDITED_HINT = (
    "Until your app passes TikTok's audit, TikTok only accepts --privacy-level SELF_ONLY, "
    "posted to a creator account that is itself set to private - anything else is "
    f"rejected ({TIKTOK_UNAUDITED_ERROR}), not quietly posted as private instead."
)


def tiktok_post(url, headers, body, timeout, what):
    """POST to one Content Posting API endpoint. TikTok reports failures in the JSON
    body's error.code as well as the HTTP status, so both are checked. Returns
    (payload, None) on success, or (None, exit_code) after printing why it failed."""
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        print(f"TikTok API rejected {what}", file=sys.stderr)
        print(f"Status: {e.code} {e.reason}", file=sys.stderr)
        print(f"Response: {raw[:500] or '(empty body)'}", file=sys.stderr)
        if TIKTOK_UNAUDITED_ERROR in raw:
            print(TIKTOK_UNAUDITED_HINT, file=sys.stderr)
        return None, 4
    except (urllib.error.URLError, OSError) as e:
        print(f"Failed to reach TikTok's API: {e}", file=sys.stderr)
        return None, 3
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError
    except ValueError:
        print(f"TikTok returned a non-JSON response to {what}: {raw[:500] or '(empty body)'}", file=sys.stderr)
        return None, 4
    error = payload.get("error") or {}
    if error.get("code", "ok") != "ok":
        print(
            f"TikTok API returned error '{error.get('code')}' for {what}: "
            f"{error.get('message') or '(no message)'}",
            file=sys.stderr,
        )
        if error.get("code") == TIKTOK_UNAUDITED_ERROR:
            print(TIKTOK_UNAUDITED_HINT, file=sys.stderr)
        return None, 4
    return payload, None


def run_tiktok(args):
    """Two real HTTP calls: query the creator's current posting settings
    (creator_info - TikTok requires this before every post, and the post must
    use a privacy level it returns), then init the post. TikTok fetches the
    video itself (PULL_FROM_URL) and processes/posts it asynchronously after
    that. --dry-run shows both requests, but Step 2 only as asked for - what
    Step 1's real answer would change can't be known without sending it."""
    env = require_env("TIKTOK_ACCESS_TOKEN")
    if not args.video_url:
        print(
            "--platform tiktok requires --video-url. This script uses TikTok's "
            "PULL_FROM_URL source, where TikTok's own servers fetch the video - the "
            "URL's domain must already be verified for your app in TikTok's developer "
            "portal, or the init call will be rejected.",
            file=sys.stderr,
        )
        return 2
    caption = load_text(args.text)
    # TikTok measures this limit in UTF-16 code units, so emoji count double.
    caption_units = len(caption.encode("utf-16-le")) // 2
    if caption_units > 2200:
        print(
            f"Caption is {caption_units} UTF-16 units; TikTok rejects captions over 2200 "
            "(emoji count as 2 each). Shorten it before sending.",
            file=sys.stderr,
        )
        return 2
    if args.privacy_level != "SELF_ONLY":
        print(f"Warning: --privacy-level {args.privacy_level} was requested. {TIKTOK_UNAUDITED_HINT}", file=sys.stderr)
    info_url = "https://open.tiktokapis.com/v2/post/publish/creator_info/query/"
    init_url = "https://open.tiktokapis.com/v2/post/publish/video/init/"
    headers = {
        "Authorization": f"Bearer {env['TIKTOK_ACCESS_TOKEN']}",
        "Content-Type": "application/json; charset=UTF-8",
    }
    post_info = {
        "title": caption,
        "privacy_level": args.privacy_level,
        "disable_duet": args.disable_duet,
        "disable_comment": args.disable_comment,
        "disable_stitch": args.disable_stitch,
    }
    if args.cover_ms is not None:
        post_info["video_cover_timestamp_ms"] = args.cover_ms
    source_info = {
        "source": "PULL_FROM_URL",
        "video_url": args.video_url,
    }
    secrets = [env["TIKTOK_ACCESS_TOKEN"]]

    if args.dry_run:
        body = json.dumps({"post_info": post_info, "source_info": source_info}).encode("utf-8")
        print("=== DRY RUN: no request sent ===")
        print("Platform: tiktok")
        print(f"Note: {NOTES['tiktok']}")
        print("Step 1/2 - query the creator's current posting settings:")
        print("  Method: POST")
        print(f"  URL: {info_url}")
        print("  Headers:")
        for name, value in headers.items():
            print(f"    {name}: {redact(value, secrets)}")
        print("  Body: (empty)")
        print(
            "  A real send stops here unless --privacy-level is one of the "
            "privacy_level_options this returns, and sends duet/comment/stitch as "
            "disabled wherever the creator has turned them off. Step 1 wasn't sent "
            "during --dry-run, so Step 2 below shows the request as you asked for it."
        )
        print("Step 2/2 - init the post:")
        print("  Method: POST")
        print(f"  URL: {init_url}")
        print("  Headers:")
        for name, value in headers.items():
            print(f"    {name}: {redact(value, secrets)}")
        print(f"  Body ({len(body)} bytes):")
        print("  " + body.decode("utf-8"))
        print("=== END DRY RUN ===")
        return 0

    info, failed = tiktok_post(info_url, headers, b"", args.timeout, "the creator_info query (Step 1/2)")
    if failed:
        return failed
    creator = info.get("data") or {}
    options = creator.get("privacy_level_options") or []
    if args.privacy_level not in options:
        print(
            f"--privacy-level {args.privacy_level} isn't available for this creator right "
            f"now - TikTok only accepts one of: {', '.join(options) or '(none returned)'}. "
            "Nothing was posted; rerun with one of those.",
            file=sys.stderr,
        )
        return 2
    # TikTok only offers PUBLIC_TO_EVERYONE to public accounts (private ones get
    # FOLLOWER_OF_CREATOR instead), and an unaudited app can't post to a public one.
    if "PUBLIC_TO_EVERYONE" in options:
        print(
            "Note: this creator's TikTok account is public. If your app hasn't passed "
            "TikTok's audit yet, this post will be rejected - unaudited apps can only "
            "post to an account set to private.",
            file=sys.stderr,
        )
    for flag, setting, label in (
        ("disable_duet", "duet_disabled", "duets"),
        ("disable_comment", "comment_disabled", "comments"),
        ("disable_stitch", "stitch_disabled", "stitching"),
    ):
        if creator.get(setting) and not post_info[flag]:
            post_info[flag] = True
            print(f"Note: the creator has {label} turned off in their TikTok settings, so {flag} is sent as true.", file=sys.stderr)
    max_seconds = creator.get("max_video_post_duration_sec")
    if max_seconds:
        print(f"Note: this creator can post videos up to {max_seconds}s - TikTok won't publish a longer one.", file=sys.stderr)

    body = json.dumps({"post_info": post_info, "source_info": source_info}).encode("utf-8")
    result, failed = tiktok_post(init_url, headers, body, args.timeout, "the post (Step 2/2)")
    if failed:
        return failed

    publish_id = (result.get("data") or {}).get("publish_id")
    print("Queued on TikTok (processing happens asynchronously)")
    print(f"Publish ID: {publish_id or '(none returned)'}")
    print(f"Response: {json.dumps(result)[:500]}")
    print(
        "This means TikTok accepted the request, not that the video is live yet - "
        "confirm via TikTok's status-fetch endpoint with the publish ID above, or "
        "your app's activity log."
    )
    return 0


def http_json(url, headers, timeout, body=None, method="GET"):
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def metrics_requests(args):
    """The read-only requests --metrics makes for each platform, as (label, method, url, headers,
    body, secrets, optional) tuples. Best-effort against each platform's documented API, like the
    rest of this script: confirm the metric names against the platform's docs if a call fails."""
    vid = urllib.parse.quote(args.video_id, safe="")
    if args.platform == "youtube":
        env = require_env("YOUTUBE_ACCESS_TOKEN")
        headers = {"Authorization": f"Bearer {env['YOUTUBE_ACCESS_TOKEN']}"}
        today = time.strftime("%Y-%m-%d")
        return [
            ("statistics (YouTube Data API)", "GET",
             f"https://www.googleapis.com/youtube/v3/videos?part=statistics&id={vid}", headers, None,
             [env["YOUTUBE_ACCESS_TOKEN"]], False),
            # average view percentage needs the yt-analytics.readonly scope on the same token
            ("watch time (YouTube Analytics API)", "GET",
             "https://youtubeanalytics.googleapis.com/v2/reports?ids=channel%3D%3DMINE&startDate=2005-01-01"
             f"&endDate={today}&metrics=views%2CaverageViewDuration%2CaverageViewPercentage%2Cshares"
             f"&filters=video%3D%3D{vid}", headers, None, [env["YOUTUBE_ACCESS_TOKEN"]], True),
        ]
    if args.platform == "instagram":
        env = require_env("META_PAGE_ACCESS_TOKEN")
        metric = "views,reach,likes,comments,shares,saved,ig_reels_avg_watch_time"
        return [("insights (Instagram Graph API)", "GET",
                 f"https://graph.facebook.com/{META_GRAPH_API_VERSION}/{vid}/insights?metric={metric}"
                 f"&access_token={urllib.parse.quote(env['META_PAGE_ACCESS_TOKEN'], safe='')}", {}, None,
                 [env["META_PAGE_ACCESS_TOKEN"]], False)]
    env = require_env("TIKTOK_ACCESS_TOKEN")
    body = json.dumps({"filters": {"video_ids": [args.video_id]}}).encode("utf-8")
    return [("video stats (TikTok Display API, video.list scope)", "POST",
             "https://open.tiktokapis.com/v2/video/query/?fields=id,view_count,like_count,comment_count,share_count,duration",
             {"Authorization": f"Bearer {env['TIKTOK_ACCESS_TOKEN']}", "Content-Type": "application/json; charset=UTF-8"},
             body, [env["TIKTOK_ACCESS_TOKEN"]], False)]


def read_metrics(platform, answers):
    """Pulls views, average watch, likes, comments, shares, and saves out of the answers."""
    m = {}
    if platform == "youtube":
        stats = ((answers.get(0) or {}).get("items") or [{}])[0].get("statistics", {})
        m.update(views=stats.get("viewCount"), likes=stats.get("likeCount"), comments=stats.get("commentCount"))
        report = answers.get(1) or {}
        heads = [h.get("name") for h in report.get("columnHeaders", [])]
        if report.get("rows"):
            row = dict(zip(heads, report["rows"][0]))
            if row.get("averageViewPercentage") is not None:
                m["avg_watch"] = f"{round(float(row['averageViewPercentage']))}%"
            m["shares"] = row.get("shares")
    elif platform == "instagram":
        for item in (answers.get(0) or {}).get("data", []):
            values = item.get("values") or [{}]
            value = values[0].get("value", (item.get("total_value") or {}).get("value"))
            m[{"views": "views", "likes": "likes", "comments": "comments", "shares": "shares", "saved": "saves",
               "ig_reels_avg_watch_time": "avg_watch"}.get(item.get("name"), item.get("name"))] = value
        if isinstance(m.get("avg_watch"), (int, float)):
            m["avg_watch"] = f"{m['avg_watch'] / 1000:.1f}s"  # Instagram reports milliseconds
    else:
        video = (((answers.get(0) or {}).get("data") or {}).get("videos") or [{}])[0]
        m.update(views=video.get("view_count"), likes=video.get("like_count"), comments=video.get("comment_count"),
                 shares=video.get("share_count"))
    return m


def run_metrics(args):
    if args.platform not in ("youtube", "instagram", "tiktok"):
        print("--metrics works for --platform youtube, instagram, and tiktok.", file=sys.stderr)
        return 2
    if not args.video_id:
        print("--metrics needs --video-id: the platform's ID for the posted video.", file=sys.stderr)
        return 2
    requests = metrics_requests(args)
    if args.dry_run:
        print("=== DRY RUN: no request sent ===")
        for label, method, url, headers, body, secrets, _ in requests:
            print(f"{label}:")
            print(f"  {method} {redact(url, secrets)}")
            for name, value in headers.items():
                print(f"  {name}: {redact(value, secrets)}")
            if body:
                print(f"  Body: {redact(body.decode('utf-8'), secrets)}")
        print("=== END DRY RUN ===")
        return 0
    answers = {}
    for i, (label, method, url, headers, body, secrets, optional) in enumerate(requests):
        try:
            answers[i] = http_json(url, headers, args.timeout, body, method)
        except urllib.error.HTTPError as e:
            detail = redact(e.read().decode("utf-8", "replace")[:300], secrets)
            print(f"{label}: HTTP {e.code} {detail}", file=sys.stderr)
            if not optional:
                return 1
            print(f"(skipped: {label} is optional; for YouTube it needs the yt-analytics.readonly scope)", file=sys.stderr)
        except urllib.error.URLError as e:
            print(f"{label}: couldn't connect ({e.reason})", file=sys.stderr)
            return 1
    m = read_metrics(args.platform, answers)
    print(json.dumps({"platform": args.platform, "video_id": args.video_id, **m}, indent=2))
    cell = lambda k: "" if m.get(k) is None else str(m[k])  # noqa: E731
    print("For state/video-log.md (Views | Avg watch | 3s hold | Likes | Comments | Shares | Saves | Updated):")
    print(f"| {cell('views')} | {cell('avg_watch')} |  | {cell('likes')} | {cell('comments')} | {cell('shares')} | {cell('saves')} | {time.strftime('%Y-%m-%d')} |")
    return 0


VIDEO_RUNNERS = {
    "youtube": run_youtube,
    "instagram": run_instagram,
    "tiktok": run_tiktok,
}


def main():
    args = parse_args()

    # reading numbers posts nothing, so it skips the send gate below
    if args.metrics:
        sys.exit(run_metrics(args))

    if not args.dry_run and not args.confirmed:
        print(
            "Refusing to send: pass --dry-run to preview the request, or --confirmed to "
            "actually send it. This script never sends without one of those being explicit.",
            file=sys.stderr,
        )
        sys.exit(2)

    if args.cover_ms is not None or args.cover_url:
        if args.platform == "youtube":
            print(
                "--cover-ms/--cover-url aren't supported for --platform youtube: this script can't set a "
                "Shorts cover through the API. Pick the cover frame in the YouTube app after uploading.",
                file=sys.stderr,
            )
            sys.exit(2)
        if args.platform not in ("instagram", "tiktok"):
            print("--cover-ms and --cover-url are for --platform instagram and tiktok only.", file=sys.stderr)
            sys.exit(2)
        if args.cover_url and args.platform == "tiktok":
            print("TikTok takes a cover frame, not an image: use --cover-ms instead of --cover-url.", file=sys.stderr)
            sys.exit(2)
        if args.cover_ms is not None and args.cover_ms < 0:
            print("--cover-ms is a time in milliseconds from the start, so it can't be negative.", file=sys.stderr)
            sys.exit(2)

    if args.platform in VIDEO_RUNNERS:
        sys.exit(VIDEO_RUNNERS[args.platform](args))

    text = load_text(args.text)

    if args.platform == "reddit":
        if not args.subreddit or not args.title:
            print(
                "--platform reddit requires both --subreddit and --title "
                "(Reddit self-posts need a title; the other platforms are body-only).",
                file=sys.stderr,
            )
            sys.exit(2)
        url, headers, body, secrets = build_reddit_request(text, args.subreddit, args.title, args.flair_id)
    elif args.platform == "telegram":
        if not args.chat_id:
            print(
                "--platform telegram requires --chat-id (a numeric chat ID, or "
                "'@channelusername' for a public channel).",
                file=sys.stderr,
            )
            sys.exit(2)
        url, headers, body, secrets = build_telegram_request(text, args.chat_id, args.parse_mode)
    elif args.platform == "devto":
        if not args.title:
            print(
                "--platform devto requires --title (dev.to articles need one, "
                "the same as Reddit self-posts).",
                file=sys.stderr,
            )
            sys.exit(2)
        tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
        url, headers, body, secrets = build_devto_request(text, args.title, tags, args.org_id)
    else:
        url, headers, body, secrets = BUILDERS[args.platform](text)

    if args.dry_run:
        print("=== DRY RUN: no request sent ===")
        print(f"Platform: {args.platform}")
        print(f"Note: {NOTES[args.platform]}")
        print("Method: POST")
        # redact the URL itself, not just headers/body - Discord's webhook URL IS the
        # credential, so printing it unredacted here would defeat the point of --dry-run.
        print(f"URL: {redact(url, secrets)}")
        print("Headers:")
        for name, value in headers.items():
            print(f"  {name}: {redact(value, secrets)}")
        print(f"Body ({len(body)} bytes):")
        print(redact(body.decode("utf-8"), secrets))
        print("=== END DRY RUN ===")
        sys.exit(0)

    request = urllib.request.Request(url, data=body, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            status = response.getcode()
            reason = response.reason
            response_body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        try:
            error_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            error_body = ""
        print(f"{args.platform} API returned non-2xx status", file=sys.stderr)
        print(f"Status: {e.code} {e.reason}", file=sys.stderr)
        print(f"Response: {error_body[:500] or '(empty body)'}", file=sys.stderr)
        sys.exit(4)
    except (urllib.error.URLError, OSError) as e:
        print(f"Failed to reach {args.platform} API: {e}", file=sys.stderr)
        sys.exit(3)

    print(f"Posted to {args.platform}")
    print(f"Status: {status} {reason}")
    print(f"Response: {response_body[:500] or '(empty body)'}")
    sys.exit(0)


if __name__ == "__main__":
    main()
