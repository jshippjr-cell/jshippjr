# Community post examples

Worked examples of `community-post-generator` output, referenced from the
skill's "Example output" section. Fictional unless they say otherwise.

> Fictional example: a "one-click export" feature announcement, checked
> against a fictional `r/SaaS`-style subreddit whose rules turn out to
> block a straight promotional post.

```markdown
## Community Research Summary
**Source Confidence: Primary** — fetched directly from `r/exampleSaaS`'s
own rules page and post listing just now.

Checked `r/exampleSaaS`'s rules (fetched just now) and its last ~15
top-of-month posts. Rule 3 reads: "No direct promotion of your own
product outside the weekly Self-Promo Saturday thread; posts that are
primarily an ad for something you built will be removed on sight,
regardless of upvotes." Sampled posts confirm this in practice — the
posts that did well this month are build-in-public / lessons-learned
write-ups, not launch announcements, and read casually and first-person.
No flair requirement found; no stated karma/account-age minimum.

## Go / No-Go
No-go, as a straight announcement — Rule 3 explicitly blocks this outside
the weekly Self-Promo Saturday thread. Two real options instead: (1) wait
for the next Self-Promo Saturday and post there, or (2) reframe as a
lessons-learned post about *why* one-click export was worth building
(the problem, the tradeoffs, what broke) with the product mentioned only
in passing — that angle matches what's actually working in this
subreddit right now.

## Compliance Checklist
- Confirm whether Self-Promo Saturday requires a minimum account age to
  post in it (not stated in the rules fetched; check the pinned thread
  itself before posting).

## Next Step
Nothing drafted this run, per the No-Go above. Reply with which of the
two options above you want, and this skill will draft that version next.
```

> If step 2 had been a clear go for Reddit, Product Hunt Discussions, or
> Indie Hackers, **Drafted Post** would follow the same Markdown `##`
> heading immediately after **Go / No-Go**, as a title line plus the full
> self-post body in the community's own voice from step 3 (for Indie
> Hackers, that body specifically needs the founder-story/stage/questions
> shape — see the Output structure section above).

> **A real Go case, Hacker News shape** (from an actual test run against
> this plugin itself) — showing both the three-piece Show HN structure and
> the natural-writing rule from step 5 actually applied, not just stated:
>
> ```markdown
> ## Drafted Post
> **Title:** Show HN: A Claude Code plugin that can't post without a human confirming
>
> **URL:** https://github.com/marcosmodly/marketing-skill
>
> **Maker's first comment:**
> Hi HN. I got annoyed at how many "AI marketing automation" tools just
> assume it's fine to post on your behalf, so I built this one to not be
> able to do that.
>
> Every skill in it that drafts content is hard-blocked from marking
> anything "Approved." The only thing that can flip that status is a real
> human reply in the same conversation, right before it actually sends. If
> a scheduled run fires and nobody's there to answer, it just leaves the
> drafts queued. That's on purpose, not something I forgot to handle.
>
> It's a set of Claude Code skills: competitor research, batch content
> calendars, turning one piece of content into a LinkedIn post/thread/
> newsletter, ad copy, video briefs, and handing finished stuff off to
> your own automation or a platform API. Plain Markdown instructions plus
> two stdlib-only Python scripts. No backend, nothing running on my
> servers.
>
> Happy to get into the approval-gate design if anyone's curious, or tell
> me why it's wrong.
> ```
>
> No em dashes, no "it's not just X, it's Y," no throat-clearing opener,
> sentence lengths that actually vary, and a closing line that invites
> genuine pushback instead of a generic CTA — that's the bar from step 5,
> applied rather than just described.

