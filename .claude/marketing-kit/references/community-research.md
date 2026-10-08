# Community research, platform by platform

`community-post-generator` reads this file in its step 3 (deep research),
for the section matching the target platform. Read the whole section for
your target before researching: every rule below is part of that step,
not optional background. The cross-platform parts of step 3 (verifying a
source is about the named target, citing what was found, and tracking
source tiers) stay in the skill itself.

- **Subreddit rules.** Try
  `https://www.reddit.com/r/<subreddit>/about/rules.json` and
  `https://www.reddit.com/r/<subreddit>/about.json` (subscriber count,
  description, and whether it's quarantined, restricted, or banned —
  any of those is a hard stop; say so and stop). Reddit's own domain is
  not reachable from every runtime this skill executes in — if
  WebFetch to reddit.com fails outright, fall back to WebSearch for
  `"r/<subreddit>" rules` and the subreddit's wiki/sidebar, and say
  plainly if even that turns up nothing usable rather than drafting
  blind. Read every rule, not just the first few — in particular pull
  out:
  - Self-promotion/advertising policy: outright banned, capped by a
    "9:1" or "10%" self-promo ratio, restricted to a specific
    self-promo thread/day, requires mod pre-approval, or requires
    disclosure of affiliation with the product.
  - Any minimum account age or karma — this skill has no way to check
    the user's actual account against it, so surface the requirement
    and ask the user to confirm they clear it, rather than assuming.
    **If they don't clear it, or say their posts keep getting
    auto-removed** (often AutoMod quietly filtering new or low-karma
    accounts), don't stop at "you don't qualify." Lay out the real
    options, in this order:
    1. Message the subreddit's mods (modmail) before posting: say what
       they want to share and ask whether it's welcome, or, if a post
       was auto-removed, ask for it to be approved. Mods can approve a
       filtered post by hand. Offer to draft that message.
    2. Build a real history in that community first, by answering
       questions and commenting where they can actually help. Not
       karma farming: karma-farming subreddits and upvote swaps get
       accounts banned.
    3. A related community without the gate, researched the same way as
       the original target.
    4. A platform with no karma minimum at all: Show HN, Indie Hackers,
       or dev.to, each through its own section of this skill.
    Never suggest getting around the gate itself (a second account, a
    bought or borrowed aged account, asking for upvotes); under
    Reddit's own rules that's ban evasion or vote manipulation.
  - The subreddit's actual list of available post flairs, not just
    whether one is required — self-service flairs are choosable at
    submit time even when optional, so pull the real list (the submit
    form, sampled posts' own flair tags, or a `link_flair_text` field
    on sampled listings) and pick the best-fitting one for this draft
    regardless of whether the rules mandate one. Only skip flair
    entirely when research turns up no flair system at all for that
    subreddit, not when one was merely optional. Note whether flair is
    self-service or mod-assigned either way.
  - Text-post vs. link-post norms, and title-format conventions (some
    subreddits enforce a specific title template via AutoMod).
- **The actual "usual post."** Sample a handful of recent top/hot posts
  in that subreddit (e.g.
  `https://www.reddit.com/r/<subreddit>/top.json?t=month&limit=15`, same
  fallback-to-WebSearch rule as above if unreachable) to learn the
  community's real voice — typical title phrasing and length, how
  casual/first-person vs. formal it reads, and whether posts that do
  well there read as genuine discussion or as thinly-veiled promotion.
- **Product Hunt.** Research current Product Hunt community
  guidelines/help docs for whichever surface applies, plus a few recent
  Discussions posts on a similar topic for tone/format if that's the
  target. If it's a launch, be explicit that launches are scheduled and
  the maker is expected to actively answer comments all day — this
  skill drafts the tagline/description/first-comment text, not the
  launch logistics.
- **Hacker News.** Research current guidelines
  (`news.ycombinator.com/newsguidelines.html`) and Show HN norms
  (`.../showhn.html`), plus genuine HN discussion threads
  (`.../item?id=...`) if any turn up — those count as the platform's
  own words even relayed via search snippet, unlike a third-party
  "how to launch on HN" guide. HN's self-promotion norm is behavioral,
  not mechanical: there's no cooldown period or designated lane like
  Reddit or Product Hunt have — it's whether the *account's overall
  pattern* is genuine participation with occasional self-posting, or
  promotion-only. This skill can't audit an account's history, so
  surface that limit explicitly rather than quietly assuming it's fine.
  Two rules are hard, not norms to weigh: never solicit upvotes,
  comments, or submissions anywhere (not just in the post itself), and
  never coordinate voting — HN actively detects both and treats them
  as bannable, not just frowned-upon.
