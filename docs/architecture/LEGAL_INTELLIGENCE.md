# Legal Intelligence — the fifth Intelligence domain and the Rights Engine

**Status:** Architecture proposal. NOT yet ratified as an ADR. **Nothing in the clause
library ships until retained counsel reviews and approves it.** This document is written
in the voice of a senior entertainment/IP attorney to be *reviewed by* a licensed attorney
— it is architecture and informed recommendation, not legal advice, and it does not create
an attorney–client relationship.

**Author lens:** commercial-music / advertising / work-for-hire / publishing / PRO / IP
transactions. The job here is not to draft contracts — it is to architect the legal
operating system so an attorney can later drop in clause text without touching the engine.

---

## 0. The five legal truths this architecture is built on

Everything below pivots on five facts about US commercial-music law. They are load-bearing;
the engine encodes them as rules. Each is grounded in an authoritative source (§9).

1. **Work-for-hire is fragile for independent contractors.** Under 17 U.S.C. §101(2), a
   *commissioned* work can be "made for hire" only if it is a written agreement **and** the
   work falls into one of **nine enumerated categories**. A stand-alone musical composition
   is **not** one of them. **But** music created as "a part of a motion picture or other
   audiovisual work" *is* category 2 — and a TV/video/social spot is an audiovisual work.
   → **Medium decides whether WFH is even legally available.** A jingle scored to a specific
   video spot may be valid WFH; a radio-only track, a streaming-audio ad, or a library cue
   generally is not.

2. **Work-for-hire triggers a California employment trap.** California Labor Code
   §3351.5(c) makes an **individual** who signs a WFH agreement a **statutory employee** —
   pulling in workers'-comp, unemployment-insurance, and payroll obligations, *regardless of
   contract language to the contrary.* (The 2020 AB5 amendment exempted musicians/composers
   from the ABC test, but §3351.5 is a **separate** hook and still bites WFH.) The section
   reaches **individuals, not entities.** → For an individual California composer, a WFH
   clause can accidentally make Chordential an *employer.* Mitigation: use **assignment**
   (not WFH), or contract through the composer's **loan-out entity** (LLC/corp).

3. **Assignment carries a 35-year reversion; work-for-hire does not.** Under 17 U.S.C.
   §203, a post-1977 assignment or license is **terminable by the author** ~35 years out
   (notice window 25–40 years). Works made for hire are **exempt** from termination. → The
   standard defensive structure is **belt-and-suspenders**: primary WFH *where valid* + a
   **backup assignment**, accepting the theoretical §203 reversion on the backup. For a
   commercial campaign, the work is commercially dead long before year 35 — the reversion is
   near-academic, but it must be a **recorded, conscious** decision, not an accident.

4. **Copyright requires human authorship; AI-*generated* material is not protectable.**
   The US Copyright Office's *Copyright and Artificial Intelligence, Part 2* (Jan 29, 2025)
   holds that human authorship is the "bedrock" of copyrightability: wholly AI-generated
   output is uncopyrightable; **prompts alone are insufficient** to make the user an author;
   AI used **as a tool** to assist a human creator is fine; and **only the human
   contributions** are protectable. → You cannot validly warrant "original human authorship"
   over an AI-generated bed. The **chain of title is only as strong as the human-authorship
   declaration.** AI disclosure is therefore not hygiene — it is a **validity gate.**

5. **Chain of title is a graph, not a document.** Every human who touched the work —
   composer, session players, vocalists, producer, mixer, engineer, plus any sample owner —
   is a potential rights-holder whose grant must be captured. A single missing vocalist
   release or uncleared sample **voids the "one clean commercial relationship"** the entire
   business model sells, and exposes Chordential's indemnity. The architecture's core job is
   to make shipping that impossible.

> **The through-line:** the business sells the *client* a single, clean, fully-cleared
> relationship. That cleanliness is manufactured on the *talent* side, one grant at a time.
> Legal Intelligence is the ledger that proves the manufacture happened; the Rights Engine is
> the inspector that refuses to ship until it did.

---

## 1. Legal Intelligence — the domain

