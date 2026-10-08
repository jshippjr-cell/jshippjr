# Everyday / FYP formats

The everyday, memeable formats that fill most of a brand's feed on TikTok,
Instagram Reels, and YouTube Shorts: POVs, tier lists, text-message skits,
storytimes. `short-form-video` reads this file when the user wants an
everyday post rather than a marketing video type (`video-types.md`), and
`content-calendar` uses it to rotate formats through the week. Edit it
like `brand-voice.md` if your mix differs.

Every format here has a template in `scripts/video/templates/` that
`render.js` turns into a finished 9:16 video with an original soundtrack,
so none of them needs filming, except day in the life (real footage) and
before/after with a real result (real photos).

## The formats at a glance

| Group | Format | Template | Why it gets engagement | Default sound | Lifespan |
|---|---|---|---|---|---|
| Meme captions | POV | `pov.html` | Viewers see themselves, so they share and tag | `hiphop`, scratch, boom | Evergreen |
| | Nobody / me | `nobody-me.html` | An oddly specific habit people admit to in the comments | `phonk`, typing, boom | Evergreen |
| | Expectation vs reality | `expectation-reality.html` | The gap is the joke, and it's honest | `pop`, scratch | Evergreen |
| | Tell me without telling me | `tell-me-without.html` | Insider details signal belonging; viewers add their own | `jersey`, swish | Evergreen |
| | Things that just make sense | `makes-sense.html` | Small truths people nod at, like, and save | `lofi`, ding | Evergreen |
| | Starter pack | `starter-pack.html` | An affectionate stereotype people tag friends in | `funk`, pop, boom | Evergreen |
| Comment bait | Tier list | `tier-list.html` | Everyone disagrees with one placement | `jersey`, ding, buzzer | Evergreen |
| | This or that | `this-or-that.html` | A low-effort reply: "early bird, email, music" | `funk`, swish, tick | Evergreen |
| | Hot take | `hot-take.html` | Agree or disagree, in the comments | `phonk`, horn, boom | Evergreen |
| | Green flags / red flags | `flags.html` | People add their own flags | `pop`, ding, buzzer | Evergreen |
| | Guess it in 3 seconds | `quiz.html` | Viewers wait for the answer and post their score | `house`, tick, ding | Evergreen |
| | Rating things | `rating.html` | Scores invite counter-scores | `hiphop`, buzzer, boom | Evergreen |
| UI skits | Text-message skit | `text-chat.html` | Reading along holds attention to the last bubble | `lofi`, ping, rimshot | Evergreen |
| | Lock-screen notifications | `notifications.html` | Escalation viewers feel, then relief | `phonk`, ping, cash | Evergreen |
| | Social post skit | `post-card.html` | A familiar layout with the punchline in the replies | `pop`, ping, rimshot | Evergreen |
| | Loading bar | `loading.html` | A stall and an error everyone has lived | `tech`, glitch, ding | Evergreen |
| Story & everyday | Storytime | `storytime.html` | A story with a "part 2" earns the follow | `lofi`, one cue on the twist | Evergreen |
| | Top-5 countdown | `countdown.html` | Useful, so it's saved; viewers stay for #1 | `house`, drumroll, boom | Evergreen |
| | Day in the life | `day-in-life.html` | Real people behind the brand | `acoustic`, shutter | Evergreen |
| | Wait for it (reveal) | `reveal.html` | Suspense holds viewers to the reveal | `cinematic`, drumroll, boom | Evergreen |
| | Before / after | `before-after.html` | The transformation is the payoff | `house`, whoosh | Evergreen |
| | Slideshow / carousel | `slideshow.html` | Saves, and it doubles as a photo carousel | `acoustic`, swish | Evergreen |