> **What the two `Secondary` tiers actually look like** (both happened in
> real runs, not hypotheticals):
>
> `Secondary (third-party)` — WebFetch to reddit.com was blocked outright
> by the runtime's network policy (every path on the domain failed, not
> just one page), so research fell back to WebSearch, which surfaced
> several third-party marketing-blog summaries converging on the same
> numbers (a self-promo cadence limit, a designated feedback-thread lane) —
> but none of them were reddit.com or Reddit's own words, and sites like
> these can all be echoing one shared, unverified source. That run opened
> with `**Source Confidence: Secondary (third-party)** — reddit.com was
> unreachable; the below comes from third-party summaries only, not
> Reddit's own rules page`.
>
> `Secondary (official)` — a separate run against Product Hunt also had
> its direct fetches blocked (producthunt.com and help.producthunt.com
> both denied by the network policy), but several of the WebSearch
> snippets were visibly quoting Product Hunt's own Help Center articles
> by name and URL (its Forum Guidelines and Community Guidelines pages) —
> one step removed from a direct read, but still Product Hunt's own
> stated words, not a third party's guess at them. That run opened with
> `**Source Confidence: Secondary (official)** — producthunt.com was
> blocked this run; the below comes from search snippets that quote
> Product Hunt's own Help Center articles directly, not a direct fetch`.
>
> Either way, a go verdict built on either tier still needs the
> corresponding hedge in the Go/No-Go line (step 4) — `Secondary
> (official)` earns a lighter one than `Secondary (third-party)`, but
> neither is presented as flatly as a `Primary`-confirmed go.

> **What the target-verification check actually caught** (also a real
> run, not hypothetical): researching Indie Hackers, one search result
> summarized "r/indiehackers permits self-promotion exactly once per
> product, using the SHOW IH flair" — plausible-sounding, and wrong for
> the actual target. A follow-up search confirmed Show IH is a real
> indiehackers.com group, not a subreddit flair; the first source had
> conflated the two platforms under their shared name. That claim was
> excluded entirely rather than folded in as a lower-confidence data
> point — it wasn't weaker evidence about indiehackers.com, it was zero
> evidence about indiehackers.com, since it was actually describing
> something else. This is the failure mode step 3's target-verification
> check exists to catch before a claim ever reaches the Source Confidence
> tiers above.

> **What a `User-Supplied` Discord case looks like.** Unlike the examples
> above, this one is illustrative, not from an actual run — this skill
> hasn't been tested against a real Discord server with a real user in
> this session, so it's shown as a worked hypothetical rather than
> mislabeled as something that happened:
>
> ```markdown
> ## Community Research Summary
> **Source Confidence: User-Supplied** — the server isn't Discovery-listed
> and has no public page to check; the requester is a member and
> described the rules directly, checked just now in conversation, not
> independently verified against the server itself.
>
> Target: the fictional "BuildSpace" Discord, #showcase channel. Per the
> requester: self-promotion is welcome in #showcase specifically (not in
> #general), one post per project, screenshots or a working link expected,
> no cross-posting the same thing in multiple channels. No stated account
> age or role requirement.
>
> ## Go / No-Go
> Go, based on what the requester described — this skill couldn't check
> BuildSpace's actual rules channel itself, so if you're not sure that's
> still current, glance at the pinned message before sending.
>
> ## Drafted Post
> Shipped a small thing this week: [product], a [one-line description].
> Built it because [the actual reason], and the part I wasn't sure would
> work was [specific detail]. Screenshot below. Would genuinely like to
> know if the [specific feature] makes sense to anyone outside my own
> head.
>
> ## Compliance Checklist
> - Confirm #showcase is still the right channel and the one-post-per-
>   project rule hasn't changed since you last checked.
>
> ## Next Step
> Nothing sent. If BuildSpace has a webhook set up for #showcase,
> `publish-pipeline`'s direct-post path can send this immediately, no
> approval queue involved — see the plugin's `docs/publishing.md`.
> ```
>
> Same natural-writing bar as every other draft (no em dashes, no
> throat-clearing opener), same explicit hedge pattern as the Secondary
> tiers, just labeled for what it actually is: unverified by this skill,
> taken on the requester's own word.