- **Indie Hackers.** Research the specific group's posting guidelines
  (shown on-site before posting, per IH's own group-guidelines
  feature) and recent posts in that group for tone/format — genuine
  indiehackers.com/post/... and indiehackers.com/group/... threads
  count as the platform's own words even via snippet, same as HN's
  item threads. Unlike Reddit, there's typically no hard cooldown or
  karma/account-age gate; unlike Reddit, Product Hunt, and Hacker News,
  IH is explicitly hospitable to founders sharing their own product,
  but only in the right shape — the **Show IH** convention specifically
  is lead with the founder story, state the current stage, and ask one
  or two concrete questions, not a bare link or a pitch. Posting the same
  pitch to multiple groups instead of the single most relevant one is
  discouraged, same spirit as cross-posting the same pitch to multiple
  subreddits.
- **dev.to.** Research two layers, not one: the sitewide Code of
  Conduct (`dev.to/code-of-conduct`), and each target tag's own
  submission guidelines, shown in that tag's sidebar
  (`dev.to/t/<tag>`) — a tag can carry its own posting guidance the
  same way a subreddit's sidebar does, enforced by that tag's
  volunteer Tag Moderators rather than sitewide staff. Sample recent
  posts under the target tag(s) (`dev.to/api/articles?tag=<tag>` is a
  public, unauthenticated read endpoint, similar in spirit to Reddit's
  `.json` listings) for tone/format. If `#showdev` is one of the
  target tags, confirm the content is a real, triable project rather
  than a tutorial or a bare announcement — a moderator can and does
  strip the tag from posts that don't fit, independent of whether the
  post itself survives. Don't treat a 2xx from the API (if drafting
  for direct send) as the same thing as "this was welcome" — API
  acceptance and tag/content moderation are two different, later,
  independent checks.
- **Discord.** Try the public route first, but expect it to come up
  empty for most servers: a large, established, Discovery-listed
  server (1,000+ members, opted into Server Discovery) may have a
  public description and preview via Discord's own site, and the
  no-auth invite-metadata endpoint (`discord.com/api/v9/invites/<code>`)
  returns a server name/description/member count if an invite link is
  available — but none of that includes rules text or message history,
  for any server, Discovery-listed or not. For the typical case (a
  private or invite-only server, which is most of them), there is
  nothing to fetch. **Ask the user directly** for what the server's
  rules channel actually says, and for that specific channel's own
  posting norms if it's a designated self-promo/showcase channel
  (common pattern: a `#self-promo` or `#show-and-tell` channel with its
  own pinned rules, separate from the server-wide ones). If they don't
  know or haven't checked, **don't proceed to drafting on a guess** —
  ask them to go check the pinned rules message first, the same way a
  No-Go elsewhere stops the process rather than working around it.
  Silence or "probably fine" from the user isn't the same as an actual
  answer.
- **Slack.** Even more closed than Discord: there's no evidence of
  anything analogous to Discord's Server Discovery/Lurker Mode for
  Slack workspaces — every "browse channels" feature found describes
  browsing public channels *inside a workspace you're already a
  member of*, not previewing a workspace from outside before joining,
  and Slack's API is fully OAuth-gated per-workspace with no public
  unauthenticated lookup found equivalent to Discord's invite-metadata
  endpoint. Treat the public-research route as not available at all for
  Slack, not just unlikely — **ask the user directly**, same pattern
  as Discord (the actual rules, the specific channel's own norms if
  it's a designated channel, and if they don't know, ask them to check
  rather than drafting on a guess). Same "silence isn't an answer" rule
  applies.
- **Telegram.** Which research path applies was already determined in
  step 2 — don't re-guess it here:
  - **Public channel/group:** try `https://t.me/s/<username>` (Telegram's
    unauthenticated web preview) for recent messages, and a pinned
    message if one shows in the preview — many channels/groups pin their
    posting rules or an "about this channel" message the same way a
    subreddit pins rules. If that fetch is blocked or the runtime can't
    reach `t.me`, fall back to WebSearch for the channel/group's own name
    plus "rules" or "telegram," same tiering rule as every other
    platform: snippets quoting the channel's own `t.me` page or pinned
    content are `Secondary (official)`, third-party mentions are
    `Secondary (third-party)`. If the preview loads but shows no explicit
    rules or pinned message, that's real signal too — say so, and treat
    the *typical recent message* pattern (tone, whether self-promotion
    already happens there) as the closest available substitute, same
    spirit as sampling a subreddit's top posts.
  - **Private channel/group:** no public surface exists, full stop —
    **ask the user directly**, same pattern as Discord and Slack (the
    actual rules if any were stated when they joined, typical norms
    they've observed, and if they don't know, ask them to check rather
    than drafting on a guess). Same "silence isn't an answer" rule
    applies.
  Either way, also note from step 2 whether it's a channel or a group —
  a channel where the user isn't an admin changes what gets drafted in
  step 5, regardless of which research path applied.
