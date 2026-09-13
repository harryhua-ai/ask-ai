# v1.6.4 Iteration Plan — Knowledge & Answer Integrity

- Date: 2026-09-13
- Status: **CONTRACT READY / WAITING FOR CODE GATE**
- Base: `origin/main = 5c501914636ae274bdf54896e3decf86c4584e12`
- Scope issues: #25 (lifecycle retirement/GC), #28 (Woo variant commercial truth), #31 (evidence authority/precedence), #48 (citation URL integrity)
- Evidence base: [v164-engineering-reality-audit.md](./v164-engineering-reality-audit.md) (acceptance matrices + production probe)
- Governance: v1.6.3 is still in Integration/Acceptance. v1.6.4 planning/contracts are frozen now; **implementation is NOT authorized** until v1.6.3 = COMPLETE and the code-gate re-verification below has passed.

## 1. Objective

Close the knowledge-and-answer integrity loop in one iteration:

1. **Lifecycle closure (#25)**: source disappearance → confirmed retirement → automatic GC becomes a real, exercised loop (not just dormant machinery).
2. **Commercial & evidential truth (#28 + #31)**: answers ground current commercial facts in actual Store variation truth, and every material claim uses its best available authoritative evidence class — with truthful absence and freshness semantics.
3. **Citation navigability (#48)**: every rendered clickable citation resolves to its authoritative source; nothing renders as clickable when it cannot (no fake navigability).

Non-goals (frozen): no redesign of the TB-P1 lifecycle state model; no change to comparison pipeline, product isolation, citation numbering, fail-closed serving projection (they are green — regression gates protect them); no Cartesian variation synthesis; no hard-coded product prices/URLs; no new Admin IA (the #50 surface is the consumer, not a workstream); no production mutation during development.

## 2. Track topology (dependency-driven, not 1-issue-1-track)

```
CODE GATE (v1.6.3 COMPLETE + fresh-main drift check)
        │
        ├── Track A — Lifecycle Retirement & GC Closure            (#25)
        │      backend lifecycle/connectors/sync + ops trigger
        │
        ├── Track B — Commercial Truth & Evidence Authority        (#28 + #31)
        │      B1: Woo variation ingestion + metadata (data layer)
        │      B2: claim-authority / absence / freshness semantics (answer layer)
        │      (B1 → B2 via one frozen interface; B2 may build on fixtures)
        │
        └── Track C — Citation URL Integrity                       (#48)
               backend linkability state + widget badge gate
        │
   Integration E — combine A+B+C on one tree: full regression + gates + combined topology
        │
   Release → Deploy → Production Acceptance (real repro queries + admin truth + lifecycle exercise)
```

Rationale for 3 tracks (not 4): #28 and #31 share **one mechanism** — claim-dependent evidence authority. "Price/stock → Store" is one row of the same claim→authority mapping #31 requires; both touch the same evidence-planning/selection/generation files, and building them separately would create two competing semantics layers. #48 is orthogonal (URL identity vs claim authority) with a distinct consumer (widget). #25 is orthogonal infrastructure.

File-ownership boundaries (conflict avoidance for parallel tracks):

| Region | Owner |
|---|---|
| `scripts/sync.py` lifecycle paths, `document_lifecycle.py`, `lifecycle_gc.py`, `filesystem.py`/`woocommerce.py` `fetch_deleted`/discovery-confirmation, deploy cron | **A** |
| `evidence_planning.py`, `evidence_selection.py`, `evidence_reservation.py`, `response_strategy.py`, `claim_validation.py`, `rag.py` prompt block (~:1143-1166) + intent/bucket region, `woocommerce.py` variation ingestion, `ingest.py` metadata props, admin commerce schema fields | **B** |
| `rag.py:_extract_sources` (~:1170-1231), `canonical_url.py`, `citation.py` linkability/`PUBLIC_SOURCE_TYPES`, `routes.py` citation serialization, `widget/src` (sanitize/types), github connector visibility capture | **C** |
| Neutral (both B and C read, neither rewrites semantics): `search.py` metadata plumbing | shared, additive-only |

`rag.py` is split by region: B owns the generation-prompt + retrieval-bucket regions, C owns `_extract_sources`. Any spillover requires re-negotiation in Integration E, not silent edits.

## 3. Track A — Lifecycle Retirement & GC Closure (#25)

Contract: [v164-track-a-lifecycle-retirement-contract.md](./v164-track-a-lifecycle-retirement-contract.md)

Scope (WHAT): ledger-side disappearance confirmation for connector-deletion-less sources (filesystem, WooCommerce) with explicit policy-absence classification; `missing_candidate` grace producer (first complete-discovery absence) → retire on second consecutive confirmation; RETIRED→7d→GC eligibility reuses frozen TB-P1 semantics unchanged; an automatic production-safe GC trigger (scheduled sweep; apply behind explicit config; first production apply is a controlled ops action); persisted retirement reason/evidence surfaced in the existing #50 detail view.

Dependencies: none outside main. Consumes the already-built #50 buckets (data starts flowing; zero Admin IA change).

Acceptance highlights: fs file-deletion e2e (delete → sync ⇒ missing_candidate+Needs-Attention-with-reason → sync ⇒ RETIRED+serving stops+`gc_eligible_at=+7d`); policy-absence never retires and surfaces a distinct reason; transient scan failure never confirms; woo fixture-level same flow; GC trigger proven in integration (scheduled dry-run + config-gated apply); idempotence + persisted audit records; red-line regression (serving projection untouched).

## 4. Track B — Commercial Truth & Evidence Authority (#28 + #31)

Contract: [v164-track-b-evidence-authority-commercial-truth-contract.md](./v164-track-b-evidence-authority-commercial-truth-contract.md)

Scope (WHAT):
- **B1 (ingestion, #28)**: fetch actual Store variations; per-variation first-class truth (attributes, SKU, regular/current/sale price, stock/purchasability, canonical identity); structured chunk-level commerce metadata (anti-conflation identity); admin doc-truth exposes variation/SKU/price/stock; only real variations are purchasable truth.
- **B2 (semantics, #28+#31)**: claim-type → best-available-authority mapping (spec→Product/Wiki docs; SDK/API→developer docs; price/stock/variation→Store; deployment-proof→Case Study; architecture→Solution+Case; capability→authoritative product docs); absence assessed across eligible authoritative classes (kills the context-scoped “官方资料未载明” overstatement class); mixed config+price questions reach Store handling; CASE_EVIDENCE eligibility for website case studies + proven-deployment distinction; solution-page retention path; model/use-case owning role; truthful price freshness/staleness; EN/ZH regression pair.

Frozen internal interface B1→B2: the variation metadata/identity contract (field names, identity key, admin schema shape) — to be pinned in the B contract's Frozen Interface section during B1 kick-off (contract amendment, not silent drift).

Dependencies: B2 acceptance (cg-r05 end-to-end) requires B1 data; B2 development proceeds in parallel against fixtures. Woo source re-sync after B1 lands (small source: 41 docs).

Acceptance highlights: frozen repro cg-r05 end-to-end (per-config prices with SKU/attribute association, no false official-absence, no fabricated combinations); solution/case composition query retains complementary roles (solution page + case + wiki + model docs, each used for the claims it owns); absence-semantics tests (new — currently zero); red lines cg-r03/r04/cg-s01 unchanged; EN/ZH pair; production repro acceptance.

## 5. Track C — Citation URL Integrity (#48)

Contract: [v164-track-c-citation-url-integrity-contract.md](./v164-track-c-citation-url-integrity-contract.md)

Scope (WHAT): linkability becomes an explicit, backend-owned citation state (valid canonical URL vs explicitly non-navigable vs private/inaccessible vs stale) surviving serialization to the widget; widget renders non-clickable representation whenever the state is not a safe external URL (closes the unguarded badge path and the `url=""` ambiguity); GitHub ingestion captures repo accessibility so private repos never present fake public navigability; `local_git`/`file://` removed from linkable classes; staleness semantics explicit and truthful (branch-ref 404 window documented and represented, not fabricated); automated cross-source suite asserting stored URL → API citation JSON → rendered href (incl. non-clickable classes).

Dependencies: none outside main. Optional (not gated): wire the orphaned `/api/click` telemetry.

Acceptance highlights: badge gate unit tests (empty/file/invalid → non-clickable; valid → canonical href unchanged incl. wiki mapping); private-repo citation renders per stored state; zero retrieval/grounding/numbering drift (citation-integrity suite + red lines); e2e URL-chain test per linkable source type; production click-through checks on a real non-wiki GitHub citation.

## 6. Parallelization & integration

- A ∥ B1 ∥ B2(fixtures) ∥ C after code gate, each from fresh main; narrow file ownership per §2.
- B2's end-to-end acceptance joins B1 at Integration E; C and A are independent of both.
- Integration E: 3 merges into one combination tree (zero-rewrite discipline as v1.6.2), full backend suite + PA suite + vitest + tsc + build, cross-track gates: lifecycle e2e × woo re-sync × cg-r05 × citation URL suite on the combined tree.
- Release/deploy/production acceptance per the standard orchestration; production acceptance must include: real NE101/NE301 pricing repro, real NE503-class citation click-through, solution-query composition check, and a **controlled** lifecycle exercise on a designated filesystem source (missing → retired visible in #50) + GC dry-run evidence (apply is an explicit operator action, may trail the release).

## 7. Issue closure criteria

| Issue | Close when |
|---|---|
| #25 | Track A acceptance incl. production lifecycle exercise + automated GC trigger evidence; R10/R3/R5-confirmation rows flip to IMPLEMENTED in a delta audit |
| #28 | Track B acceptance incl. cg-r05 end-to-end on production + admin variation inspection evidence |
| #31 | Track B acceptance incl. authority/absence/solution-composition evidence on real queries |
| #48 | Track C acceptance incl. production cross-source click-through suite with zero dead/malformed clickable citations |

No issue is closed by planning. Priority and `iteration:v1.6.4` labels unchanged.

## 8. Code gate (mandatory before implementation)

1. v1.6.3 reaches **COMPLETE** (Integration B + review + release + deployment + production acceptance closed).
2. Fresh `git fetch`; re-base contract check on the new main SHA; run **contract-drift / implementation-overlap check**: confirm v1.6.3's final tree did not alter this plan's factual basis — specifically: lifecycle files (Track A's basis), evidence/citation pipeline regions (B/C ownership map), widget sanitize/types, woo connector, and the six spot-checked claims in the audit §7. Any drift ⇒ amend contracts (versioned, no silent rewrite) before authorization.
3. Role A separately and explicitly authorizes implementation (per-track authorization acceptable; B2 may authorize before B1 lands).

**IMPLEMENTATION_AUTHORIZED = NO** (as of this document; reason: v1.6.3 not COMPLETE).

## 9. Material risks / blockers

| Risk | Mitigation |
|---|---|
| v1.6.3 final tree changes lifecycle/evidence/citation code (3 B-tracks in flight) | Code-gate drift check is blocking; contracts carry file-ownership maps to localize re-verification |
| Store-side variation data quality ( Woo API may not expose every combination; attributes may be sparse) | B contract freezes "only real variations" + truthful-insufficiency semantics; Discovery-lite step inside B1 kick-off verifies endpoint representation before schema freeze |
| Corpus/schema growth from variation ingestion + metadata props | Additive-only schema; woo source is small (41 docs) — full re-sync cheap; no mass backfill required (metadata computed at ingest; read-time fallback allowed) |
| B2 semantic changes regress red-line answer quality | Comparison-exempt preserved; red lines cg-r03/r04/cg-s01 + frozen benchmark as gates; prompt-side changes validated by eval suite not unit-only |
| GC `--apply` against 147,999-chunk production | Exact-UUID purge already test-proven; dry-run-first ops runbook; apply is explicit, auditable, and may trail deployment |
| Private-repo linkability changes visible-citation behavior (fewer clickable citations) | Product-frozen direction (#48: no fake navigability); acceptance records the before/after set |
| Parallel-track `rag.py` contention (B prompt region vs C `_extract_sources`) | Regional ownership table; spillover renegotiated at Integration E only |
| www/widget edge 404 (observed in v1.6.2, orthogonal) | Unrelated to #48 link semantics; tracked separately; do not absorb into Track C |

## 10. Deliverables of this planning pass

- `docs/engineering/tasks/v164-engineering-reality-audit.md` — full acceptance matrices + production probe + reconciliation (this iteration's factual record)
- `docs/engineering/tasks/v164-iteration-plan.md` — this document
- `docs/engineering/tasks/v164-track-a-lifecycle-retirement-contract.md`
- `docs/engineering/tasks/v164-track-b-evidence-authority-commercial-truth-contract.md`
- `docs/engineering/tasks/v164-track-c-citation-url-integrity-contract.md`
- Planning comments on #25/#28/#31/#48 (no status/priority/iteration changes)