> **What a `User-Supplied` Slack case looks like, and how it differs from
> Discord's.** Also illustrative, not from an actual run:
>
> ```markdown
> ## Community Research Summary
> **Source Confidence: User-Supplied** — no research path exists for a
> private Slack workspace (no Discovery-style exception the way Discord
> has one); the requester is a member and described the rules directly,
> checked just now in conversation.
>
> Target: the fictional "Foundersync" Slack, #wins channel. Per the
> requester: #wins is specifically for sharing things you shipped,
> screenshots welcome, no more than one post per week per person, keep it
> to the actual update rather than a pitch. Sending would need a webhook
> for that channel, and the requester isn't sure whether their workspace
> requires admin approval to create one.
>
> ## Go / No-Go
> Go, based on what the requester described — this skill couldn't check
> Foundersync's actual channel rules itself, so confirm that's still
> current before sending.
>
> ## Drafted Post
> Shipped the export feature today. Someone asked for this three separate
> times last month and I kept saying "soon" - it's live now, one click,
> picks the format automatically. *Screenshot below.* Still rough around
> the edges on large files, working on that next.
>
> ## Compliance Checklist
> - Confirm this doesn't exceed one #wins post this week already.
> - Confirm whether creating a webhook for #wins needs Workspace
>   Owner/Admin approval in this specific workspace, or whether the
>   requester can just do it themselves.
>
> ## Next Step
> Nothing sent. Sending isn't guaranteed to be a quick self-serve step
> here the way it would be for Discord - if Foundersync requires app
> approval, that has to happen before `publish-pipeline`'s direct-post
> path can be used at all.
> ```
>
> Notice `*Screenshot below.*` uses a single asterisk on purpose — that's
> mrkdwn bold, not italic, matching step 5's rule. A Discord draft with
> that same intent would use `**Screenshot below.**` instead. Same
> `User-Supplied` tier, same honest hedging pattern, genuinely different
> syntax and a genuinely more cautious Next Step - not a find-and-replace
> of the Discord example.

