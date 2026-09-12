# Knowledge Operations Design Baseline

**Baseline ID:** KB-OPS-V163-001  
**Iteration:** v1.6.3  
**Status:** FROZEN DESIGN SOURCE OF TRUTH

## Purpose

This baseline governs the v1.6.3 Admin Knowledge Operations design-convergence work tracked by Issues #52–#60.

The implementation MUST be reviewed against the accepted design, not merely against backend correctness, API availability, tests, or the pre-existing UI.

## Authoritative IA

Knowledge Operations is organized around:

1. Overview
2. Sources
3. Documents
4. Issues
5. Settings

Technical/runtime observability and Knowledge Gaps remain distinct operational domains. Source pages are knowledge-operation workspaces, not sync-configuration/log dashboards.

## Product hierarchy

### Sources list

The list is attention-first. It must answer:
- Which sources need operator attention?
- Why?
- What is the knowledge/content state?
- What action or drill-down is appropriate?

Sync configuration and destructive controls must not dominate the primary information hierarchy.

### Source detail

Operator comprehension order:

1. Source identity and overall health
2. Attention/problem summary
3. Content inventory
4. Generation evidence
5. Recent history / technical evidence

Normal repetitive history is compressed. Exceptions and actionable states are visually stronger.

### Document inspector

A document drill-down must expose the authoritative truth needed to understand:
- identity
- lifecycle/version
- serving state/generation
- citation/provenance where available
- diagnostic reason/evidence

It must not invent fields that the backend does not possess.

### Technical Insights

Technical performance/RAG observability and Knowledge Gaps are separate concepts.

Raw backend diagnostics are progressively disclosed. Incident hierarchy must make operator-impacting failures more prominent than routine telemetry.

### Knowledge Gaps

Summary/visualization empty states must agree semantically with the underlying gap rows. The UI must not simultaneously imply “no gap data” while displaying authoritative gap records.

## Presentation rules

- Operator language before backend vocabulary.
- Human-readable time before raw ISO timestamps; raw values may remain secondary evidence.
- Backend thresholds/enums are not primary UI copy.
- Normal logs and abnormal incidents must not receive equal visual weight.
- Repetitive successful sync history is compressed.
- Destructive controls must not visually dominate routine knowledge operations.
- Information density must support scanning rather than expose every backend fact at equal priority.

## Screenshot reference set

The accepted reference images from the product/design conversation are part of this baseline and MUST be checked into the repository under:

`docs/product/design/admin-knowledge-ops/references/`

Expected semantic references:
- sources-list
- source-detail
- document-inspector
- technical-insights
- knowledge-gaps

**Important:** image assets must be the original accepted design/reference images, not screenshots recreated from the current implementation. If a binary reference is unavailable in a worktree, implementation MUST NOT silently substitute the current UI.

## Annotation contract

For every reference screen, implementation and review must preserve:
- information hierarchy
- grouping
- default expansion/collapse behavior
- operator terminology
- attention/error emphasis
- major density and spacing relationships
- primary/secondary action hierarchy

Pixel identity is not required where responsive layout or real data legitimately differs, but unexplained semantic or hierarchy divergence is a failure.

## Acceptance mechanism

Every UI task in #52–#60 must provide:

1. **Design baseline reference:** `KB-OPS-V163-001`
2. **Implementation screenshot(s)** at the agreed desktop viewport
3. **Side-by-side review** against the corresponding accepted reference
4. **Difference ledger** classifying every material difference as:
   - MATCH
   - JUSTIFIED DIFFERENCE
   - DEFECT
5. **No unexplained differences**
6. Role A visual/design conformance review before FINAL PASS
7. Production screenshot verification after deployment before the iteration is COMPLETE

Tests-green/backend-correct is necessary but insufficient for UI acceptance.

## Change control

B may not reinterpret this baseline to match the existing implementation.

If repository reality makes a baseline requirement infeasible or materially incorrect:
- STOP that requirement,
- report CONTRACT/DESIGN DRIFT,
- return to Role A,
- do not silently redesign.

Any accepted material design change requires a new baseline revision/ID or an explicit amendment committed to the repository.

## Issue mapping

- #52 — Knowledge Operations IA
- #53 — Sources list
- #54 — Source detail
- #55 — Document Inspector
- #56 — Source history
- #57 — Technical Insights IA/domain separation
- #58 — Technical Insights incident/diagnostic hierarchy
- #59 — Knowledge Gaps state semantics
- #60 — Cross-screen visual hierarchy/density/terminology

