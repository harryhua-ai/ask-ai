# ASK-AI Answer Intelligence Scorecard

**Purpose:** give a product-owner-readable view of ASK-AI answer quality using the frozen Answer Intelligence Benchmark v1 baseline.

> This scorecard is a presentation layer over the existing Benchmark v1 measurement. It does **not** change the frozen benchmark, case set, scoring rules, baseline results, or adjudication.

## 1. Executive Summary

| Metric | Baseline | Plain-language meaning |
|---|---:|---|
| **Overall Answer Intelligence** | **80.2 / 100** | Overall measured answer quality across the frozen benchmark |
| **Correctness / Hard Quality** | **79.2 / 100** | Whether answers are materially correct and satisfy hard requirements |
| **Evidence Quality** | **73.2 / 100** | Whether answers are supported by the right first-party evidence and citations |
| **Response Experience** | **90.2 / 100** | Whether answers are clear, useful, natural, and appropriate for the interaction |
| **Case Pass Rate** | **81.8%** | 99 of 121 benchmark cases passed by case-majority result |
| Run Pass Rate | 82.6% | 300 of 363 repeated runs passed |
| Zero-source Rate | 32.5% | 118 of 363 runs returned zero sources |
| TTFT P50 | 10.13 s | Median time before the first answer token appears |
| E2E P50 | 13.01 s | Median total answer latency |

### One-number view

**ASK-AI baseline Answer Intelligence = 80.2 / 100**

```text
0        20        40        60        80       100
|---------|---------|---------|---------|---------|
████████████████████████████████████████░░░░░░░░░░
                                        80.2
```

This should be read as the **2026-09-07 frozen baseline**, not as the score of the current development branch.

---

## 2. Where the Gap Is

The formal product target has **not yet been frozen**, so this document does not invent a target such as 90 or 95 and call the difference an official gap.

For an intuitive view only, the table below shows the remaining distance to a theoretical perfect score of 100. This is **not** the product target.

| Dimension | Baseline | Distance to 100 | Current interpretation |
|---|---:|---:|---|
| **Evidence Quality** | **73.2** | **26.8** | Largest measured weakness; evidence selection, coverage, authority, freshness, composition, and observability are the main improvement space |
| **Correctness / Hard Quality** | **79.2** | **20.8** | Material room remains in task understanding, routing, grounding, and answer correctness |
| **Overall Answer Intelligence** | **80.2** | **19.8** | System is useful but not yet at a consistently strong expert-assistant level across all benchmark cases |
| **Response Experience** | **90.2** | **9.8** | Strongest dimension; still needs more natural, less templated, context-appropriate responses |

### Gap ranking

```text
Evidence Quality      73.2 / 100   gap-to-100 26.8
Correctness           79.2 / 100   gap-to-100 20.8
Overall               80.2 / 100   gap-to-100 19.8
Response Experience   90.2 / 100   gap-to-100  9.8
```

The important conclusion is that ASK-AI's largest baseline weakness is **not surface wording**. The larger gap is in whether the system finds, selects, composes, and uses the correct evidence for the user's actual task.

---

## 3. Reliability and Performance View

### Reliability

- **99 / 121 cases passed** by case-majority result.
- **22 / 121 cases did not pass** the baseline case-majority threshold.
- **63 / 363 individual runs failed**.
- **118 / 363 runs returned zero sources**.

A zero-source run is not automatically a wrong answer, but the baseline shows that evidence availability/selection is a major quality constraint and must be interpreted together with case-level adjudication.

### Performance

| Metric | P50 | P90 | P95 | P99 | Max |
|---|---:|---:|---:|---:|---:|
| TTFT | 10.13 s | 12.02 s | 12.56 s | 14.91 s | 16.01 s |
| End-to-end | 13.01 s | 15.86 s | 16.76 s | 20.41 s | 25.05 s |

For a user, the practical interpretation is simple: **the answer can be reasonably good, but it often takes too long to start responding**. Performance therefore remains a separate product gap even when answer quality is acceptable.