> **What a `Secondary` Telegram case looks like, and how it differs from
> Discord's or Slack's `User-Supplied`.** Illustrative, not from an actual
> run — this is the case that only exists for Telegram among the chat
> platforms, since it depends on the target having a public `@username`:
>
> ```markdown
> ## Community Research Summary
> **Source Confidence: Secondary (official)** — the target is a public
> group (`@examplebuilders`), so `https://t.me/s/examplebuilders` was
> attempted for a live preview; the fetch itself was blocked by this
> runtime's network policy, but WebSearch surfaced snippets quoting that
> same `t.me/s/examplebuilders` page directly, including its pinned
> message.
>
> Target: the fictional "@examplebuilders" Telegram group (confirmed a
> group, not a channel — members can post, not just admins). Pinned
> message (per the quoted snippet): self-promotion allowed on Fridays
> only, one link per person, no cross-posting the same thing in multiple
> Telegram communities. Requester confirmed they're a member.
>
> ## Go / No-Go
> Go, but only if today is Friday per the pinned rule above — based on
> `Secondary (official)` sourcing (the pinned message quoted via search
> snippet, not a direct fetch this run), so confirm the rule is still
> current before sending.
>
> ## Drafted Post
> Been heads-down on this for about six weeks: <b>ExportKit</b>, a
> one-click export tool for the report-building grind. Built it after
> losing an entire afternoon to a manual export at my last job. Free tier
> covers most single-user cases. Link in the next message so this doesn't
> get flagged as a link-drop.
>
> ## Compliance Checklist
> - Confirm today is actually a Friday before sending.
> - Confirm the one-link-per-person rule hasn't changed since the pinned
>   message was last updated.
>
> ## Next Step
> Nothing sent. If the requester has a Telegram bot already added to
> `@examplebuilders` by one of its admins, `publish-pipeline`'s direct-post
> path can send this via the Bot API — creating the bot itself needs no
> approval, but it only works if that add-to-chat step already happened.
> ```
>
> `<b>ExportKit</b>` uses Telegram's HTML tag, not `**ExportKit**` or
> `*ExportKit*` — a third syntax, distinct from both Discord's near-standard
> Markdown and Slack's mrkdwn. And unlike either Discord or Slack example
> above, this one reached `Secondary (official)`, not `User-Supplied` — the
> target's public `@username` made a real (if network-blocked-and-
> search-recovered) research pass possible, a determination made back in
> step 2 before research even started. A private-target Telegram case would
> look identical in shape to the Discord or Slack `User-Supplied` examples
> above — same tier, same hedging — just with HTML tags in the draft
> instead of near-standard Markdown or mrkdwn.

> **A real research run, dev.to** — dev.to's own domain was blocked in this
> runtime (same pattern as reddit.com, producthunt.com, and the others), so
> this fell back to WebSearch, same as the `Secondary`-tier examples above.
> Unlike those, one specific claim stayed unconfirmed rather than resolving
> to a tier at all — shown here as it actually happened, gap included, not
> smoothed over:
>
> ```markdown
> ## Community Research Summary
> **Source Confidence: Secondary (official)** — dev.to's own domain was
> unreachable this run, but WebSearch surfaced content that traces back to
> dev.to's own pages: the `#showdev` tag's purpose confirmed by a named DEV
> Tag Moderator's own explanatory post, and the Organizations feature
> described in what reads as dev.to's own marketing copy for it. One gap:
> the Code of Conduct's specific self-promotion/spam wording could not be
> directly confirmed this run, from either a fetch or a search snippet.
>
> Target tags: `showdev`, `ai`, `opensource`, `buildinpublic` (4, the
> platform's per-post maximum). dev.to has a real per-tag moderation layer
> on top of its sitewide Code of Conduct — volunteer Tag Moderators can
> strip a tag that doesn't fit it, separately from the post itself being
> removed. `#showdev` is confirmed for real, triable projects, explicitly
> not tutorials, with no required founder-story/stage/questions shape the
> way Indie Hackers' Show IH has one. Posting under a personal account, not
> a dev.to Organization (requester isn't a member of one for this project).
>
> ## Go / No-Go
> Go, based on `Secondary (official)` sourcing — the structural signals
> (the `#showdev` tag's whole purpose, the Organizations feature's own
> marketing framing) both point toward self-promotion being welcome here,
> but the Code of Conduct's specific wording on it stayed unconfirmed this
> run. Treat this as a lean, not a fully confirmed rule, and skim
> `dev.to/code-of-conduct` directly before posting.
>
> ## Drafted Post
> **Title:** I built a Claude Code plugin that can't post anything without a human saying so
> **Tags:** showdev, ai, opensource, buildinpublic
>
> I got tired of "AI marketing automation" tools that assume it's fine to
> post on your behalf the moment you connect an account. So I built the
> opposite of that.
>
> marketing-skill is a Claude Code plugin: competitor research, batch
> content calendars, turning one piece of content into a LinkedIn post or a
> Twitter thread or a newsletter blurb, ad copy, video briefs, and a
> publishing step that hands finished content to your own automation or a
> platform API.
>
> The part I actually care about is the approval gate. Every skill that
> drafts content is hard-blocked from marking anything "Approved." The only
> thing that can flip that status is a real human reply in the same
> conversation, right before it sends. A scheduled run that fires with
> nobody there to answer just leaves the draft queued. It doesn't quietly
> go out anyway.
>
> For platforms like Reddit, Product Hunt, Hacker News, and Indie Hackers,
> there's a research step before drafting anything: the skill checks that
> specific subreddit's or forum's current rules and typical post style, and
> says plainly if a post wouldn't be welcome there. Discord, Slack, and
> Telegram get a variant of this, since most servers, workspaces, and
> private chats have no public page to check at all.
>
> Plain Markdown instructions plus two stdlib-only Python scripts. No
> backend, nothing running on my own servers.
>
> Genuinely curious whether the approval-gate design holds up against real
> use, or if there's a hole in it I'm not seeing yet.
>
> ## Compliance Checklist
> - Confirm the Code of Conduct's self-promotion/spam wording directly
>   before posting — this run's research couldn't reach it, so treat it as
>   unread, not as cleared.
> - Confirm this doesn't exceed whatever cadence dev.to considers normal
>   for one account — no stated cooldown was found, but this skill didn't
>   independently verify account-history norms, the same limit it can't
>   check for Hacker News either.
>
> ## Next Step
> Nothing sent. If the requester has a dev.to API key, `publish-pipeline`'s
> direct-post path can publish this immediately — dev.to's write API needs
> no approval process found in this skill's research, the simplest access
> story of any platform here. That ease is about access, though, not
> content: it says nothing about whether a Tag Moderator leaves all 4 tags
> in place afterward.
> ```
>
> The gap is part of the output, not hidden — a `Secondary (official)`
> tier carrying one explicitly named unconfirmed claim, not rounded up to a
> clean `Mixed` or smoothed into a vague general caveat. And unlike every
> other researchable platform's example above, the tag list itself was
> part of what got researched and drafted, not an afterthought — landing on
> 3 tags instead of 4, or swapping one out, would have been a legitimate
> outcome of this same research pass, not a failure of it.
