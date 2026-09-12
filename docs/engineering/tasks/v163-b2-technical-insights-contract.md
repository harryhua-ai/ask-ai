# v1.6.3 B2 Frozen Contract — Technical Insights Convergence

Authority: KB-OPS-V163-002
Issues: #57 #58 #59 and B2 portion of #60
Hard visual reference: docs/product/design/admin-knowledge-ops/references/technical-insights-answer-gaps-original.png

## Objective
Converge Technical Insights to the recovered shared diagnostic experience while preserving existing authoritative evidence and drill-downs.

## Product semantics
Technical Performance and Answer Gaps remain sibling tabs in one Technical Insights domain.
Technical Performance explains system/runtime causes; Answer Gaps explains knowledge/content causes. Do not split them into separate top-level product homes.

Answer Gaps is a read-only operator projection over existing truth in v1.6.3, not a new persisted Knowledge Issue model.

## Expected
- Preserve a strong shared Technical Insights shell and selected-tab state.
- Make incident rows operator-readable first; raw HTTP/internal stages/codes are expandable evidence.
- Make critical/abnormal evidence outrank routine evidence.
- Restore Answer Gaps as a useful queue: question/topic, counts/impact/cause/status/recency only where authoritative.
- Restore contextual diagnosis/evidence layout and existing source/conversation drill-downs where supported.
- Distinguish real zero, unavailable/stale derived data, and populated evidence honestly.

## Forbidden
- Splitting the two tabs into separate top-level domains.
- Inventing cause/status when backend truth is absent.
- New OBSERVING/remediation/resolve/refresh/export persistence semantics.
- Duplicate Data Source inventory/configuration.
- Retrieval/ranking/citation/lifecycle semantics changes.
- Letting raw diagnostics dominate primary hierarchy.

## Acceptance
- Relevant engineering tests/build/typecheck/lint pass.
- Real candidate Admin is rendered with representative technical incidents and gap data.
- Required B2 states are captured at fixed documented viewport.
- Side-by-side Difference Ledger covers all material reference elements/states.
- DEFECT=0.
- JUSTIFIED DIFFERENCE requires Role A acceptance.
- Existing event→source and gap→conversation drill-downs remain functional.
- No screenshot/Ledger => UI UNPROVEN.

## Deliverable
CANDIDATE READY only with candidate SHA + report + screenshots + Difference Ledger + scope audit.
