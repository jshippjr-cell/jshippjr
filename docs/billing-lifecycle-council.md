# Billing & Payments Lifecycle Council — Capabilities PDF → Cash in the Bank

*Board simulation. **CFO leads** (per CEO directive). The question: design the
end-to-end money lifecycle — invoice, collect a deposit, track the remaining
balance per project, dun unpaid balances, collect payment, and land funds in
Jon's bank — on **Stripe**, with a great customer experience. Agents are required
to disagree; **consensus is explicitly not the goal**; the CEO ratifies.*

Date: 2026-06-23.

---

## What already exists (don't rebuild it)

The architecture was scaffolded for exactly this; the council builds on it:

| Layer | Status | Where |
|---|---|---|
| Proposal with `total_price`, `deposit_pct`, `deposit_amount`, `balance_due` | ✅ built | `proposals.py` |
| Deterministic invoice builder (Deposit = deposit_amount, Final = balance_due) | ✅ built | `invoicing.py::build_invoice` |
| `invoices` table: `kind`, `status` (Draft/Issued/Paid), `amount`, `external_ref`, `paid_at` | ✅ built | `web/db.py` |
| Routes: create invoice, create checkout, set status; auto-draft Final on delivery | ✅ built | `web/app.py` |
| **Payment provider seam**: `PaymentProvider.create_checkout()` / `handle_webhook()`, Null + **Stripe stub** | ✅ built (Stripe = stub) | `payments/` |

**The gap:** Stripe is a stub (`create_checkout`/`handle_webhook` raise `NotImplementedError`); there's no webhook route, no balance rollup across invoices, no reminders, and the front of the funnel (capabilities PDF → accept → pay) isn't connected to a real pay link. That gap is what this council scopes.

---

## The proposed lifecycle (the flowthrough)

```
 ┌────────────┐   ┌────────────┐   ┌──────────────┐   ┌───────────────┐
 │ 1. SEND    │   │ 2. ACCEPT  │   │ 3. DEPOSIT   │   │ 4. PAY DEPOSIT│
 │ Capabilities│→ │ Client     │→ │ invoice auto-│→ │ Stripe hosted │
 │ PDF + price │   │ accepts →  │   │ created      │   │ checkout      │
 │ band        │   │ proposal   │   │ (deposit_amt)│   │ (card/wallet) │
 └────────────┘   │ LOCKED     │   └──────────────┘   └───────┬───────┘
                  └────────────┘                              │ webhook
                                                              ▼
 ┌────────────┐   ┌──────────────┐   ┌──────────────┐   ┌───────────────┐
 │ 8. PAYOUT  │   │ 7. PAID FULL │   │ 6. REMINDERS │   │ 5. WORK BEGINS│
 │ Stripe pays│ ← │ Final invoice│ ← │ auto dunning │ ← │ deposit clears│
 │ bank (auto,│   │ paid → proj  │   │ on balance   │   │ → kickoff;    │
 │ T+2 daily) │   │ closed       │   │ due/overdue  │   │ milestones    │
 └────────────┘   └──────────────┘   └──────────────┘   └──────┬────────┘
                                                               │ on delivery
                                                               ▼ Final invoice
```

