# First-Touch "Capabilities Email" — Cabinet Deliberation

**Convened:** 2026-06-25 · **Chair:** Jon Shipp (CEO) · **CMO leads** (per CEO
directive) · **CTO on logistics** · **Mandate:** decide whether the first-touch
intro email should become a *composable, capabilities-doc-grade* asset — generated
when Jon clicks **Compose email**, with elements he can toggle on/off — and, if so,
how to actually deliver it. **The cabinet deliberates and returns options; Jon
decides.**

Governing rule unchanged: **the machine proposes, Jon disposes.** Agents disagree
where they actually disagree.

Roster: **CMO** (lead), **CTO** (logistics), **CRO**, **Founder's Advocate**,
**Head of Production**, **CFO**.

---

## The trigger

The founder's words: *"I only get one chance to make a good first impression. The
capabilities document is awesome to send **after** the initial touch — but the
initial touch needs to be just as awesome."*

Today the first touch is the weak link. **Compose email** (`outreach.html`) is a
`mailto:` link that drops a **plain-text** first-touch message into Jon's mail
client. Meanwhile the capabilities doc that follows is a branded, editable,
toggle-driven document. The two are mismatched: the *second* contact is gorgeous,
the *first* — the one that decides whether there's a second — is unstyled text.

---

## 1. The strategic question — CMO (lead)

**CMO:** The instinct is right, but I want to sharpen *what* "just as awesome" means,
because the obvious reading ("make the email a beautiful HTML brochure") is a trap.

A cold first touch has **one job: earn a reply.** Not to impress — to feel *relevant,
human, and low-risk* enough that a busy buyer answers. The capabilities doc's job is
different: it's the *considered* proof you send once there's interest. If we cargo-cult
the doc's richness into the cold open, we risk turning a personal note into a marketing
blast — which for a **new studio with no logos to flash** is exactly the wrong signal.

So my reframe: the first-touch upgrade isn't "make it pretty." It's **"make it
composable and razor-relevant"** — give Jon a **block composer** (like the doc's toggle
bar) so he can, in fifteen seconds, assemble *the right* first touch for *this* buyer:
the one relevant track, the one line about their brief, the call offer — and leave out
the rest. The awesomeness is **fit and restraint**, not chrome.

**Founder's Advocate (agreeing, sharpening):** Yes — and the default must read like
**Jon typed it.** The day a buyer can tell a first email was assembled by software, the
new-studio credibility is gone. Composable: yes. Looks-automated: never.

---

## 2. The medium problem — CTO (logistics)

**CTO:** Before anyone designs blocks, here is the hard constraint, because it bounds
everything (verified in the code):

- **Today the app sends *no* email.** "Compose email" is a `mailto:` (`outreach.py
  _mailto`) — it hands a draft to Jon's own mail client. That's actually *good* for
  deliverability and personal feel, but `mailto:` is **plain-text only**; you cannot
  reliably inject branded HTML through it. A "capabilities-doc-looking email" is
  **impossible via the current path.**
