# Design Conformance Checklist

Baseline: **KB-OPS-V163-001**

A UI candidate cannot receive FINAL PASS unless every applicable item below is evidenced.

## Source-of-truth gate
- [ ] Candidate names KB-OPS-V163-001.
- [ ] Correct accepted reference image(s) are available.
- [ ] No current-production screenshot has been substituted for an accepted design reference.
- [ ] Any baseline ambiguity/drift was escalated before implementation.

## Structural conformance
- [ ] Page purpose matches baseline.
- [ ] Information hierarchy matches.
- [ ] Section grouping matches.
- [ ] Primary/secondary actions match.
- [ ] Default expanded/collapsed states match.
- [ ] Navigation/drill-down semantics match.

## Visual/semantic conformance
- [ ] Attention and incident states dominate routine telemetry appropriately.
- [ ] Routine history/logs are compressed where required.
- [ ] Operator terminology is used instead of raw backend vocabulary.
- [ ] Dates/times are human-readable at the primary layer.
- [ ] Raw diagnostics are progressively disclosed.
- [ ] Density/spacing supports the accepted scanning hierarchy.
- [ ] Empty/unknown/unavailable states are semantically truthful.

## Evidence
- [ ] Implementation screenshot captured at agreed desktop viewport.
- [ ] Side-by-side comparison completed.
- [ ] Material differences recorded in the difference ledger.
- [ ] Every difference is MATCH or explicitly JUSTIFIED; DEFECT count = 0.
- [ ] Relevant automated tests pass.
- [ ] Role A independently reviews actual rendered UI, not only code/report.

## Production gate
- [ ] Production is running the accepted tree/release.
- [ ] Production screenshot captured.
- [ ] Production screenshot is compared to the same baseline.
- [ ] No environment/CSS/build/deployment drift changes the accepted design.
- [ ] Issue/iteration is closed only after production visual conformance passes.

## Difference ledger template

| Area | Baseline | Actual | Classification | Rationale / Fix |
|---|---|---|---|---|
| ... | ... | ... | MATCH / JUSTIFIED DIFFERENCE / DEFECT | ... |
