# The Campaign Intelligence Extraction Engine (ADR-0023)

The orchestrated, recall-maximizing extraction system that populates the **existing**
Campaign Intelligence Board. The board is canonical (ADR-0013); every downstream module —
Campaign Brief, Commercial Review, Estimate, Proposal, Cue Sheet, Rights, Composer Brief,
Timeline, CRM, contracts — reads the board and only the board. This engine exists solely
to fill it as completely and accurately as possible.

**Non-negotiables honored by construction:**
- The board is not redesigned, renamed, or reorganized. The engine emits the exact
  candidate shape the intake pipeline already writes, steered onto the existing canonical
  keys (`budget_band`, `deadline`, `deliverables`, `decision_makers`, …).
- Everything writes into Campaign Intelligence through the ONE provenance API
  (`campaign_intelligence.contribute`) via the intake pipeline's capture envelope
  (ADR-0014). Nothing writes around it. The engine itself never touches the DB.
- The engine never writes downstream documents (briefs, proposals, estimates, SOWs,
  emails, cue sheets). Those modules consume the board after extraction, as they already do.
- Machine proposes, Jon disposes (Constitution §4.1): every extracted field lands at its
  kind's OPEN status; conflicts with human-owned values park for resolution; the human
  gate is untouched.

## 1. Project architecture

```
                       web/extraction_bridge.py (the impure edge)
   discovery transcript ──┐
   recall transcript      │  assembles EVERY artifact:      src/chordential_oia/extraction/
   discovery notes        │  • the capture text                     (pure domain)
   meeting metadata       ├─▶ • meeting metadata          ┌──────────────────────────────┐
   uploaded RFP           │  • opportunity intelligence   │ engine.run(artifacts, priors)│
   uploaded creative brief│  • board snapshot (context)   │  ├ fan-out: 10 workers ────┐ │
   opportunity intel      │  • prior captures (RFP/notes) │  ├ validation (determin.)  │ │
   relationship intel     │                               │  ├ recall loop (until dry) │ │
   operator notes ────────┘                               │  └ merge (evidence+alts)   │ │
                                                          └──────────┬─────────────────┘ │
              campaign_intake._apply_capture  ◀── candidates ────────┘                    │
                 │ capture envelope (raw evidence + run report)                           │
                 │ contribute() per candidate (capture_id stamped, value_json evidence)   │
                 │ gap engine → ask_* clarification questions                             │
                 ▼                                                                        │
        CAMPAIGN INTELLIGENCE BOARD  ──▶  brief / proposal / estimate / cue sheet / … ◀───┘
```

Layering: the engine package is **pure** (strings + dicts in, candidates out — no DB, no
web imports), mirroring the meeting-domain package. The bridge is the only impure edge,
and `_apply_capture` is the only integration point — one seam, already load-bearing.

## 2. Folder structure

```
src/chordential_oia/extraction/
    __init__.py     public API: run(), WORKERS, FACT_SCHEMA, get_provider(), is_enabled()
    schemas.py      the shared fact envelope + JSON wire schema + coercion + LIST_KEYS
    workers.py      the 10 WorkerSpecs + the shared prompt builder + RECALL_SPEC
    providers.py    the model seam: NullProvider / AnthropicProvider (env-selected)
    validation.py   deterministic validation workers (dedupe / conflicts / impossible)
    recall.py       the Recall Auditor prompt + one audit round
    merge.py        the merge engine (evidence, corroboration, alternates, list unions)
    engine.py       the orchestrator (fan-out, validation, recall loop, merge, report)
src/chordential_oia/web/
    extraction_bridge.py   artifact assembly from storage + the intake-seam callable
tests/test_extraction_engine.py
```

## 3. Worker prompts

