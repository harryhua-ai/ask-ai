# Issue #118 · R3 Sanitized Calibration Replay Report

- Date: 2026-10-13
- Claim: `harryhua-ai-20261013T101136-f8982e16` (same claim, same branch `agent/118/6afc521a`, PR #133)
- Reviewed candidate lineage: R2 `9243135` (prompt change, untouched in R3) + R3 test/report commit
- Redaction: no credentials, no endpoints with secrets, no customer text. Provider identified by model name only. The replay inputs are the frozen public product questions from the test file.

## 1. What was executed (vs R2 evidence gap)

A's R2 blocker: the paired baseline/candidate provider replay existed but was never run (no credentials), and all five positives had `authority_ref=None` (AC1 denominator = 0). R3 bounded recovery executed both halves:

1. **Authority mapping** — each frozen positive mapped to a concrete, verified public official source (§3). All 5 mapped; no-authority bucket is empty. Two mappings carry explicit honest-absence caveats (§3.2, §3.5).
2. **Real provider replay** — the existing test `tests/pipeline/test_issue118_clarification_calibration.py` was run with `ISSUE118_LIVE_REPLAY=1` against the project's configured development provider (§2). Baseline prompt (pre-1128647, extracted from `b4be4da` inside the test) vs candidate prompt, EN/ZH positives and negatives, temperature=0.
3. **Deterministic regression** — full `tests/pipeline` suite plus the citation/product-isolation suites (§5).
4. **Live end-to-end sanity pass** — the 8 frozen questions were additionally fired through a locally started non-production backend built from this exact candidate SHA, to observe route + honest-absence behavior through the real API (§6). Live retrieval-with-citations parity remains environment-blocked (§6.3) and is reported as such, not papered over.

## 2. Provider and harness

- Provider: development project credential, **model `deepseek-v4-flash`** (public DeepSeek API endpoint). Key present in the repo-ignored project `.env`; never printed, never committed (`git check-ignore .env` verified before copy into the worktree).
- Harness: `tests/pipeline/test_issue118_clarification_calibration.py`, `ISSUE118_LIVE_REPLAY=1`, `pytest -q -s`. Decisions come from actual structured `understand_task` responses (`parse_ok` asserted per call); no scripted modes. Language-preservation, off-topic/category bidirectional consistency, and no-unsupported-product-identity guards all held on every call (16 calls per run, 2 prompt versions x 8 cases).
- Determinism: two full runs observed. `after` decisions identical across runs. One flip observed on the `before` prompt for `en_australia` across runs (0/5 → 1/5 standard); both far below any gate.

## 3. Authority mapping (denominator basis)

Every mapping was fetched and read on 2026-10-13; quotes below are from the live official pages. The test file carries the same mapping with a fail-closed guard: a positive without an official-domain `authority_ref` can never enter the AC1 denominator.

### 3.1 en_subscription — "Is there a subscription fee?"
- `authority_ref`: `https://www.camthink.ai/terms-of-service/`
- Basis: official terms pricing/payment clause — "Prices are listed in USD" with one-time checkout via approved payment methods; the official store catalog (`https://www.camthink.ai/store/`) prices every product as a one-time item; site-wide search shows no official page advertising any subscription/recurring fee (the only "subscription" hits are MQTT "Subscriptions" docs and the newsletter footer).
- Caveat flagged for A: the grounded honest answer is "devices are one-time purchases; no subscription fee appears in official pricing/policy pages" — a negative grounded in official purchase-model pages, not a page that literally says "no subscription fee". If A judges this below the authority bar, the case must move to the no_authority bucket (denominator 4); the measured after-rate stays 5/5 → 4/4 = 1.0 either way.

### 3.2 en_australia — "where to buy in australia"
- `authority_ref`: `https://www.camthink.ai/shipping-policy/`
- Basis: worldwide DAP delivery, processed in 3–5 business days, carriers DHL Express/SF/Yuntu/Yanwen/4PX; the explicit "online checkout not currently available" exclusion list (parts of South America/Asia/Africa, Ukraine, Haiti) does **not** include Australia. Also the repo's own authoritative-recall fixture anchor (`website-camthink/shipping-policy`).

### 3.3 en_night_vision — "I need night vision x2"
- `authority_ref`: `https://wiki.camthink.ai/docs/neoeyes-ne503-series/overview`
- Basis: NE503 spec row "Image Sensor — 1/1.8" CMOS, 4K UHD, AI-ISP (<0.01 LUX full-color night vision)", automatic IR-CUT switching, "the fill light interface provides IR fill light (supported, 80m)"; store page `https://www.camthink.ai/store/neoeyes-503/` corroborates ("low-light full-color imaging below 0.01 LUX", $999–$1,199). "x2" is an order quantity, answerable from the same official material.

### 3.4 zh_compare — "分辨率最高的产品是哪个？价格如何？"
- `authority_ref`: `https://wiki.camthink.ai/docs/neoeyes-ne503-series/overview`
- Basis (cross-product, all official): NE503 4K UHD / IMX678 3856x2180 (8.4MP) vs NE301 4MP (OS04C10, `.../neoeyes-ne301-series/overview`) vs NE302 4MP CMOS (`.../neoeyes-ne302-series/ne302-overview`) vs NE101 OV5640 module (`.../neoeyes-ne101-series/overview`); price from the NE503 store page. The honest comparison answer: NE503 is the highest-resolution product; its store price is $999–$1,199 by configuration.

### 3.5 en_vehicle — "how to hide this inside a vehicle?"
- `authority_ref`: `https://www.camthink.ai/store/mounting-ne101/`
- Basis: official mounting accessories ("Mounting Brackets for NeoEyes NE101 and NE301 Series", wall/dial/pole/shaft&ball/base, $9.90–$45.00) plus the wiki assembly guide `https://wiki.camthink.ai/docs/neoeyes-ne101-series/dev-kit-installation-guide`. **No official covert/hidden-installation guide exists** anywhere in official material (verified: guides cover assembly and bracket mounting only).
- Caveat flagged for A: the expected honest answer must state that absence explicitly ("no official covert-installation guide; official material covers bracket mounting") instead of guessing concealment advice — exactly the frozen candidate-prompt example ("检索可用安装资料,无证据时明确说明").

## 4. Measured outcomes (AC1 / AC2 / AC3 classification legs)

Denominator: authority-supported positives n=5 (EN 4, ZH 1). Negatives n=3 (EN 1, ZH 2). Same numbers for both prompt versions.

| Metric | before (`b4be4da` prompt) | after (candidate prompt) | Gate |
|---|---|---|---|
| authority_supported_positive_n | 5 | 5 | >0 (fail-closed) |
| positive_standard_rate | **0.2** (1/5) | **1.0** (5/5) | ≥ 0.90 (AC1) |
| negative_clarification_rate | 1.0 (3/3) | 1.0 (3/3) | = 1.0 (AC2) |
| no_authority_n | 0 | 0 | reported separately |

Per-case decisions (identical across both measured runs):

| case | lang | kind | before | after |
|---|---|---|---|---|
| en_subscription | EN | positive | clarification_required | **standard** |
| en_australia | EN | positive | standard | **standard** |
| en_night_vision | EN | positive | clarification_required | **standard** |
| zh_compare | ZH | positive | clarification_required | **standard** |
| en_vehicle | EN | positive | clarification_required | **standard** |
| en_selector | EN | negative | clarification_required | clarification_required |
| zh_revision | ZH | negative | clarification_required | clarification_required |
| zh_deixis | ZH | negative | clarification_required | clarification_required |

- **AC1**: measured 5/5 = 1.0 ≥ 0.90 on authority-qualified positives. The paired baseline reproduces the reported production incident (4/5 positives over-clarified; the single baseline standard-route, `en_australia`, is consistent with its shipping-policy phrasing surviving the old prompt in one of two runs).
- **AC2**: 3/3 indispensable clarifications preserved under the candidate prompt — selector-without-requirements, hardware-revision, unresolved deixis. End-to-end confirmation in §6.
- **AC3 (classification leg)**: strict before/after improvement measured on the same frozen set (0.2 → 1.0). Prompt baselines are pinned: baseline = `git show b4be4da:backend/pipeline/task_understanding.py` prompt block, sha256 prefix `9298015c36fa6d2b`; candidate sha256 prefix `b278c34721b22847`. The only prose delta is the `clarification_required` rule rewrite (missing model identity alone is not a clarification reason; public facts/purchase policy/general capability/evidence-backed comparison route to retrieval) plus 5 frozen judgment examples mirroring exactly these cases. **No prompt wording was changed in R3** — the R2 candidate prompt is byte-identical (git diff empty for `backend/pipeline/task_understanding.py`).
- Test assertions now encode these gates mechanically (`AC1_POSITIVE_STANDARD_GATE = 0.9`, strict improvement, AC2 equality, fail-closed authority/denominator checks) replacing the R2 `positive_standard_rate is None` tautology.

## 5. Retrieval / answer / citation integrity (AC3 preservation leg)

Deterministic, unchanged-code suites on the candidate tree:

- `tests/pipeline` full directory: **854 passed, 1 skipped** (the skip is this replay without `ISSUE118_LIVE_REPLAY=1`).
- Citation/product-isolation subset re-run explicitly: `test_citation_integrity.py`, `test_rag_citation_source.py` (source-type/citation rules), `test_citation_product_eligibility.py`, `test_product_resolver.py`, `test_product_boundary_retrieval.py`, `test_comparison_evidence_correctness.py` — **124 passed**. Product isolation, eligible-source gating and citation integrity contracts are untouched by the two-file diff.
- Focused: `test_issue118_clarification_calibration.py` + `test_task_understanding.py` + `test_intent.py`: 37 passed / 1 skipped.

## 6. Live end-to-end sanity pass (candidate SHA, real API)

A locally started non-production backend (compose `ask-ai-local` data layer; app built from this worktree at candidate SHA `9243135...`, `/health` reported that exact `git_sha`, app_mode=development) served the 8 frozen questions via the existing `/api/ask` SSE contract (same harness pattern as `scripts/e2e_20q.py`). Read-only: no sync triggered, no reindex, no corpus mutation.

### 6.1 Results
- 5/5 positives: **no clarification short-circuit** — routed into retrieval (the pre-fix behavior returned clarification text before any retrieval).
- 3/3 negatives: end-to-end clarification questions (selector / hardware revision / deixis) — AC2 holds through the full API surface.

### 6.2 Honest-absence behavior (observed, correct)
The local dev data layer has **zero in-service document generations** (dev Postgres: 0 documents/versions/index_generations; retrieval logged "在服代集合为空(权威:无现役知识),跳过 hybrid 检索" — the P1 fail-closed gating). The pipeline therefore returned the honest fallback ("I couldn't find relevant information in the official sources." / "暂未在官方资料中找到相关信息。") instead of fabricating subscription fees, prices or install advice. ZH query got the ZH fallback. This is the contract-required behavior when authoritative evidence is absent, demonstrated live.

### 6.3 Environment-blocked leg (explicit, not closed)
**Live retrieval→eligible-source→answer/citation parity on a populated authoritative corpus was NOT measured.** Both local Weaviate instances lack an in-service corpus (dev: 70,587 orphaned objects with no registered generation; `p1b` instance: no schema). Populating it requires a full sync/ingest (reindex), which is outside this task's bounded recovery path and explicitly out of scope. The only positive-case corpus material found locally is `website-camthink/shipping-policy` (orphaned). Consequently AC3's citation leg rests on (a) the unchanged deterministic citation-eligibility/integrity suites (§5) and (b) the §6.1/6.2 route + honest-absence observations — not on a live cited-answer replay. This is recorded as a limitation, not passed off as measured.

## 7. Limitations
- n=5 positives / n=3 negatives: the frozen calibration set only; no claim beyond it.
- Single-provider (model `deepseek-v4-flash`, temperature=0); routing robustness across other providers is untested here.
- One baseline run flip (`en_australia`) across runs shows residual provider nondeterminism; the after-rate was stable at 5/5 in both runs.
- Subscription and vehicle mappings carry documented honest-absence caveats (§3.1, §3.5); A may re-bucket them — the fail-closed denominator logic handles that mechanically.
- Live cited-answer replay on a populated corpus: blocked (§6.3).
