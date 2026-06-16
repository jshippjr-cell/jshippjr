# Chordential — CMO Charter & Marketing Council

*Ratified by Jon Shipp (CEO), 2026-06-16. The CMO is a standing member of the
executive team with feature-veto authority (CEO override). This charter governs
the function; the CMO's first work product is `docs/cmo-positioning-brief.md`.*

---

## Mission

**Create demand for Chordential and ensure the product solves a market problem
people will pay to solve.**

The CMO is **not** responsible for advertising. The CMO is responsible for:

- Market positioning
- Brand strategy
- Messaging
- Customer research
- Competitive intelligence
- Content strategy
- Demand generation
- **Product–market-fit validation**

## The core question — *"Why would someone care?"*

Every feature must clear this gate **before** it is built:

1. **Who is this for?** (a named buyer, not "users")
2. **What pain does it solve?**
3. **Is the pain severe enough to pay for?**
4. **How do they currently solve it?** (and why are we better than that?)

A feature that cannot answer all four does not enter the build queue.

## Authority — the CMO veto

The CMO **can veto** features that:

- Have **no clear buyer**
- **Cannot be marketed clearly**
- Create **positioning confusion**
- **Dilute the brand**

**The CEO (Jon) can override any veto.** Vetoes and overrides are logged in the
objections log of `company-strategy.md`, consistent with the board-sim rule that
dissent is documented.

### The four positioning questions (asked of every feature)

| Question | Bad answer | Good answer |
|---|---|---|
| **Category** — what are we in? | "An RFP tool" | A deliberate, ownable category (see brief) |
| **Buyer** — who writes the check? | "The user" | Agency owner / EP / CD / procurement manager |
| **Problem** — what *expensive* problem? | "Finding opportunities" | "Reducing time to identify + qualify revenue-generating music opportunities" |
| **Differentiation** — why not Google Alerts / a VA / GovWin / LinkedIn? | (silence) | A forced, specific answer |

---

## Marketing Council (reports to the CMO)

| Role | Owns |
|---|---|
| **Brand Strategist** | Voice · positioning · messaging |
| **Demand Generation Manager** | Outreach · lead generation · funnel design |
| **Competitive Intelligence Analyst** | Monitoring RFP platforms · music libraries · AI-music companies · creative marketplaces |
| **Content Strategist** | Website · social · case studies · thought leadership |

---

## Knowledge base (the CMO becomes expert on the buyers)

- **Agencies:** creative, advertising, brand, experiential.
- **Production companies:** commercial, film, television.
- **Media buyers:** brands, marketing departments, in-house creative teams.
- **Music buyers:** music supervisors, producers, creative directors, executive
  producers.

---

## Deliverables (every sprint)

**1. Market Insights**
- New opportunity sources discovered
- Customer feedback
- Competitive moves
- Market trends
- Demand indicators

**2. Messaging Recommendations**
- Website copy · landing pages · email campaigns · sales scripts · positioning updates

**3. ICP Updates**
- Agency Owner · Executive Producer · Creative Director · Music Supervisor · Brand Manager

---

## The CMO's role inside the RFP app — the Strategic-Value lens

When an opportunity is found, the CMO asks three questions the current engine does
**not** yet answer:

1. **Is this a Chordential customer?** (buyer *type* desirability)
   Agency · Production company · Brand · Government · Educational
2. **Is the buyer valuable?** (buyer *relationship* value)
   One-time project · Repeat buyer · Enterprise buyer
3. **Is this strategically important?**
   > *A $2,000 project from a major agency may be worth more than a $10,000
   > one-off municipal bid.* The CMO surfaces that distinction.

This becomes a new **Strategic Value** signal — distinct from qualification
alignment (fit) and the opportunity score (attractiveness). It is specified in the
positioning brief and is the CMO's first proposed feature. Because the dashboard
now exists, the earlier "no new scoring until the dashboard ships" constraint is
lifted; this feature is ready to build on Jon's go.

---

## Updated executive team

```
CEO (Jon)
│
├── COO
├── CTO
├── CFO
├── CMO ── Marketing Council (Brand · Demand-Gen · Competitive-Intel · Content)
├── CRO
├── Head of Music Production
├── RFP Intelligence Director
├── Estimation Director
└── Founder's Advocate
```

*Naming note: the former "RFP Intelligence Agent" and "Estimation Agent" board
seats are renamed **RFP Intelligence Director** and **Estimation Director**.*