The fifth Intelligence domain, built to the **same pattern** as Campaign / Relationship /
Commercial / Procurement Intelligence: a store of **facts**, each with provenance, that
**renderers** read and **engines** reason over. No document owns data; no document owns logic.

### 1.1 The Legal Fact

Every legal fact is the tuple the brief demanded, plus provenance:

```
LegalFact {
  scope        # WORK | PARTY | RELATIONSHIP  (see 1.2)
  scope_id     # which engagement / party / relationship
  facet        # Ownership | Parties&PRO | Grants | Structure | Warranties | Releases | Compliance | Signatures
  key          # e.g. "composition.owner", "writer.pro", "grant.territory", "warranty.ai_disclosure"
  value        # the asserted value (may be structured: split maps, date ranges…)
  source       # who/what asserted it: DECLARED | CONTRACTED | INFERRED | VERIFIED
  evidence     # URI to the signed doc / upload / registration that proves it (nullable)
  confidence   # LOW | MEDIUM | HIGH  (how sure are we the value is correct)
  status       # lifecycle, see 1.3
  timestamp    # when last changed
  owner        # the human accountable for this fact (operator, composer, counsel)
}
```

This mirrors the existing Campaign Intelligence facet×key×kind model with provenance — it is
**not a new invention**, it is CI generalized to legal facts. Reuse the CI store's shape
(`contribute` / `edit_or_create` / `fields_view`), don't fork it.

### 1.2 Scoping — facts anchor at three levels

- **WORK-level** (composition + master for one engagement): ownership, splits, WFH/assignment
  status, rights granted to the client, territory/term/media/exclusivity, Content-ID, samples,
  AI status. *These are born in the engagement and die with it.*
- **PARTY-level** (a composer/musician/vendor, persistent across engagements): PRO affiliation,
  IPI/CAE number, W-9, COI/insurance, NDA/MSA on file, portfolio permission, exclusivity
  commitments. *Captured once, reused on every future engagement* — exactly the Procurement
  Company-Profile pattern, generalized to talent.
- **RELATIONSHIP-level** (Chordential↔client, Chordential↔talent): MSA status, master terms,
  standing exclusivity.

This is the same anchoring discipline Campaign Intelligence already uses (anchored to the
Opportunity) and the talent layer already uses (party persistence). Do not re-collect a
composer's IPI on every job.

### 1.3 Status lifecycle — the engine's fuel

```
unknown → asserted → documented → verified → disputed → expired
```

The lifecycle is what makes the engine safe: **a Rights Certificate may not render ownership
from `asserted` facts** — it needs `documented` (a signed instrument exists as evidence) or
`verified` (evidence checked). This is the legal analog of "documented, not fabricated."

### 1.4 Facets (top-level groupings)

| Facet | Representative keys |
|---|---|
| **Ownership** | composition.owner, master.owner, publishing.owner, writer_share.owner, neighboring_rights.owner |
| **Parties & PRO** | writer.name, writer.pro (ASCAP/BMI/SESAC), writer.ipi_cae, publisher.name, publisher.ipi, split.map |
| **Grants** | grant.rights[], grant.territory, grant.media, grant.term, grant.exclusivity, grant.retained[] |
| **Structure** | engagement.medium, engagement.wfh_status, engagement.assignment_status, engagement.buyout_tier |
| **Warranties** | warranty.originality, warranty.samples, warranty.ai_disclosure, warranty.content_id |
| **Releases** | release.session_musicians[], release.vocalists[], release.producer, release.mixer, release.engineer |
| **Compliance** | compliance.coi, compliance.nda, compliance.msa, compliance.w9, compliance.conflict |
| **Signatures** | signature.outstanding[], signature.executed[], signature.evidence |

### 1.5 Legal Intelligence is *downstream* of the other domains

This is the key structural insight. Legal Intelligence does not re-ask what the other domains
already know — it **consumes** them:

- **Campaign Intelligence** already knows the **medium, territory, term** the client needs
  (discovered on the call).
- **Commercial Intelligence** already knows the **buyout tier** the client *paid for*.
- **Procurement Intelligence** already knows **vendor compliance** (W-9, COI) — much of which
  is the same party-level compliance Legal needs.