---

## 4. What This Baseline Means for the Product

The baseline indicates four distinct product realities:

1. **The answer experience is already the strongest layer.** The main problem is not merely tone or formatting.
2. **Evidence quality is the weakest measured dimension.** Improving retrieval/evidence selection/composition should produce larger quality gains than cosmetic response changes alone.
3. **Task understanding and routing still create false failures.** Production issues such as underspecified in-domain questions and capability/orientation questions being treated as off-topic are examples of correctness defects that the Intelligent Answer Engine initiative is addressing.
4. **Latency is still too visible to users.** Median TTFT above 10 seconds means performance work remains material even if answer quality improves.

---

## 5. Benchmark Identity and Frozen Baseline

- Benchmark: **ASK-AI Answer Intelligence Benchmark v1**
- Frozen case count: **121**
- Baseline date: **2026-09-07**
- Baseline run ID: `PB-V1-20260907-CDBCAD3`
- Production baseline commit: `cdbcad38fc3512561e12c71ff6eda067d06257b5`
- Total executions: **363 / 363 completed**
- Infrastructure errors: **0**
- Infrastructure retries: **0**
- Baseline validity: **ACCEPT_WITH_QUALIFICATIONS**
- Baseline gate: **FINAL PASS**

### Known baseline qualifications

- Evidence scoring has a known judge-leniency qualification in part of the zero-source subset.
- One frozen executable case (`sq-090`) contains a truncated question and remains frozen as part of Benchmark v1 rather than being silently edited.
- Critical-policy adjudication identified policy ambiguity for a small number of PII-related critical flags; the baseline itself was not mutated.

These qualifications matter when interpreting fine-grained scores, but they do not invalidate the baseline as the comparison point for future iterations.

---

## 6. Target and Official Gap

### Current status

```text
PRODUCT_TARGET_SCORE = NOT YET FROZEN
OFFICIAL_GAP_TO_TARGET = NOT YET AVAILABLE
```

An official gap requires an explicit Product decision defining what level constitutes an acceptable target for ASK-AI, for example by dimension and by latency. Until that is frozen, this scorecard will not fabricate a target.

When the target is frozen, this section should become:

| Dimension | Baseline | Current | Target | Improvement vs Baseline | Remaining Gap |
|---|---:|---:|---:|---:|---:|
| Overall | 80.2 | TBD | TBD | TBD | TBD |
| Correctness | 79.2 | TBD | TBD | TBD | TBD |
| Evidence | 73.2 | TBD | TBD | TBD | TBD |
| Experience | 90.2 | TBD | TBD | TBD | TBD |
| TTFT P50 | 10.13 s | TBD | TBD | TBD | TBD |
| E2E P50 | 13.01 s | TBD | TBD | TBD | TBD |

---

## 7. How to Use This Scorecard Going Forward

Use this file as the stable Product/Executive view, while detailed benchmark artifacts remain the engineering/evaluation evidence.

At the end of each major Answer Intelligence iteration:

- keep Benchmark v1 identity/frozen baseline unchanged;
- run the authorized evaluation against the new accepted candidate;
- update **Current** scores;
- show **Improvement vs Baseline**;
- once Product targets are frozen, show **Remaining Gap**;
- link the underlying detailed evaluation artifacts and review decision.

The intended product-level question should always be answerable from this one page:

> **ASK-AI is currently how good, how much did this iteration improve it, and how far is it from the target?**

---

## 8. Baseline Snapshot

```text
ASK-AI Answer Intelligence Benchmark v1
Baseline: 2026-09-07

Overall                 80.2 / 100
Correctness             79.2 / 100
Evidence Quality        73.2 / 100
Response Experience     90.2 / 100

Case Pass Rate          81.8%
Run Pass Rate           82.6%
Zero-source Rate        32.5%

TTFT P50                10.13 s
E2E P50                 13.01 s

Official Product Target      NOT YET FROZEN
Official Remaining Gap       NOT YET AVAILABLE
```
