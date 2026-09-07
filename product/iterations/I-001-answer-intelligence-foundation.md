# I-001 — Answer Intelligence Foundation

Durable semantic record for the current ASK-AI iteration. GitHub Project #2 owns operational membership/status; this file owns durable iteration semantics. Do not duplicate the full Benchmark / Architecture / Discovery reports here — reference them.

| Field | Value |
|---|---|
| Iteration ID | I-001 |
| Title | Answer Intelligence Foundation |
| GitHub Project | harryhua-ai / Project #2 (`@harryhua-ai's ask-ai project`, PRIVATE) |
| GitHub native Iteration | Custom field `Iteration` (native Projects Iteration type) → **I-001 — Answer Intelligence Foundation**, window **2026-09-07 → 2026-09-20** (14d) |
| Last Reconciled | 2026-09-07 |

## Goal

Establish the answer-intelligence foundation for the ASK-AI Answer Engine before any redesign: a frozen unified evaluation benchmark (Benchmark v1), a measured production baseline with independent review and failure attribution, a frozen target architecture + engineering discovery, and the first implementation increment (INC-1 — Answer Pipeline Observability Foundation).

## Current State

**ACTIVE.** All lifecycle gates below are ACCEPTED/DONE. The execution frontier is INC-1 (Ready — Frozen Implementation Contract authorized by Agent A). INC-2a and INC-3 are contract-ready but NOT execution-authorized.

## Accepted / Completed (iteration history)

| Step | Durable artifact (internal docs repository) |
|---|---|
| Historical Evaluation Material Audit | `docs/evaluation/BENCHMARK_V1_ADMISSION_GROUND_TRUTH_2026-09-07.md` + `docs/evaluation/BENCHMARK_V1_HISTORICAL_CORPUS_MIGRATION_DISCOVERY_2026-09-05.md` |
| Benchmark Definition | `docs/evaluation/benchmark_v1/unified_benchmark_contracts_121_2026-09-07.json` (121 unified cases) |
| Historical Benchmark Migration | `docs/evaluation/BENCHMARK_V1_HISTORICAL_CORPUS_MIGRATION_DISCOVERY_2026-09-05.md` |
| Ground Truth Revalidation | `docs/evaluation/BENCHMARK_V1_GROUND_TRUTH_REVALIDATION_2026-09-05.md` |
| Complex Marking Contract Rewrite | `docs/evaluation/BENCHMARK_V1_MARKING_CONTRACT_REWRITE_2026-09-07.md` |
| Coverage Gap Completion | `docs/evaluation/BENCHMARK_V1_COVERAGE_GAP_COMPLETION_2026-09-07.md` |
| New Case Admission | `docs/evaluation/BENCHMARK_V1_ADMISSION_GROUND_TRUTH_2026-09-07.md` |
| Unified Benchmark Normalization | `docs/evaluation/BENCHMARK_V1_UNIFIED_NORMALIZATION_2026-09-07.md` |
| Benchmark v1 Freeze | `docs/evaluation/BENCHMARK_V1_FINAL_FREEZE_2026-09-07.md` + `docs/evaluation/benchmark_v1/freeze_v1/benchmark_manifest_v1.json` |
| Production Baseline Measurement | `docs/evaluation/benchmark_v1/baseline_v1_2026-09-07/BASELINE_V1_2026-09-07.md` (+ raw/judged results, score summary) |
| Baseline Calibration / Independent Review | `docs/evaluation/benchmark_v1/baseline_v1_2026-09-07/review/BASELINE_V1_INDEPENDENT_REVIEW_2026-09-07.md` (+ judge/human calibration artifacts) |
| Failure Attribution | `docs/evaluation/benchmark_v1/baseline_v1_2026-09-07/attribution/FAILURE_ATTRIBUTION_V1_2026-09-07.md` + `FAILURE_ATTRIBUTION_AMENDMENT_2026-09-07.md` (REV2: SC-1..6 capability gaps, K0 corpus coverage excluded) |
| Target Answer Architecture | `docs/product/architecture/INTELLIGENT_ANSWER_ENGINE_TARGET_ARCHITECTURE.md` (AD1-10 anchored to baseline attribution) |
| Engineering Discovery | `docs/engineering/discovery/INTELLIGENT_ANSWER_ENGINE_ENGINEERING_DISCOVERY.md` — **FINAL PASS** (8-increment sequence; INC-1 / INC-2a / INC-3 READY_FOR_CONTRACT, 5 increments MORE_DISCOVERY) |

Parent P0 initiative / evidence issue: harryhua-ai/ask-ai#32.

## Current Frontier

**INC-1 — Answer Pipeline Observability Foundation.** Status: **Ready**. Frozen Implementation Contract authorized by Agent A. Engineering execution is the next step after this record; observability is first per the engineering discovery dependency order.

## Next (contract-ready, NOT execution-authorized)

- **INC-2a — Evidence Metadata Schema + Deterministic Backfill** — Status: Backlog. Do NOT mark Ready until Agent A explicitly authorizes its Frozen Implementation Contract.
- **INC-3 — Task Understanding Consolidation** — Status: Backlog. Same authorization gate.

## Carried / Excluded

- **INC-2b — Ingestion Redaction**, **INC-4 — Evidence Planning + Slot-driven Retrieval**, **INC-5 — Evidence Selection / Composition / Strategy**, **INC-6 — Claim Class / Temporality Validation**, **INC-7 — Source Envelope / Natural Generation** — Backlog, not implementation-authorized; several still require additional Discovery. No implementation contracts may be manufactured for them.
- **#33 (Widget UX: theme flash on initial load)** — excluded from I-001.
- **#34 (Knowledge sync: GitHub connectivity timeout without recovery)** — excluded from I-001.
- Historical Answer Intelligence regression references: closed issues **#5** (cross-product contamination) and **#19** (comparison empty-generation) belong to the initiative as Done history, **not** to iteration I-001. Do not reopen.

## Dependencies / Blockers

1. Agent A authorization is the gate for every Frozen Implementation Contract (INC-2a/INC-3 next).
2. Discovery must precede any contract for increments currently marked MORE_DISCOVERY in the engineering discovery report.
3. **Bootstrap credential blocker (2026-09-07):** the local GitHub credential (gh keyring OAuth, shared by the GitHub MCP) holds `read:project` only — all Project v2 mutations (creating `Iteration` / `Type` / `Initiative` fields, classifying #32, adding #5/#19, adding INC items) were rejected with `INSUFFICIENT_SCOPES`. Remediation: `gh auth refresh -h github.com -s project` (interactive) or supply a token with the `project` scope, then re-run project reconciliation. Read-only verification passed (project PRIVATE; Status workflow's 5 values untouched; existing Priority/Size/Estimate/Start date/Target date fields preserved; #32/#33/#34 already present as Backlog items; zero mutations performed).

## Governance notes

- Built-in Project workflows (Auto-add sub-issues, Auto-add to project, Auto-close issue, Item added, Item closed, PR linked, PR merged) must not be enabled/edited/deleted; their configuration is deferred to a separate Discovery/authorization gate.
- This document lives in the internal docs repository (local-only, no remote). Commit = persistence.
- Iteration window 2026-09-07 → 2026-09-20 chosen at reconciliation (starts on reconcile date; no velocity claims, no future iterations manufactured).
