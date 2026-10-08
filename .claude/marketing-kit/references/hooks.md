# Hooks

The first second decides whether anyone watches the rest. `short-form-video`
reads this file when it writes a hook, and offers the user three, each from
a different pattern below, so the choice is real. With the renderer's hook
variants (`data-variant`, see `video-rendering.md`), all three can be
rendered and tested.

## What every hook needs

- **It works with the sound off.** It's on screen from the first frame, as
  text, because many viewers decide before the audio registers. The first
  frame is also the default cover.
- **Short.** Under about 8 words on screen; readable in a second.
- **Specific.** A number, a named situation, a concrete result. "3 invoice
  mistakes" beats "tips for freelancers".
- **True, and kept.** The video delivers what the hook promises, early.
  A hook the video doesn't pay off is how a post gets swiped away at second
  three, and how an account loses trust.
- **In the brand's voice.** Banned words in `brand-voice.md` apply.
  Lowercase and slang only if the voice is that casual.

## Patterns by goal

| Pattern | Shape | Example (fictional invoicing app) | Best for |
|---|---|---|---|
| Pain | Name the problem the viewer has right now | "you're losing money on every late invoice" | Ads, explainers |
| Number promise | A countable payoff | "3 invoice mistakes that cost you a week" | Tips, countdowns |
| Contrarian | A belief the brand holds that most don't | "stop sending invoices on Fridays" | Hot takes, thought leadership |
| Curiosity gap | What happened, without the ending | "a client paid in 4 minutes. here's why" | Storytime, case studies |
| POV | The viewer inside a moment they've lived | "pov: the client asks to pay next month" | Everyday posts |
| Before / after | The change, stated up front | "14 steps to invoice. now it's 3" (only if true) | Demos, launches |
| Direct question | A question the viewer answers in their head | "do you still invoice from a spreadsheet?" | FAQ, comment bait |
| Callout | Who it's for, so the right people stop | "freelancers who hate chasing payments:" | Niche audiences |
| Mistake | What the viewer is doing wrong | "you're writing your invoice subject lines wrong" | Tips, how-tos |
| Result first | The outcome, then how | "paid 9 days sooner, with one change" (only if real) | Case studies, testimonials |

Results, numbers, and customer outcomes must be real and the user's to
share. If they aren't, use a different pattern.

## Avoid

- Clickbait the video doesn't pay off ("you won't believe...").
- Throat-clearing: "hey guys", "so today I want to talk about", a logo
  intro before the point.
- Generic openers that fit any video: "here are some tips", "did you know".
- Claims about competitors, or about people's identity, health, or money
  worries meant to scare.
- A question with an obvious "no" ("want to waste money?").

## Testing hooks

- Write three, each from a different pattern, and let the user pick, or
  render all three as variants of one page: everything after the hook
  stays the same, so the hook is the only thing being tested.
- Instagram's trial reels show a reel to non-followers first, which suits
  testing variants; posting a different variant to each platform also
  works. Compare the share of viewers still watching after three seconds
  (each platform's own analytics shows it) rather than likes.
- Log which hook ran where in `state/video-log.md`, so the next video can
  start from what worked for this account.