All 22 are evergreen: they've outlived the trends that started them, so
they work any week. Trend-dependent posts (a specific sound, a dance, a
meme that's peaking this week) are the 20% below, and they're made in the
app, not here.

## Planning everyday posts

- **The mix:** a rule of thumb many social teams use is about 70%
  evergreen formats (this file), 20% trends (a current sound or meme,
  checked live), and 10% experiments (a new format, a new angle).
- **Rotation:** don't repeat a format within a week, and move between the
  groups, so the feed has a POV, a tier list, a skit, and a story rather
  than four POVs. Two or three posts in the same format over a month is
  fine; the topic changes each time.
- **Fit to goal:** comment bait for reach and comments, story and
  countdown for saves and follows, UI skits and meme captions for shares.
  One clear call to action per post: comment, save, follow, or tag.
- **Hooks:** each template's hook is on screen from the first frame (class
  `now`), since it's the cover and the swipe decision. `hooks.md` has the
  patterns, and hook variants render several versions of one post to test.
- **Trends:** the skill may search the web for what's trending this week,
  but only as a hint: trends move faster than search results, so check in
  the app before relying on one. Prefer an evergreen format with a fresh
  topic over a trend that may be over.
- **Trending sounds** live inside each app. To use one, post the video and
  add the sound in the app, with the video's own audio turned down; an
  API or a render can't add one. Never put a popular song in the render.

## Writing the copy in the brand's voice

The templates ship with a neutral, playful default for a fictional
invoicing app. Rewrite every line for the brand, following
`brand-voice.md`:
- **Case:** the formats are traditionally lowercase ("pov: you..."). Use
  lowercase only if the voice is casual enough; otherwise use sentence
  case, which reads fine in every format.
- **Slang:** only words already in the brand's voice, or used by its
  audience in a way the brand could say without sounding like it's trying.
  When in doubt, leave it out: plain, specific, and funny beats slang.
- **Emoji:** follow the emoji rule in `brand-voice.md`. If emoji are out,
  replace the big ones with a word, a photo, or nothing, and drop the
  inline ones. No format depends on emoji to make sense.
- **Banned words** in `brand-voice.md` apply to captions too.
- Keep captions short: under about 12 words, readable in two seconds.
  The lint in `render.js` flags any that spill out of their box.

## Rules for every format

- **Skits are fiction.** Chats, notifications, and posts are clearly made
  up, with generic roles ("client", "a friend") and animal or emoji
  avatars. Never use a real person's name, handle, photo, post, or
  message, and never recreate a real conversation.
- **No fake proof.** No invented reviews, testimonials, ratings of the
  product, customer counts, or poll results. A poll shows real numbers
  from a poll you ran, or none.
- **No borrowed property.** No copyrighted meme images, movie or cartoon
  characters, celebrity photos, other brands' logos, or a real app's look
  (the mockups here are generic on purpose).
- **No punching down.** Joke about situations, habits, and the work, never
  about people's identity, appearance, health, tragedy, or politics.
  Starter packs and flags are about roles and behaviors, not groups.
- **Real results only.** A before/after, a number, or a customer moment
  must be real and the user's to share.

## The formats

Each format lists its beats, what to change, and a line of copy at two
tones (playful / professional) to show how the voice changes it.

### POV (`pov.html`, 12s)
- **Beats:** a "POV" sticker and "you..." setup → the turn, on a record
  scratch with the beat dropping out → the punchline, on a boom → an
  optional soft brand line.
- **Change:** the three captions, around a moment the audience has lived.
- **Copy:** "pov: you finally sent every invoice before friday" /
  "POV: Every invoice went out before Friday."
- **Skip it** when there's no shared moment, e.g. a niche feature only
  power users know.

### Nobody / me (`nobody-me.html`, 10s)
- **Beats:** "nobody:", "absolutely no one:", "me at 2am:" building to the
  drop → the habit escalating, one step per beat → a comment prompt.
- **Change:** the habit; any small ritual that escalates (file names,
  tabs, coffee orders).
- **Copy:** "me at 2am: renaming invoice_final_v3" / "Our support team at
  2am: answering one more ticket."
- **Skip it** if the habit would make the brand look careless (a bank
  losing files is not a joke).

### Expectation vs reality (`expectation-reality.html`, 12s)
- **Beats:** the expectation pane → reality slams in on a record scratch
  → "tag the friend".