One shared skeleton (`workers.build_worker_prompt`), specialized per domain by the
`WorkerSpec`: the specialist's **charge** ("you are responsible ONLY for … Nothing
else"), the recall posture ("read every artifact start to finish; your domain may
surface twenty times; keep searching after each find; never summarize; never invent; if
ambiguous return MULTIPLE candidates at lower confidence; if uncertain emit an
open_question"), the **key guide** (the board's canonical keys first, then domain
vocabulary), the wire schema, the producer priors (ADR-0021), and **every artifact**,
labeled for source attribution.

The ten workers and their board mapping:

| Worker | Facet fence | Lands on (canonical keys bold) |
|---|---|---|
| budget | engagement, commercial, observed | **budget_band**, music_budget, production_budget, budget_flexibility, cost_concerns, procurement_constraints, currency |
| timeline | engagement, observed | **deadline**, launch_date, delivery/review/broadcast_dates, production_schedule, dependencies, milestones, rush_indicators |
| deliverables | engagement, observed | **deliverables** (one merged list) + per-asset `deliverable_*` facts |
| stakeholder | buyer, relationship, observed | **decision_makers**, **brand_notes**, **agency_notes**, stakeholders, approval_chain, procurement/legal contacts |
| creative | direction, observed | **campaign_objective**, **emotional_arc**, **reference_playlist**, mood, genre, instrumentation, tempo, brand_voice |
| campaign | engagement, buyer, observed | **business_objective**, campaign_type, industry, audience, markets, territories, languages, seasonality, products |
| rights | commercial, observed | usage_rights, territory, term, media, licensing, publishing, pro, union_status, buyout, renewals, exclusivity |
| technical | engagement, observed | runtime, frame_rate, sample_rate, file_formats, loudness, delivery_specs, codec, platform_requirements |
| opportunity | relationship, outcome, observed | `upsell_*` / `cross_sell_*` / `expansion_*` as **recommendations** |
| risk | engagement, commercial, direction, observed | `risk_*` / `assumption_*` / `contradiction_*` / `unknown_*` as flagged **open_questions** |

Facts with no dedicated slot land on the `observed` facet — the board's existing
working-memory scratchpad (ADR-0021) — so nothing real is dropped for want of a slot.

## 4. Shared JSON schemas

`schemas.FACT_SCHEMA` — every worker (and the recall auditor) returns a JSON array of:

```json
{"facet": "engagement", "key": "budget_band", "kind": "fact",
 "value": "$20,000", "confidence": 90,
 "evidence": "twenty for the music", "speaker": "Pat, CMO",
 "timestamp": "00:14:32", "artifact": "Discovery Transcript",
 "is_concern": false}
```

Coercion (`coerce_fact`) is the domain fence: off-facet/off-kind items are dropped
(another specialist owns them), keys normalize to the board's snake_case, confidence
clamps to 0–100. Field Name / Candidate Value / Confidence / Supporting Evidence /
Speaker / Timestamp / Source Artifact all survive to the board: the candidate's extras
ride in `value_json` on the CI field, and the complete raw extraction is stored verbatim
on the capture envelope — the board schema itself is untouched.

## 5. Merge engine (`merge.py`)

Deterministic folding, one candidate per board slot `(facet, key, kind)`:
- **Evidence preserved** — every supporting quote/speaker/timestamp/artifact/worker rides
  in `value_json.evidence` (capped at 6).
- **Corroboration** — the same value found twice keeps both evidence trails and the max
  confidence (validation collapses the duplicate row, not the proof).
- **Ambiguity preserved** — a scalar slot with conflicting values keeps the
  highest-confidence value as primary and EVERY distinct other value in
  `value_json.alternates`; validation has already raised the flagged `confirm_<key>`
  open_question for the operator.
- **List slots union** — `deliverables`, `reference_playlist`, `milestones`, territories,
  languages, formats… merge into one deduped list: five partial finds become one complete
  value (recall-maximizing, not last-writer-wins).
- Downstream, `contribute()` remains the arbiter: human-owned values are never clobbered
  (disagreement parks as a board conflict), and everything lands OPEN.