| # | Stage | Trigger | System action | Customer sees |
|---|---|---|---|---|
| 1 | **Send** | Jon sends capabilities/proposal | price band on the doc | A branded doc + "Approve & start" |
| 2 | **Accept** | Client approves | proposal locked; deposit/balance computed | One-click accept, no login |
| 3 | **Deposit invoice** | acceptance | auto-create Deposit invoice | — |
| 4 | **Pay deposit** | client clicks pay | Stripe Checkout session created | Hosted, branded pay page; Apple/Google Pay; instant receipt |
| 5 | **Work begins** | deposit webhook = paid | project → Active (gated on deposit) | "Deposit received — we're starting" email |
| 6 | **Track + remind** | balance outstanding | balance rollup; scheduled reminders | Friendly "balance due" emails w/ pay link |
| 7 | **Final + paid** | delivery → Final invoice paid | invoices reconcile to proposal; project closed | Final pay page + receipt; "paid in full" |
| 8 | **Payout** | Stripe payout schedule | none (Stripe-native) | — (money lands in Jon's bank) |

---

## The deliberation

### Fork A — which Stripe product? (the central fight)

**CTO (opening):** Use **Stripe Invoicing**. Stripe hosts the invoice, sends it,
runs the **reminders/dunning for us**, hosts the pay page, emails receipts, and
reconciles — we write almost no code and inherit a best-in-class CX. Building our
own checkout + dunning is reinventing a solved problem.

**CFO (lead, pushes back):** I want Stripe Invoicing's *muscle* but not its *brain*.
Our deposit/milestone/balance logic is already deterministic and lives in our DB —
**our DB must stay the source of truth**, reconciling to the proposal to the dollar.
If Stripe becomes the ledger we lose the clean reconciliation we built. My position:
**Stripe Checkout Sessions** per invoice (deposit, then balance), DB-authoritative,
Stripe as the rails — *or* Stripe Invoicing only if we treat its objects as a mirror
of our invoices, never the master.

**CMO:** I don't care which object — I care that the **buyer** experience is
frictionless and on-brand: a single "View & Pay" link, wallets enabled, no account,
instant receipt, and it *feels* like Chordential, not a generic Stripe page. Both
Invoicing and Checkout give a hosted page; pick whichever lets us **brand it** and
**send one durable link per project**.

**Founder's Advocate (dissents on scope):** You're all over-engineering for week one.
Jon needs to **get paid for the first deal now.** Start with a **Stripe Payment Link**
(literally create it in the dashboard, paste into the proposal email) — zero code,
money this week — and automate later. Don't let the perfect lifecycle delay the
first deposit.

**COO:** Whatever we pick, **reconciliation and dunning must be reliable** — a
silent failed webhook that leaves an invoice "Issued" forever is worse than no
automation. I lean to letting **Stripe own the reminder cadence** (their dunning is
battle-tested) rather than our scheduler chasing it.

> **No consensus.** CTO = Invoicing (Stripe owns dunning). CFO = Checkout, DB-
> authoritative. Founder's Advocate = Payment Links now, automate later. CMO =
> agnostic on object, adamant on brand + one link. COO = Stripe-owned dunning.

### Fork B — source of truth for the balance

**CFO:** Our DB. The proposal is the contract; invoices reconcile to it; Stripe is a
payment rail whose webhooks *update* our records. **Decided position: DB-authoritative.**
**CTO (concedes partially):** Fine, *if* we add an idempotent webhook + a reconcile
job that catches missed events, or we'll drift from Stripe. — *Accepted as a
requirement.*

### Fork C — dunning/reminders: Stripe-native vs our scheduler

**COO + CTO:** Stripe-native (Invoicing) — proven, less to maintain.
**CFO:** We already run a scheduler (`web/scheduler.py`); a branded reminder from
*us* ("Hi — balance of $X due for [project]") converts better and keeps the
relationship ours, not Stripe's. **CFO leans our scheduler, branded, with a
Stripe-hosted pay link inside.** — *Unresolved; CEO to break.*

### Fork D — who eats Stripe's fee (2.9% + 30¢)?

**CFO:** On a $2.5k–$15k deal, ~$75–$440 in card fees. Options: (a) **absorb** it
(cleanest CX), (b) **surcharge** cards, (c) **offer ACH/bank-debit** (0.8%, capped
$5) as the default for larger balances and absorb the small fee.
**CMO (hard line):** **Never surcharge** — it sours the closing moment. Absorb on
deposits; **steer big balances to ACH** to cut the fee.
**CFO (agrees, reluctantly):** Accept — price the fee into the quote instead of
surcharging. ACH for the balance on deals > $5k.

### Fork E — Stripe **standard** vs **Connect**

**CFO + CTO (agree):** **Standard Stripe account** now — Jon is the merchant, funds
pay out to *his* bank. **Connect** is a Phase-C marketplace concern (paying third-
party composers / taking a take-rate) — explicitly **out of scope** today. No dissent.

### Fork F — deposit timing & refundability

**Head of Production:** **No work starts until the deposit clears** — the deposit is
the commitment gate. Non-refundable once work begins; refundable (minus fees) if we
haven't started. **CFO:** Agreed; 50% default deposit (already in the proposal),
balance due on delivery, net-7. — *Agreed.*

---

## CFO synthesis

The disagreements collapse to **two real decisions**; the rest is sequencing:

1. **Stripe object:** I'm not going to let us choose *Invoicing-as-ledger* — our
   DB stays authoritative (Fork B, settled). Between Checkout and Invoicing for the
   *rails*, the deciding factor is **dunning** (Fork C). If we want Stripe to own
   reminders, use **Invoicing**; if we want branded reminders we control, use
   **Checkout/Payment Links** + our scheduler.
2. **Speed vs polish:** the Founder's Advocate is right that the first deposit
   shouldn't wait on the full build. **Phase it.**

My recommendation: **phase it, Checkout-based, DB-authoritative, branded dunning** —
but I'm handing the dunning tie (Fork C) to the CEO.

---

## CEO ruling

> **Approved, with the Fork-C tie broken toward _our_ branded reminders.** Rationale:
> the relationship is the asset (consistent with the moat thesis) — a "balance due"
> note from Chordential, with a one-click Stripe pay link inside, keeps the
> relationship ours and converts better than a generic Stripe dunning email. DB
> stays the source of truth. Standard Stripe account, no Connect. Absorb fees, steer
> big balances to ACH, never surcharge. **And ship the Founder's Advocate's Phase 0
> first** — a Payment Link so Jon can take a deposit this week — then automate.
> Build it in the phases below.

---

## Ratified architecture & roadmap

**Principles:** DB-authoritative (reconcile to the proposal to the dollar) · Stripe
is the rail, not the ledger · idempotent webhooks + a reconcile sweep · branded,
relationship-owned reminders · absorb fees / ACH for big balances / never surcharge ·
standard account now, Connect deferred to Phase C.

**Phase 0 — get paid this week (no code).** Jon creates a Stripe account + a Payment
Link; paste it into the proposal/capabilities email. Money flows; we learn. *(Only
manual step: Jon opens the Stripe account + connects his bank.)*

**Phase 1 — wire Stripe Checkout into the existing seam.** Implement
`StripePaymentProvider.create_checkout(invoice)` (hosted Checkout Session, wallets on,
success/cancel URLs, `client_reference_id = invoice id`) and a **`POST /webhooks/stripe`**
route → `handle_webhook()` that, idempotently, marks the invoice `Paid` + sets
`paid_at` on `checkout.session.completed` / `payment_intent.succeeded`. Set
`CHORDENTIAL_PAYMENT_PROVIDER=stripe`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`,
`CHORDENTIAL_PUBLIC_DOMAIN`. *Only file that changes is `payments/stripe.py` + one route.*

**Phase 2 — balance tracking + the customer "View & Pay" page.** A per-project rollup
(`total`, `paid`, `remaining`) summing invoices against the proposal; a single durable,
login-free **/pay/{token}** page showing status + the live pay button (great CX, one
link for the whole engagement).

**Phase 3 — branded dunning.** Extend `web/scheduler.py`: when a balance is outstanding,
send escalating branded emails (T-3 "due soon" → due → T+3/T+7 "overdue"), each with the
pay link; stop on Paid. A nightly **reconcile sweep** re-checks Stripe for any invoice
stuck `Issued` (webhook-miss safety net).

**Phase 4 (later) — ACH + receipts polish + Connect (Phase C only).** Enable ACH/bank-
debit for balances > $5k; branded receipts; revisit Stripe **Connect** only when paying
third-party composers / taking a take-rate.

**Payout to bank:** no code — Stripe pays out collected funds (minus fees) to Jon's
connected bank on the standard rolling schedule (≈ T+2, daily). That *is* "deposit into
my account."

---

## Open questions for the CEO

1. **Deposit %** — keep 50% default, or 30% for larger/strategic deals?
2. **Terms** — balance **net-7 on delivery**, or due-on-delivery?
3. **ACH threshold** — steer to ACH above **$5k**, or always offer both?
4. **Phase 0 now?** — want me to write the one-page "open Stripe + make a Payment
   Link" runbook so you can take a deposit before any code ships?