- **Change:** both panes, about the same thing. Real photos go in each
  `.pane` as `<img class="bg-media">`.
- **Copy:** "set your own hours. all of them." / "Expectation: launch on
  Monday. Reality: launch on Monday, plus three quick fixes."
- **Skip it** when the "reality" is the product failing for a customer.

### Tell me you're a ___ without telling me (`tell-me-without.html`, 12s)
- **Beats:** the prompt → four quick answers on the beat → "your turn".
- **Change:** the identity (the audience's role) and four insider details.
- **Copy:** "a folder called 'taxes (real)'" / "Tell me you work in
  finance without telling me: 'let's take this offline.'"
- **Skip it** when the audience isn't one recognizable group.

### Things that just make sense (`makes-sense.html`, 14s)
- **Beats:** the title stays up → five small truths swap in → "add one".
- **Change:** the five items; the product can be one of them, never all.
- **Copy:** "one tab open. just one." / "Agendas sent before the meeting."
- **Skip it** when it would be five product features (that's an ad).

### Starter pack (`starter-pack.html`, 12s)
- **Beats:** the title → six items pop into a grid → an "accurate?" stamp
  and "what's missing?".
- **Change:** the identity and six items, two to four words each, the
  funniest last. Real product photos go in a `.cell` as
  `<img class="bg-media">`.
- **Copy:** "the third coffee" / "The new-manager starter pack: a 1:1
  template."
- **Skip it** for groups defined by age, gender, ethnicity, or any other
  identity; roles, hobbies, and situations only.

### Tier list (`tier-list.html`, 16s)
- **Beats:** the title → six items, each shown big, then dropped into its
  tier (ding at the top, buzzer at the bottom) → "rank it different?".
- **Change:** the topic and six items. Rank honestly, with one placement
  that's a little spicy.
- **Copy:** "ranking ways to get paid faster" / "Ranking onboarding
  tactics by how much they help."
- **Skip it** for ranking people, competitors, or customers' choices.

### This or that (`this-or-that.html`, 14s)
- **Beats:** three rounds of two choices, each with a draining timer →
  "comment your picks", with the brand's own picks.
- **Change:** the three pairs; evenly split, no right answer.
- **Copy:** "early bird or night owl" / "Async update or quick call?"
- **Skip it** when one side is the product and the other a competitor.

### Hot take (`hot-take.html`, 12s)
- **Beats:** an "unpopular opinion" sticker on an air horn → the take →
  a poll that swings and lands on a tie → "break the tie".
- **Change:** the take: about the work, defensible, and something the
  brand actually believes.
- **Copy:** "invoices should go out the day the work ends." / "Unpopular
  opinion: most status meetings should be a document."
- **Skip it** for anything about people, groups, or politics. Poll
  numbers only from a real poll.

### Green flags / red flags (`flags.html`, 14s)
- **Beats:** three green flags → three red flags → "add one".
- **Change:** the subject (a client, a tool, a job post) and the flags,
  all behaviors.
- **Copy:** "pays the deposit without asking" / "Sends feedback in one
  consolidated email."
- **Skip it** when the red flags would describe the brand's own customers
  too pointedly.

### Guess it in 3 seconds (`quiz.html`, 15s)
- **Beats:** a puzzle → a 3-2-1 ring with ticks → the answer on a ding,
  twice → "how many did you get?".
- **Change:** the puzzles. Emoji puzzles of everyday phrases beat trivia;
  any real trivia must be checked.
- **Copy:** "📧 ☝️ 📧 = per my last email" / "Guess the metric from three
  emoji."

### Rating things (`rating.html`, 13s)
- **Beats:** the title → four things, each rated with a stamp (buzzer on
  the low one, boom on the top one) → "what's yours?".
- **Change:** the topic and four items. Scores are opinions; make them
  fun.
- **Copy:** "rating email sign-offs" / "Rating meeting formats out of 10."
- **Skip it** for rating people or other brands' products.

### Text-message skit (`text-chat.html`, 15s)
- **Beats:** a chat plays out, with typing dots before replies and a
  rimshot on the punchline → a one-line payoff.
- **Change:** the contact's role and the messages; one or two short lines
  per bubble.
- **Copy:** "can you make it bigger / but also smaller" / "Can we move
  the deadline up? / By a week? / Yesterday."
- **Skip it** if it would recreate a real conversation, even anonymized.

### Lock-screen notifications (`notifications.html`, 12s)
- **Beats:** a lock screen fills with escalating notifications → the one
  notification that makes it fine.
- **Change:** up to four notifications (generic app names), then the
  brand's own as the relief.
- **Copy:** "quick call? / actually, can it be now?" / "Calendar: 3
  meetings moved to 8am."

### Social post skit (`post-card.html`, 13s)
- **Beats:** a "POV" setup → a post whose likes count up while replies
  roll in, the last one the punchline → a payoff line.
- **Change:** the post and replies, keeping the POV framing.
- **Copy:** "new rates start today. that's the post." / "We shipped
  dark mode. That's the update."
- **Skip it** if the replies would praise the product: that's a fake
  review.

### Loading bar (`loading.html`, 12s)
- **Beats:** something "loading" crawls to 99% and stalls → an error
  dialog on a glitch, the beat dropping out → the fix loads it.
- **Change:** what's loading and the fix.
- **Copy:** "monday morning, loading motivation…" / "Loading Q4
  planning…"

### Storytime (`storytime.html`, 18s)
- **Beats:** "storytime" and "part 1" stickers → the story in short
  chunks, word by word → "part 2?".
- **Change:** the story: real, the brand's own or a customer's with
  permission, in chunks of four to nine words.
- **Copy:** "so I once sent an invoice to the wrong client." / "Our first
  customer found us by accident."
- **Skip it** without a real story; never invent one.
- **Told aloud:** for a storytime with a voiceover (the user's own voice
  works best), use `narrated.html` through `compose.js`: one chunk of the
  story per line, captions synced to the voice, and the "storytime" sticker
  idea as the hook.

### Top-5 countdown (`countdown.html`, 16s)
- **Beats:** the promise with a "save this" sticker → tips 5 to 1, a
  drumroll into #1 → "which one first?".
- **Change:** the five tips, correct and specific, the strongest at #1.
- **Copy:** "send it the day you finish" / "Put the due date in the
  subject line."

### Day in the life (`day-in-life.html`, 16s)
- **Beats:** the title → five timestamped moments, each on a camera
  shutter → a question back to the viewer.
- **Change:** needs the person's own photo or clip for each moment; without
  them, offer a shot list instead. Times and moments must be true.
- **Copy:** "coffee first, emails second" / "8:00: Inbox, then the
  roadmap."

### Wait for it (`reveal.html`, 12s)
- **Beats:** a tease → "wait for it…" over a drumroll and a filling bar →
  a flash, a boom, and the beat dropping on the reveal → the CTA.
- **Change:** the reveal: a launch, a feature, news. It has to be worth
  the wait; put a real product shot in its background slot.
- **Copy:** "we've been working on something" / "Something new arrives
  Tuesday."

### Before / after (`before-after.html`, 12s)
- **Beats:** the "before" side → a wipe on a whoosh → the "after" side →
  a question.
- **Change:** for a product, a space, or a customer's result, the actual
  before and after photos in each `.side`. Never stock, AI, or a mock-up
  for a result. The text-only default suits things anyone can relate to.
- **Copy:** "my inbox: monday vs friday" / "Our onboarding: 14 steps then,
  3 now" (only if true).

### Slideshow / carousel (`slideshow.html`, 17.5s)
- **Beats:** a title slide → five tips, one per photo → a question.
- **Change:** a photo per slide and one short line each.
- **Also:** `node scripts/video/render.js slideshow.html --slides` writes
  each slide as a 1080x1920 PNG, to post as a TikTok photo carousel or an
  Instagram carousel (which then use the app's own music).
- **Copy:** "send the invoice the day you finish" / "Send the invoice the
  day the work ends."
