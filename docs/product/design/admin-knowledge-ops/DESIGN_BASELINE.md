# Knowledge Operations Design Baseline

**Baseline ID:** KB-OPS-V163-001  
**Iteration:** v1.6.3  
**Status:** DESIGN HOLD — superseded for planning by recovered-design review pending approval

## Critical governance notice

The original accepted visual references have now been recovered and preserved in-repo as compressed visual copies suitable for agent/reference review:

- `docs/product/design/admin-knowledge-ops/references/data-source-operations-original.png`
- `docs/product/design/admin-knowledge-ops/references/technical-insights-answer-gaps-original.png`

They materially change several assumptions encoded in this v001 baseline.

Therefore:

> **#52–#60 MUST NOT begin implementation from KB-OPS-V163-001 alone.**

Use:

`docs/product/design/admin-knowledge-ops/DESIGN_RECOVERY_REVIEW_V002.md`

for the current recovery review.

After User/Role A approval, the accepted result will become the next frozen design baseline.

## What remains valid from v001

The following governance rules remain in force:

- backend correctness/tests are necessary but insufficient for UI acceptance;
- operator language must outrank raw backend vocabulary;
- normal telemetry must not visually compete with actionable exceptions;
- repetitive successful history should be compressed;
- technical evidence should be progressively disclosed;
- no UI may invent backend/product truth;
- every material UI task requires implementation screenshots;
- Role A must perform side-by-side design conformance review;
- unexplained material design differences block FINAL PASS;
- production screenshots must be checked against the same accepted baseline before iteration closure.

## Recovered original design references

### Data Source Operations

`references/data-source-operations-original.png`

Contains accepted visual/product intent for:

- data-source list
- source detail / knowledge-content workspace
- expanded knowledge-item issue handling
- synchronization status and recent activity
- Edit Data Source drawer
- Knowledge Settings drawer
- high-risk change preview modal

### Technical Insights / Answer Gaps

`references/technical-insights-answer-gaps-original.png`

Contains accepted visual/product intent for:

- Technical Insights shared domain
- Technical Performance / Answer Gaps tab relationship
- answer-gap issue queue
- cause/status/impact/recency semantics
- diagnosis side panel
- typical-question evidence
- related-source drill-down
- related-conversation evidence/export intent
- content repaired → observation workflow

## Acceptance mechanism

The next frozen baseline must preserve this minimum mechanism:

1. design baseline ID named in every relevant Issue/Contract;
2. accepted reference image(s) stored in repo;
3. implementation screenshot(s) captured at agreed viewport;
4. side-by-side comparison;
5. difference ledger: MATCH / JUSTIFIED DIFFERENCE / DEFECT;
6. DEFECT count = 0 before Role A FINAL PASS;
7. integrated UX composition review;
8. pre-deploy rendered-UI review;
9. production screenshot parity before iteration COMPLETE.

## Change control

B may not reinterpret recovered design intent to match the existing production implementation.

If current repository truth makes a recovered design requirement infeasible or invalid:

- classify it in the recovery review;
- obtain Role A/User decision where material;
- amend/freeze the new baseline before implementation;
- never implement first and rationalize the difference afterward.