A rights fact like *"client receives perpetual worldwide all-media buyout"* is **half
Commercial** (what they bought) and **half Legal** (what was actually granted, and what *can*
be granted given the talent agreements). The Rights Engine **reconciles the two** — and its
single most valuable output is catching the case where **the client was sold rights the talent
chain does not actually convey.** That reconciliation is the crown jewel of the whole system.

---

## 2. The Rights Engine

A **deterministic resolver** — no LLM, no generation, like every other ChordOS engine ("the
machine proposes, Jon disposes"). Input: an engagement's Legal Intelligence facts (plus the
CI/Commercial facts it reconciles against). Output: a **resolved rights determination** and,
more importantly, a **blocking gap list.**

### 2.1 What it determines

For any engagement it computes, deterministically:

- composition owner · master owner · publishing owner · writer's-share owner · neighboring-rights owner
- PRO income recipient(s)
- the rights the client receives (media × territory × term × exclusivity)
- Content-ID permitted? (only if no conflicting registration exists and the buyout permits it)
- exclusivity present? (two axes — see 3.x)
- samples present → cleared?
- AI disclosure required? sufficient?
- **additional agreements required** (the gap list)

### 2.2 It is a function of the ENGAGEMENT MODEL

Two variables drive everything:

1. **Medium** (audiovisual spot vs audio-only vs library) → whether **WFH is legally
   available** at all (truth #1).
2. **Buyout tier** the client purchased (from Commercial Intelligence) → what rights **must**
   flow to the client.

From those two plus the party facts, the engine derives the required document set, the
ownership waterfall, and the reconciliation between "sold" and "grantable."

### 2.3 The output that matters: BLOCKS

The certificate is not the prize. The **blocking gap list** is:

- "Vocalist release missing — cannot warrant clean master."
- "Sample detected in stems, no clearance on file — originality warranty is false."
- "AI bed declared, no human-authorship attestation — composition may be uncopyrightable;
  cannot warrant originality." (truth #4)
- "Client purchased *worldwide perpetual all-media*; composer agreement grants *North America,
  3-year, broadcast-only* — **rights shortfall of X**." (the crown-jewel reconciliation)

**Wire this into the delivery gate you already built.** No package assembles / no download
unlocks until the Rights Engine returns **green** — the legal twin of the
delivery-completeness gate. Legal cleanliness becomes a *ship condition*, not a hope.

### 2.4 Ownership defaults by engagement type (the recommendation matrix)

| Engagement | Comp owner | Master owner | Publishing | Writer's share | Instrument | Why |
|---|---|---|---|---|---|---|
| **Audiovisual spot** (TV/video/social) | Chordential | Chordential | Chordential (publisher's share) | **Composer retains** | **Assignment + WFH recital** | WFH *available* (cat. 2) but assignment is safer vs CA trap; recital preserves WFH fallback |
| **Audio-only ad** (radio / streaming audio) | Chordential | Chordential | Chordential | **Composer retains** | **Assignment** (WFH invalid here) | Not an audiovisual work → WFH unavailable (truth #1) |
| **Library / catalog cue** | Chordential | Chordential | Chordential | Composer retains + royalty | **Assignment / exclusive license** | No single commission; buyout or license model |
| **Individual CA composer, any medium** | Chordential | Chordential | Chordential | Composer retains | **Assignment (never bare WFH)** | Avoid §3351.5 statutory-employee trap (truth #2) |
| **Loan-out entity** | Chordential | Chordential | Chordential | Entity/composer | WFH *or* assignment | §3351.5 reaches individuals, not entities |

> **Headline recommendation (challenging the likely default): make ASSIGNMENT the primary
> instrument with a WFH recital, not WFH primary.** See §7.

---

## 3. Talent lifecycle architecture

```
Source → Qualify → Onboard → Engage → Produce → Clear → Deliver → Steward
```

- **Source / Qualify** — existing recruiting pipeline.
- **Onboard (PARTY-level compliance, once):** W-9, IPI/CAE, PRO affiliation, COI/insurance,
  NDA, MSA. Reuses Procurement's vendor-onboarding machinery — a composer *is* a vendor.
- **Engage (WORK-level):** composer agreement (assignment + WFH recital + backup), split
  scope, deliverable scope, buyout tier flowed down from Commercial Intelligence.
- **Produce:** revisions inherit the same grant; **the engine watches for NEW contributors**
  introduced mid-revision (a session player added in v3) who need their own grant.
- **Clear:** session-musician releases, vocalist/performer releases, producer/mixer/engineer
  grants, originality + sample + AI declarations.
- **Deliver:** Rights Engine must be green (§2.3).
- **Steward:** portfolio permission windows, exclusivity windows, PRO/cue-sheet registration,
  and a **reversion calendar** (§203 dates recorded at signing).

### 3.1 Recommendations — answering the 18 talent questions

- **When WFH:** only when the medium is **audiovisual** *and* the contractor is **not an
  individual CA resident** (or contracts via a loan-out). Then category-2 WFH is valid and
  dodges §203. **Always pair with a backup assignment.**
- **When assignment:** audio-only/radio/streaming-audio/library (WFH unavailable); **any**
  individual CA composer (avoid §3351.5); or any doubt. Assignment always works; accept §203.
- **Should Chordential own publishing?** **Yes** — own the copyright + **publisher's share** +
  100% sync control. The buyout model requires clean, unilateral sync authority.
- **Should Chordential own masters?** **Yes** — it is the producer/commissioner and the
  client's buyout depends on it.
- **Should composers retain writer's share?** **Recommend: yes.** On a pure US-broadcast buyout
  there is usually **no performance income anyway** (§3.2), so it costs Chordential nothing —
  yet it is a powerful talent-attraction and retention lever, and it is what the best houses do.
  Where the content has a genuine performance afterlife (YouTube series, film, international),
  the retained writer's share becomes a real, deserved composer upside. Structure: **Chordential
  = copyright + publisher's share + sync control; composer = writer's share of any PRO
  performance income.**
- **PRO registration / cue sheets:** register works and capture IPI/CAE at onboarding, but set
  expectations — **US broadcast commercials historically generate little/no PRO performance
  income** (ad music is a buyout market). Cue sheets matter mainly when the music airs as
  *programming* or **internationally.**
- **Split sheets:** required whenever there is **more than one writer**; capture at **production**
  time, not delivery.
- **Revisions & ownership:** the original grant carries; a **new contributor** in a revision
  needs a **new grant** — the engine must detect and block on this.
- **Buyouts:** model as **tiers** (media × territory × term × exclusivity) in Commercial
  Intelligence; the engine maps tier → required grants.
- **Soundtrack / sync rights:** flow from publishing ownership + the buyout tier; Chordential's
  sync control makes these clean to grant.
- **Promotional / portfolio usage:** default-grant the composer a **non-exclusive portfolio /
  demo-reel license** (carve-out) — unless a client exclusivity term forbids it; the engine
  resolves that conflict rather than the operator guessing.
- **Exclusivity — two axes:** (a) the client's exclusivity *in the music* (can the track be
  resold?); (b) the composer's exclusivity *to Chordential* (can they score a competitor?).
  Both are facts, tracked separately.
- **AI-assisted compositions:** **mandatory disclosure + warranty.** If AI-*generated* (not
  merely assisted), flag the uncopyrightable-bed risk (truth #4) → the originality warranty
  cannot stand → **block.** AI-*assisted* with real human authorship → allowed, disclosed.
- **Required vs good-practice documents:** see §4.4.
- **Risks:** see §8. **How the best houses handle it:** assignment-default, publishing control,
  writer's-share goodwill, rigorous release collection, and a hard clearance gate before delivery.

### 3.2 The buyout / PRO reality (set expectations honestly)

US broadcast advertising is predominantly a **buyout** market: the advertiser pays once for
broad rights and expects no back-end. Performance royalties that flow through PROs for
*commercials aired as advertising* are historically thin to nonexistent in the US. This is
**why retaining the composer's writer's share costs Chordential little** — and why the honest
posture with talent is "you keep your writer's share; on most spots it pays nothing, but on the
ones with an afterlife it's real and it's yours."

---

## 4. Document taxonomy

Reorganized around one principle the taxonomy **must** encode:

> **Contracts create facts. Certificates render facts. Forms collect facts.**
> A Composer Agreement is an **input** (it *creates* ownership facts). A Rights Certificate is
> an **output** (it *renders* them). Same rendering engine, **opposite data-flow direction.**

Each document is typed `CONTRACT` (bilateral, signed) · `CERTIFICATE` (unilateral attestation) ·
`FORM` (data collection), and mapped to the Intelligence domain that feeds it.

### 4.1 CLIENT
| Doc | Type | Fed by |
|---|---|---|
| Proposal · Campaign Brief · Commercial Review | render | Campaign / Commercial Intel |
| Statement of Work · Change Order | CONTRACT | Commercial Intel |
| Master Services Agreement | CONTRACT | Relationship Intel |
| Creative Approval · Final Acceptance | CERTIFICATE | Production (delivery gate) |
| Rights Certificate · Cue Sheet · Delivery Manifest | CERTIFICATE | **Legal Intel** |
| Invoice · Receipt | render | Commercial Intel |

### 4.2 TALENT
| Doc | Type | Creates/collects |
|---|---|---|
| Composer / Independent-Contractor / Work-for-Hire / Copyright-Assignment Agreement | CONTRACT | ownership, WFH/assignment status, grants |
| Producer / Mixer / Engineer / Sound-Designer Agreement | CONTRACT | contributor grants |
| Musician Agreement · Vocal Release · Performer Release | CONTRACT/RELEASE | neighboring rights, master cleanliness |
| Split Sheet | FORM→CONTRACT | split.map, writer info |
| Portfolio License · Credit Agreement | CONTRACT | portfolio permission, credit requirements |
| Originality Declaration · Sample Declaration · AI Disclosure | CERTIFICATE (by talent) | warranties |
| Confidentiality (NDA) · Conflict-of-Interest | CONTRACT/FORM | compliance |

### 4.3 PROCUREMENT
W-9 · ACH Authorization · Remittance Sheet · Vendor Packet/Profile · Company Overview ·
Insurance Certificate (COI) · Bank Verification · Compliance Docs · Vendor Registration Packet.
→ **Already largely built in Procurement Intelligence.** Legal reuses these as party-level
compliance facts; do not duplicate.

### 4.4 LEGAL (all CERTIFICATE — pure renders of Legal Intelligence)
Rights Certificate · Publishing Certificate · Ownership Certificate · Content-ID Declaration ·
Copyright Chain · Clearance Certificate · IP Assignment (this one is CONTRACT) · Licensing
Summary · PRO Registration Summary.

**Legally required vs good practice (the honest split):**
- **Required for a defensible chain of title:** signed composer agreement (assignment and/or
  valid WFH), signed releases from *every* performer on the master (session musicians,
  vocalists), sample clearances where samples exist.
- **Good practice (strongly recommended, not strictly required):** split sheets, originality
  declarations, AI disclosures, portfolio licenses, NDAs, COI. These convert "probably clean"
  into "provably clean" — which is the entire product promise, so treat them as required *by
  Chordential policy* even where not required *by law.*

---

## 5. Clause library architecture — the maintainability guarantee

The five-layer separation the brief demanded, made concrete. **This is the investment that
prevents future refactoring**: counsel can rewrite clause text forever without an engineer
touching the engine.

1. **Business logic** (engine, Python, tested, *zero legal text*): given engagement facts,
   *which documents and which clauses are required.*
2. **Legal logic** (rules, authored *with* counsel but stored as **data**): which clause
   **variant** applies given jurisdiction / medium / party-type. E.g. `CA + individual →
   assignment variant, not WFH variant`. A decision table mapping facts → clause selections.
3. **Clause library** (content, **attorney-owned**): versioned clause records, swappable
   without code:
   ```
   Clause {
     id                # "assignment.grant", "warranty.ai", "termination.reversion"
     variant           # jurisdiction / medium / party-type discriminator
     version           # monotonic; every render pins the exact version used
     body              # the legal text, with {{placeholders}}
     required_variables# which Legal-Intel keys must be present to render
     supersedes        # prior clause id@version
     effective_date
     counsel_approved  # BOOLEAN — renders are BLOCKED unless true
     approved_by
   }
   ```
4. **Presentation** (renderer templates): layout, branding, medium-agnostic. Reuses the
   existing deterministic doc-builder pattern (`capabilities.py` / `delivery.py`).
5. **Variable data** (Legal Intelligence): the merge values, with provenance.

**The audit guarantee:** every generated document records the **exact clause id@version set**
it was built from (immutable). You can always reconstruct precisely what a party signed, even
after the library evolves years later. That reconstructability is what an attorney and a court
will demand — and what the version pin delivers.

**The safety gate:** no clause renders into a real document unless `counsel_approved = true`.
Until counsel signs off, the engine can *plan* documents (list required clauses, show the gap
list) but **cannot emit executable legal text.** This lets Phases 0–2 ship with zero legal
exposure (§10).

---

## 6. Renderer architecture

Every document = `renderer(LegalIntelligence, ClauseLibrary, Presentation) → document`. A
renderer reads Legal Intelligence + the selected, counsel-approved clauses. **No business
logic. No data ownership.** Two families:

- **Certificate renderers** (unilateral attestations of fact — *outputs*): Rights, Publishing,
  Ownership, Clearance, Content-ID, Copyright-Chain, PRO-Summary, Licensing-Summary. **Pure
  functions of Legal Intelligence.** Lowest legal risk — they attest to facts already held.
  These *extend the certificate builders already in `delivery.py`.*
- **Agreement renderers** (bilateral contracts — *inputs*): Composer, Assignment, WFH,
  Producer/Mixer/Engineer, Musician/Vocal release, Split Sheet, Portfolio License, NDA, COI.
  Renderer = *clause-selection (from legal-logic) + merge.*

**The loop closes on signature.** After execution, the signed document becomes **evidence**
attached to the facts it created, and those facts flip `asserted → documented → verified`.

**Signature seam** (same null-default pattern as payments/mailer/calendar): default =
typed-name ESIGN/UETA capture (which the delivery portal *already does* for approvals) +
pluggable DocuSign later. The renderer emits the doc; the seam captures intent + returns an
evidence URI; the fact's status advances. Never block; never raise.

---

## 7. Consolidated recommendations (the opinionated answer)

1. **Default to ASSIGNMENT with a WFH recital — not WFH-primary.** For a contractor-based
   house with California talent, WFH-primary is the wrong default: it is often *invalid*
   (truth #1) and, when valid, risks making Chordential an *employer* (truth #2). Assignment is
   always valid, dodges the CA trap, and the §203 reversion (truth #3) is a 35-year theoretical
   irrelevant to a commercial campaign. Keep a WFH recital as a belt-and-suspenders fallback.
   *This likely inverts the assumption in the brief — deliberately.*
2. **Own the copyright, master, and publisher's share. Let composers keep the writer's share.**
   It costs almost nothing on US buyouts, is a genuine upside where content has an afterlife,
   and is the single best talent-retention lever available. This is the "best commercial music
   house" posture.
3. **Prefer loan-out contracting where the talent has an entity** — it sidesteps §3351.5
   entirely and lets you use WFH cleanly when the medium allows.
4. **Treat AI disclosure as a validity gate, not a checkbox.** An AI-*generated* bed cannot be
   warranted as original; the engine must block delivery on it (truth #4). AI-*assisted* with
   real human authorship is fine and disclosed.
5. **Make the Rights Engine a ship-gate.** Legal cleanliness joins delivery-completeness as a
   hard condition before any package downloads.

---

## 8. Risks & alternative business models

- **The single-relationship model's hidden fragility.** "One clean relationship" is only as
  clean as the weakest link in the talent graph (truth #5). One uncleared sample or missing
  vocalist release turns the promise into a **misrepresentation** and exposes Chordential's
  indemnity. → The engine's gap list is the mitigation; it must be un-bypassable.
- **The California employment trap** (WFH → statutory employee, truth #2) — a real,
  quantifiable liability (workers'-comp, UI, payroll, penalties) hiding inside a boilerplate
  clause. Mitigated by assignment-default + loan-out preference.
- **§203 reversion** on backup assignments — low, but must be **recorded** on a reversion
  calendar, not discovered by surprise.
- **AI originality warranty** — the newest, sharpest risk: warranting originality over
  AI-generated material is a **false warranty** that flows straight into the client indemnity.
- **Worker misclassification (AB5/Borello)** — the entire "Chordential contracts talent as
  independent contractors" model depends on defensible IC status; WFH clauses undercut it in CA.
  **Alternative models to weigh:** (a) **loan-out-only** (cleanest, narrows the talent pool);
  (b) **employer-of-record** for CA individuals (heavier, safest); (c) **assignment-default**
  (recommended balance).
- **Business-model challenge — leave less on the table.** A pure buyout forfeits value where
  content has a real performance afterlife (branded YouTube series, international, film-adjacent
  content). A **hybrid** — buyout for the spot + retained writer's share + *optional publishing
  administration as a service* — could be both a new revenue line and a talent magnet. Worth
  modeling in Commercial Intelligence as an alternate tier.

---

## 9. Questions that require retained counsel before ANY production

The engine and data spine (Phases 0–1) need none of these. **Clause generation (Phase 3+)
needs all of them.** I will not guess at:

1. **Exact clause text** for every agreement and certificate — the entire clause library.
2. **The CA §3351.5 mitigation** for Chordential's *actual* talent mix — mandate loan-outs,
   default to assignment, or stand up an employer-of-record? (Choice has tax/insurance
   consequences.)
3. Whether to **register a publishing entity** and take out PRO **publisher** memberships.
4. The precise **AI-disclosure + originality warranty** language (fast-moving; tie to the
   Copyright Office's evolving guidance).
5. **Indemnity caps, insurance requirements, choice-of-law/venue** in the client MSA and the
   talent agreements.
6. Whether existing **client MSAs impose flow-down obligations** that constrain what Chordential
   may promise talent (and vice-versa).
7. **Sample-clearance workflow** and who bears clearance cost/risk.
8. The **buyout-tier definitions** (media/territory/term/exclusivity) as enforceable grant
   language.

Grounding sources for §0's five truths (for counsel's fast orientation):
- 17 U.S.C. §101 (definitions; the nine WFH categories) — Cornell LII / Copyright Office Circ. 30.
- California Labor Code §3351.5(c) — CA leginfo; AB5 musician exemption (2020 amendment).
- 17 U.S.C. §203 (termination of transfers; WFH exemption) — Copyright Office / Cornell LII.
- US Copyright Office, *Copyright and Artificial Intelligence, Part 2: Copyrightability*
  (Jan 29, 2025) — copyright.gov/ai.

---

## 10. Phased roadmap (each phase independently valuable; minimal future refactoring)

- **Phase 0 — Legal Intelligence data spine (pure engineering, zero legal risk).** Fact model,
  provenance, status lifecycle, three-level scoping. Mirror the CI store. Begin capturing facts
  you *already have*: splits, PRO/IPI, W-9/COI from Procurement. No documents generated.
- **Phase 1 — Rights Engine (deterministic resolver) + blocking gap list, wired into the
  delivery gate.** No clause generation. Still zero legal exposure — it only *reports* what is
  owned and what is missing. Enormous operational value; this alone justifies the pause.
- **Phase 2 — Certificate renderers.** They attest to facts you already hold (lowest legal
  risk) and extend the existing `delivery.py` certificate builders: Rights, Clearance,
  Ownership, Copyright-Chain, PRO-Summary. Reviewed by counsel but not novel contract text.
- **Phase 3 — Clause library scaffold + agreement renderers, behind the counsel-approval gate.**
  No clause emits unless `counsel_approved = true`. Start with the three load-bearing
  agreements: Composer/Assignment, Musician/Vocal Release, Split Sheet.
- **Phase 4 — Signature seam (DocuSign) + executed-doc-as-evidence loop + reversion/exclusivity
  calendars.** Closes the fact lifecycle end-to-end.

The Phase-0 data spine is why nothing later requires rework: every subsequent phase is a new
*reader* of the same facts, never a re-modeling of them.

---

*Ratification path: once retained counsel reviews §7–§9 and approves the clause-library
approach, promote the binding decisions into `ARCHITECTURE_DECISIONS.md` as an ADR and record
current build state in `PROJECT_STATE.md`.*
