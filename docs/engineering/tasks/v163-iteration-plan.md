# v1.6.3 — UI Design Convergence Iteration Plan

Status: FROZEN / EXECUTION AUTHORIZED after Role A review
Design authority: KB-OPS-V163-002
Issues: #52–#60

## Objective
Make the shipped Admin Knowledge Operations experience materially conform to the recovered accepted design, while preserving current authoritative backend/product truth.

## Source of Truth
1. docs/product/design/admin-knowledge-ops/DESIGN_RECOVERY_REVIEW_V002.md
2. docs/product/design/admin-knowledge-ops/references/data-source-operations-original.png
3. docs/product/design/admin-knowledge-ops/references/technical-insights-answer-gaps-original.png
4. #52–#60 KB-OPS-V163-002 Frozen Amendments
5. current repository/backend authoritative truth

The PNGs are hard visual references, not inspiration. Current implementation is evidence of available truth, not visual authority.

## Frozen scope
v1.6.3 = visual/UX convergence + existing truth mapped into operator workflows + read-only diagnosis + already-authorized safe operations.

Do not invent persistence, lifecycle/policy/remediation/export semantics merely to imitate a reference. Unsupported design semantics are omitted/unavailable and entered in the Difference Ledger.

## Execution topology
B1 and B2 run in parallel from the same fresh origin/main baseline.

### B1 — Data Source Operations Convergence
Owns #52/#53/#54/#55/#56 plus applicable #60 grammar.
Reference: data-source-operations-original.png.
Contract: v163-b1-data-source-operations-contract.md.

### B2 — Technical Insights Convergence
Owns #57/#58/#59 plus applicable #60 grammar.
Reference: technical-insights-answer-gaps-original.png.
Contract: v163-b2-technical-insights-contract.md.

### Integration / Visual Conformance
Only after B1 and B2 independently pass Role A.
Owns combined-tree conflicts, shared visual grammar, cross-page navigation, fresh screenshots and an independent Difference Ledger.
It MUST NOT become a third redesign track.

## Required execution loop
For each track:
baseline reconstruction → UI state inventory → RED behavioral tests → implementation → GREEN → render real Admin UI → capture screenshots → side-by-side comparison → Difference Ledger → fix all DEFECTs → rerender/recompare.

Engineering GREEN without rendered conformance evidence = UI UNPROVEN, not CANDIDATE READY.

## Difference Ledger
Every material reference-vs-implementation difference is exactly one:
- MATCH
- JUSTIFIED DIFFERENCE — must cite authoritative truth and requires Role A acceptance
- DEFECT — must be corrected

B cannot self-authorize a JUSTIFIED DIFFERENCE. Material unexplained differences are DEFECTs.

## Visual acceptance states
At minimum capture representative states corresponding to the references:
B1: source list; source detail normal; source detail needs-attention/expanded diagnosis; activity/history; edit-source drawer where existing operation supports it; any reference-only unsupported state explicitly ledgered.
B2: Technical Insights shell with both tabs; Technical Performance incident hierarchy; Answer Gaps queue; selected gap diagnosis/context state; supported drill-down state.

Use a fixed documented desktop viewport for paired comparisons. If a reference is a composite board rather than a literal single viewport, compare each depicted product state separately and do not require pixel identity to board annotations/callouts.

## Engineering gates
Relevant backend/frontend tests, typecheck, build and lint must pass with no unexplained regression. No retrieval/ranking/citation/lifecycle/generation semantics may change unless separately authorized.

## Integration gates
1. Combine accepted B1/B2 candidates without rewriting accepted commits.
2. Run combined regression/build/typecheck/lint.
3. Run real Admin with representative authoritative data.
4. Independently capture screenshots; do not reuse B screenshots as proof.
5. Independently rebuild Difference Ledger.
6. Verify shared navigation/terminology/state grammar and existing deep links.
7. DEFECT = 0; every JUSTIFIED DIFFERENCE explicitly accepted by Role A.
8. Only then READY FOR DEPLOY REVIEW.

## Deployment/production gate
Deployment is separate authorization. After deploy, repeat the same representative screenshot states against KB-OPS-V163-002. Production identity/runtime correctness alone cannot close #52–#60. Close iteration only when production visual Difference Ledger has DEFECT=0.

## Deliverables
Each B: candidate SHA, changed files, tests, screenshot paths, Difference Ledger, scope audit, execution report.
Integration: combined candidate SHA, independent screenshots/Ledger, regression evidence, issue reconciliation.
Production: release/deploy identity plus production screenshots and final conformance verdict.