- **The Gmail integration is read-only.** `gmail_client.py` lists/reads/marks alert
  emails for triage — there is **no send**. Sending would need a new OAuth scope
  (re-mint Jon's token with `gmail.send`) plus a MIME composer.
- **No ESP/SMTP exists** (no SendGrid/Postmark/SES/smtplib anywhere).
- **HTML email is a hostile medium.** Clients strip `<style>`, **images are blocked by
  default**, **audio never plays inline**, and image-heavy cold mail is **spam-filter
  bait**. A doc that's stunning in a browser can render *broken* in Outlook and land in
  Promotions/Spam — actively *harming* the one-shot first impression.

So the real menu of ways to deliver "an awesome first touch" is four options, not one:

| Option | What it is | Richness | Deliverability / feel | Build cost |
|---|---|---|---|---|
| **A. Composable mailto** | Compose screen with on/off blocks → builds the **plain-text** draft into Jon's mail client | Text only (tasteful) | Best — sends from Jon's own inbox, reads personal | **~free** (reuses doc/override infra) |
| **B. Personal note + tailored page** | Short personal email with **one link** to a per-lead branded "first-touch page" (capabilities-doc-lite, the composable richness lives there) | High (on the page) | Email deliverable; richness is one *click* away | Low (reuses the doc renderer) |
| **C. Branded HTML send via Jon's Gmail** | Extend the Gmail integration with `send`; compose inlined-CSS HTML; **send from Jon's real address** | Medium-high (HTML, no audio) | Personal *from* address; HTML render risk | **Real build** (send scope, MIME-HTML, preview, image hosting) |
| **D. ESP blast (Postmark/SES)** | Send HTML from a system address | High | **Worst** — impersonal, cold-from-system, deliverability setup | Real build + ongoing |

**CTO's lean:** **A now, B next.** A ships the composer immediately with zero infra and
keeps the email personal. B gets the buyer the "awesome" without betting the first
impression on HTML-email rendering. **C** is viable *because we'd send from Jon's own
Gmail* (not a cold system blast) — but it's a genuine project. **D I'd reject** — a
system-address HTML blast is the one path that can make a new studio look like spam.

---

## 3. The composer design — CMO (lead)

**CMO:** Here's the design, modeled on the capabilities doc's toggle bar so it's
familiar. **Compose email** opens a **composer** (not a bare mailto): a left rail of
**on/off blocks**, a live preview on the right, and a send action at the bottom. Jon
toggles, the preview updates, he sends. His block choices **persist per deal** (reuse
the `doc_overrides` pattern), so a half-built draft survives.

**The block menu** (each toggleable; the ★ are on by default):
- ★ **Warm opener** — greeting + one specific line about *their* brief (pulled from the
  lead, editable).
- ★ **What we understand you need** — the one-line client-facing synopsis (same source
  as the doc's understanding line).
- ★ **One relevant track** — *the* single best-fit example, named for their brief
  (link/▶ in HTML; "happy to send" mention in plain text). *Restraint: one, not a reel.*
- ○ **A second/third example** — for when more proof helps.
- ★ **The call offer** — the reworded excerpt: examples attached, opening links from a
  stranger isn't always ideal, happy to walk you through on a short call.
- ○ **Credibility line** — "original & cleared, fixed scope, vetted craft team" (one
  line, only if it earns its place).
- ○ **Tailored page link** — the single low-pressure "see a 90-second page built for
  your brief" link (Option B).
- ★ **Personal sign-off** — Jon's name/role, reads hand-typed.
- ○ **P.S.** — the highest-read line in any email; a single tailored offer.

Plus **"+ write your own block"** and the existing support-chip library, so the
composer and the doc share one vocabulary.

**Head of Production:** The example block is the make-or-break. In *plain text* it's a
named mention + a link Jon can paste; in *HTML/page* it's a branded player. Either way
the rule is **one perfect, relevant piece first** — a wall of tracks reads as a
catalog, not a craftsman. Tie the choice to the lead's discipline (we already do this
in `recommended_examples`).

---

## 4. The fight: richness vs. the one-shot impression

**CMO:** I'll push for **B as the real answer**, not just A. A composable *text* email
is a fine cleanup, but it doesn't deliver the "awesome" the founder is asking for — a
tasteful, personalized **page** does, and it's where players, the brief synopsis, and a
soft CTA can actually shine without HTML-email roulette.

**CRO (dissent — friction):** Careful. The email *itself* already says *"opening links
from an unfamiliar sender isn't always ideal."* If our big idea is **a link**, we're
leaning on the exact behavior we just acknowledged people resist. Cold-open reply rates
live and die on **low friction and relevance**, not destinations. I'd make the page a
**bonus**, never the payload: the email must stand on its own (relevant track mention +
call offer), and the page is for the curious minority. Measure reply rate before
assuming the page lifts anything.

**Founder's Advocate (dissent — humanity):** Both of you are over-building the *first*
sentence of a relationship. The most awesome cold email a new studio can send is a
**short, specific, obviously-human** note that proves you read their brief. A composer
that *helps Jon do that fast* is great. A composer that tempts him to stuff in a
credibility line, two tracks, a page link, and a P.S. will produce a **worse**, busier
email. Bias the defaults to **minimal**; make richness opt-in; never let it look
assembled.

**CTO (logistics check on B vs C):** If Jon wants the richness *in the inbox* (no
click), that's **C — and only acceptable because it sends from his own Gmail**, which
keeps it personal and deliverable. But C inherits HTML-email limits: **no inline
audio** (tracks become play-links/thumbnails to the page anyway), image hosting +
inlined CSS, and per-client rendering tests. So even C ends up **pointing at the page**
for the actual listening. That argues for building **B's page first regardless** — it's
the shared asset under both B and C.

**CFO:** Scope discipline. **A is hours. B is days** (a new per-lead page route +
composer UI, both reusing the doc renderer). **C is a sprint** (Gmail send scope, MIME-
HTML, preview, deliverability care). Don't authorize C until B's page exists and proves
buyers engage — otherwise we build inbox-HTML plumbing to deliver a page we haven't
validated.

---

## 5. The synthesis the cabinet converged on

Despite the disagreements, a sequence emerged that satisfies the founder's "just as
awesome" without betting the first impression on a fragile medium:

1. **Build the composer** (CMO's block menu) over the existing override/chip infra —
   this is the founder's literal ask ("elements I can click on or off").
2. **Default it to send via the composable mailto (Option A)** — personal, from Jon's
   own outbox, zero infra, ships now. Defaults **minimal** (Founder's Advocate).
3. **Build the per-lead "first-touch page" (Option B)** as the shared rich asset — a
   capabilities-doc-lite framed as an intro — and let the composer optionally include
   **one** low-pressure link to it (CRO: bonus, not payload).
4. **Hold Option C (HTML send via Jon's Gmail) as a fast-follow**, authorized only if
   the page (B) shows buyers actually engage — and even then it *points at* the page for
   audio. **Reject Option D (ESP blast)** outright.

The awesomeness the founder wants is delivered by **(1)+(3)**: composable relevance in
the email, a stunning tailored page one optional click away — without risking the one
shot on HTML-email rendering.

---

## Decisions for the founder (Jon decides — cabinet recommendation in *italics*)

1. **Replace bare "Compose email" with a block composer?** *Recommend **yes** —
   on/off blocks + live preview + persisted per-deal choices, sharing the doc's chip
   vocabulary.* — Confirm.
2. **The block menu (§3).** *Recommend the starred defaults (warm opener, understanding
   line, one relevant track, call offer, sign-off) with the rest opt-in, defaults
   minimal.* — **Review the block list; star/unstar any.**
3. **★ Delivery mechanism — the real fork.** Options, not mutually exclusive:
   - **A. Composable plain-text mailto** *(recommend as the immediate ship — personal,
     free, from your own inbox).*
   - **B. Personal email + one link to a tailored "first-touch page"** *(recommend as
     the rich layer — the "awesome" without HTML-email risk).*
   - **C. Branded HTML email sent via your Gmail** *(recommend deferring until B proves
     engagement; needs a new Gmail send scope + real build).*
   - **D. ESP/system-address blast** *(recommend reject — spam/impersonal risk to the
     one-shot impression).*
   — **Your call: A now + B next (rec.) / push straight to C / A only.**
4. **How rich is the default email?** *Recommend **minimal-by-default**, richness opt-in
   per send (Founder's Advocate + CRO), measured by reply rate.* — Confirm.
5. **The tailored-page link — payload or bonus?** *Recommend **bonus** — the email must
   stand on its own; the page is for the curious (CRO).* — Confirm.

Build order if greenlit: **composer + Option A (ship) → first-touch page (Option B) →
measure reply/engagement → decide on C (Gmail HTML send).**

*Logistics note for the build (CTO): the composer and page reuse the capabilities-doc
renderer + `doc_overrides`; Option A is a body-builder over the existing `_mailto`;
Option C, if authorized, requires re-minting Jon's Gmail token with a send scope, a
MIME-HTML composer with inlined CSS and hosted images, and a per-client render pass —
and still links out to the page for audio.*