## 6. Validation engine (`validation.py`)

Validation workers never read the transcript — they inspect the fact set. Deterministic
by design (free, offline, testable; no second model silently rewriting the first):
- **Duplicates** — exact `(facet, key, kind, normalized value)` collapse; confidence max
  carries; evidence merges.
- **Conflicts** — one scalar fact slot, materially different values → all values survive
  (primary + alternates) AND a flagged `confirm_<key>` open_question makes the
  disagreement loud. List slots are exempt (partial lists are corroboration).
- **Impossible values** — empty values; money fields whose every figure is ≤ 0 or absurd.
  Deliberately light: honesty means dropping only what is provably wrong.
- **Required-empty → clarification questions** — the intake pipeline's EXISTING gap
  engine (`campaign_intake.gaps` → `ask_*` open_questions over the REQUIRED set) already
  does this against the whole board after write. One implementation, not two.

## 7. Recall engine (`recall.py`)

After validation, the Recall Auditor receives the original artifacts AND the complete
extracted-fact inventory with one charge: **"what facts were missed?"** It hunts
omissions aggressively (with the domain fences open — its job is what fell between
them), returns only facts not already in the inventory, and each round's finds go back
through validation. The engine loops until a round comes back dry or the bounded round
budget (`CHORDENTIAL_EXTRACTION_RECALL_ROUNDS`, default 2) is spent — a cost guard, not
a correctness one: the raw capture is permanent and extraction can always re-run.

## 8. Execution flow

1. A capture arrives on any lane (discovery call, meeting transcript/notes, RFP, email
   thread, client brief — ADR-0014). `_apply_capture` asks the bridge for an engine seam.
2. The bridge assembles the artifact bundle: the capture text + meeting metadata +
   Opportunity Intelligence + the board snapshot + prior captures. Every worker gets all
   of it.
3. Fan-out: ten specialists run in parallel; each returns coerced, fenced facts.
4. Validation: dedupe / conflicts / impossible values → surviving facts + flagged questions.
5. Recall loop: audit → validate → repeat until dry (bounded).
6. Merge: board-shaped candidates with evidence + alternates in `value_json`.
7. The intake pipeline (unchanged) writes the capture envelope — now carrying the
   structured run report — contributes every candidate with the `capture_id` stamp, runs
   the gap engine, syncs confirmed engagement facts to the opportunity.
8. Only then do downstream modules read the board — exactly as they always have.

The Producer Debrief lane is deliberately excluded: it is the human's subjective read
(kinds-only, §2bis); a crew of fact-hunters would launder interpretation into fact.

## 9. Parallel execution strategy

Workers are independent by contract (no cross-talk), so the fan-out is a
`ThreadPoolExecutor` (the work is network-bound; threads are the right grain for a
SQLite/FastAPI app — no asyncio contagion into the intake path). Pool size
`CHORDENTIAL_EXTRACTION_WORKERS` (default 6) caps concurrent model calls below typical
API rate limits. Validation, merge, and each recall round are microsecond-scale pure
Python; only the recall rounds are sequential by nature (each needs the prior
inventory). Wall-clock ≈ ceil(10/pool) × worker latency + rounds × recall latency.

## 10. Error recovery strategy

Degrade, log, continue — never block the capture (the transcript is permanent evidence;
extraction can always re-run):
- **Provider**: bounded retry with backoff inside the provider; then decline (None).
- **Worker**: a failure returns `{facts: [], error}` into the run report; the other nine
  land. Malformed JSON → tolerant array parse → `no_output`.
- **Recall round**: exceptions yield an empty round → the loop ends gracefully.
- **Engine/bridge**: any unexpected failure → the seam returns None → intake falls back
  to the single-prompt seam or the deterministic heuristics (regression-pinned).
- **Item level**: coercion drops malformed items; only in-schema facts pass.

## 11. Logging strategy

Two sinks, one truth:
- `logging.getLogger("chordential.extraction")` — worker failures (warning), run
  summaries (info) for operational eyes.
