# Sonic Signature — sell-by-hand playbook

*Decision: sell the first deals fully by hand before building a self-serve offer page.
This is the one-pager to run a conversation from, and the exact steps to turn a "yes"
into a collected dollar on `/revenue`. Prices below are a recommended anchor — change
them to whatever you'll actually charge.*

---

## The offer (one productized thing, fixed)

**Sonic Signature** — an original sonic logo / mnemonic for a brand.

- **What they get:** a 3–5 second original sound signature (the audio "logo"), in the
  formats they need, **+ 2 revision rounds, + a signed clearance certificate, + a cue
  sheet, + an organized delivery package** in a review portal.
- **Why it's the first offer:** small, concrete, brand-owned forever, fast to fulfill
  with the roster we have, and an easy first "yes." Ship one perfectly → it becomes the
  case study that sells the next ten.
- **Timeline:** ~2–3 weeks from deposit to delivery.
- **Recommended price:** **$4,500 list** · **$2,950 founding rate** (first 1–3 clients,
  in exchange for a named, client-approved case study + a reference call). Paid, never
  free. *(Anchor — set your own number.)*
- **Terms:** **50% deposit to start** (non-refundable once work begins), balance on
  delivery / before final files are downloaded (the payment gate enforces this).

---

## Who you're selling to, and the pain

**Buyer:** an **agency producer, brand content lead, or business-affairs / marketing
ops** person — not "a brand that wants a song."

**Their pain (lead with this, not "music"):**
- **Rights risk** — library tracks with murky clearance, or a freelancer who hands over a
  bare mp3 with no paperwork. Legal flags it; the campaign stalls.
- **Delivery chaos** — chasing files, formats, versions, and "is this actually cleared?"

**The line:**
> *"We make original, rights-clean music and hand it over the way a procurement team wants
> it — a signed clearance certificate, a cue sheet, organized files, and a review portal.
> So your legal team never flags it and you never chase a file. The music's the easy part;
> the certainty is what you're buying."*

We sell **risk reduced + a painless process.** The music rides along. (Honesty: say
"documented, original, delivery-ready," not "litigation-proof.")

---

## The conversation (keep it short)

1. **Open on their world, not ours:** "How do you usually source music for a spot — and
   what happens when legal asks if it's cleared?"
2. **Name the pain back to them:** rights risk + file/version chaos.
3. **Offer the one thing:** the Sonic Signature, fixed scope + price + timeline.
4. **Always close on one of three asks** — never "let's stay in touch":
   - *Book a scoped 20-min call,* or
   - *Send a fixed written offer,* or
   - *Collect the deposit and start.*

**Objections:**
- *"Too expensive."* → It's brand-owned forever and clears legal once; compare it to a
  re-license or a takedown. (Or offer the founding rate.)
- *"We use a library."* → Great for filler; this is your *owned* signature, with the
  paperwork your legal team wants.
- *"Send me info."* → "I'll send a one-page offer — if the scope and price work, the next
  step is a 50% deposit and we start." (A specific next step, not a brochure.)

---

## The weekly motion (founder-run)

- **A named list of 30** agency producers / brand content leads — start with your 1st- and
  2nd-degree network (the first yes lives there).
- **10 real conversations / week** (calls or DMs that lead to an offer — not blasts).
- **Sell ONE founding client, deliver it flawlessly, turn it into the case study, then
  open the next two.** Don't sell three you can't deliver at once.
- Track the funnel on **`/revenue`** — qualified → proposal → deposit → delivered → paid.

---

## Turn a "yes" into cash on the dashboard (exact steps)

Everything below already exists in the app — no new tooling needed.

1. **Create the deal.** Add it as an opportunity (or straight to a project): **Talent/Match
   isn't needed yet** — make the **Project** (client + the Signature as the need).
2. **Generate the proposal.** On the project → **Proposal** → it builds the deterministic
   doc from the estimate (set the price to your number). Mark it **Sent**, then **Accepted**
   when they say yes.
3. **Invoice the deposit.** On the project → create the **Deposit** invoice (50%) → mark it
   **Issued**.
4. **Collect the dollar — two honest ways:**
   - **Stripe:** if `CHORDENTIAL_PAYMENT_PROVIDER=stripe` is configured, use the invoice's
     **checkout link** and send it; it marks Paid automatically on payment.
   - **Off-platform:** take Zelle/ACH/wire, then **mark the invoice Paid** by hand.
5. **It's now real revenue.** The deposit shows on **`/revenue`** under *cash collected*,
   and the **payment gate** keeps the final deliverables locked until the balance is paid.
6. **Deliver through the OS.** Assign the composer → they submit versions in the composer
   portal → you review/approve → the client reviews in the delivery portal → mark the
   **Final** invoice Paid → downloads unlock → pay the composer on **`/payouts`**.

That's the whole loop: **conversation → proposal → deposit → delivery → paid in full →
crew paid → a case study.** Run it once for real, and we have our proof.