- **The run report on the capture envelope** (`metadata.extraction_run`): provider,
  model, per-worker `{facts, ms, error}`, dedupe/conflict/impossible counts, recall
  rounds + adds, total ms. Observability stored as evidence, queryable forever, next to
  the raw text it describes — "why did the board change?" and "how did extraction run?"
  answer from the same row.

## 12. Testing strategy

`tests/test_extraction_engine.py` (15 tests, all offline via `FakeProvider`):
- **Workers** — ten domains exist; every prompt carries the charge, the schema, every
  artifact, the recall posture, and the priors; the fence drops off-facet/off-kind items.
- **Orchestration** — all ten fan out; a worker failure is recorded and never blocks.
- **Validation** — dedupe keeps max confidence + both evidence trails; true conflicts
  raise flagged questions; list slots don't false-positive; impossible values drop.
- **Merge** — evidence and alternates preserved; list slots union and dedupe.
- **Recall** — missed facts added; the loop stops on the first dry round.
- **Integration** — through `ingest_opportunity` into the real board: values on canonical
  keys, `capture_id` stamps, `value_json` evidence, OPEN statuses, the run report on the
  capture, artifact assembly (Opportunity Intelligence in every prompt).
- **Regression pins** — null provider: intake byte-for-byte deterministic, no run report;
  provider meltdown: capture still lands with heuristic extraction; debrief lane never
  invokes the fact crew.

## 13. Performance metrics

Every run self-reports (stored per capture, aggregable by SQL over
`captures.metadata_json`):
- per-worker latency + fact count + error rate
- duplicates_removed (cross-worker overlap), conflicts (ambiguity surfaced),
  impossible_dropped (schema honesty)
- recall_rounds + recall_added — **the recall pass's measured value**; if recall_added
  trends to zero the rounds budget can drop to 1
- end-to-end ms and candidate count; downstream, the board's own
  `understanding_pct` measures what extraction was for.

## 14. Cost optimization

- **Bounded bundle** — the primary capture caps at 24k chars, supplementary artifacts at
  6k each, four prior captures max: a hard ceiling on per-worker input.
- **Bounded recall** — default 2 rounds; each round only pays off while it finds facts.
- **One model call per worker** — no chains; validation and merge are free (pure Python).
- **Model dial** — `CHORDENTIAL_EXTRACTION_MODEL` (default `claude-sonnet-5`; a cheaper
  model can drive the specialists while the recall auditor stays strong — both read the
  same env today, split when data justifies it).
- **Kill switches** — `CHORDENTIAL_EXTRACTION_ENGINE=0` reverts to the single-prompt
  seam; `CHORDENTIAL_INTAKE_LLM=0` reverts to free deterministic heuristics.
- The ~10× input-token multiple vs. the single prompt is the deliberate price of recall:
  the board feeds every revenue document, and a missed budget/rights/deadline fact costs
  more than the tokens. Anthropic prompt caching over the shared artifact blocks is the
  designed next lever (identical artifact suffix across all ten prompts).

## 15. Future expansion strategy

- **New domain** = append one `WorkerSpec` (name, charge, fences, key guide). Engine,
  validation, merge, recall, tests are shape-generic. Candidates: Procurement (ADR-0022
  vocabulary), Union/AFM specifics, Localization.
- **New artifact source** = one block in `extraction_bridge._artifacts` (e.g. email
  threads via a mail integration, uploaded PDFs via a text extractor).
- **LLM adjudication** — a validation worker that *judges* conflicting candidates could
  slot behind the deterministic pass; it must stay proposal-only (the human gate stands).
- **Priors deepening** — worker-specific priors from the ADR-0021 learning ledger
  ("this operator always asks for stems") sharpen each specialist individually.
- **Structured outputs** — provider-native JSON schema enforcement when adopted; the
  wire contract is already a JSON Schema (`FACT_SCHEMA`).
