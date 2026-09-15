# Issue #77 — Role B R2 Report: Code-Oriented Competitive Gate + Fixture Correction Path

**Status:** `ISSUE_77_REMEDIATION_R2 = CANDIDATE READY` (unmerged; Role A FINAL PASS review)
**Baseline:** `origin/main` = `f4e67515af810840aa10fa800f0203c2ba290df0` (re-fetched, unchanged)
**Previous implementation:** `3948be2` (report tip `26dbc04`)
**R2 candidate SHA:** `07d1308` · **pushed tip:** `07d1308` on `candidate/issue-77-evidence-eligibility-20260915`

---

## 1. BLOCKER 1 — code-oriented competitive gate (resolved)

**Reuse, not new:** the composition is now gated on the repository's existing deterministic predicate — a module alias `_is_code_oriented_query = _is_code_oriented_comparison` (rag.py; vocabulary `_CODE_SINGLE_TOKENS`/`_CODE_PHRASES`/`_CODE_CJK_SUBSTRINGS` remains the single source, zero duplication, zero new classifier).

All four composition sites (normal-path answer + stream, fallback answer + stream) are gated:

```python
code_oriented = _is_code_oriented_query(query)
if cmp_stage_info is None and not code_oriented:
    reranked = _compose_user_facing_evidence(...)
```

```python
if _is_code_oriented_query(query):
    fallback = fused[: self._top_k] if fused else []          # competitive raw order
else:
    fallback = _compose_user_facing_evidence(fused, None, self._top_k, None)
```

Resulting semantics:
- **A** ordinary factual query + mixed pool → user-facing-first composition (unchanged from R1);
- **B** explicit code/SDK/API/firmware/driver query → composition identity; code competes by the existing relevance order (survivors order; comparison-mode Rev2 semantics untouched — the same predicate drives both, from one vocabulary);
- **C** code-only pool → identity (no user-facing candidates);
- **D** comparison path untouched.

**RED→GREEN (A/B against pre-R2 candidate `3948be2`):**
- `test_red_b1_code_oriented_query_keeps_relevance_order`: **FAIL on 3948be2** (official heading front-run; only 9 code retained) → **PASS** (first 10 = code in pool order, contiguous, 10/10 retained; any non-code presence limited to the pre-existing INC-5 required-slot front-load, ≤1 seat).
- `test_red_b2_code_oriented_fallback_keeps_raw_order`: **FAIL on 3948be2** → **PASS** (fallback keeps raw competitive order; official not promoted).
- Ordinary-query preservation: RED-1 remains GREEN (user-facing-first on ordinary queries).

## 2. BLOCKER 2 — already-serving G-04 fixtures: investigation verdict + proven correction path

**Investigation (repository code, no guessing):** existing sync/reindex does **NOT** remove still-present-but-excluded fixtures — verdict **(B) left serving**:

1. Deletions originate **only** from `connector.fetch_deleted(since)` (scripts/sync.py:1164 → tombstone via `lifecycle.tombstone_document`; "墓碑文档即时退出服务集").
2. github/local_git `fetch_deleted` = `git log --diff-filter=D` — reports only files **git-deleted upstream**; a file still present in the clone but newly excluded by `exclude_dirs` produces **no deletion signal** (and the deleted-file loop itself `continue`s on `should_exclude`, github.py:437).
3. github/local_git connectors have **no** `authoritative_source_ids` membership reconciliation (only web_crawl has it).
4. Generation swap: absent documents enter `MISSING_CANDIDATE`, which **remains in SERVING** during the frozen absence-grace (document_lifecycle.py:58-60, 274-277); absence *confirmation* is deferred (P2).

**Narrowest accepted correction seam (existing lifecycle/repair machinery — no scope expansion):** `CorpusRepairTool.plan(source, membership=<authoritative post-exclusion enumeration>)` → `RETIRE_DELETED_DOCUMENT` entries for every path absent from membership ("path absent from authoritative membership" — the same evidence standard as sync reconciliation) → `apply()` deletes the ledger row **and** the deterministic-UUID Weaviate vectors. Neighbor content produces no entries.

**Contract tests added** (`tests/services/test_corpus_repair.py`, real `CorpusRepairTool` + real `ExclusionPolicy` + real DB fixtures):
- `test_issue77_eval_boundary_via_existing_exclude_dirs` — `exclude_dirs+["eval"]` excludes `eval/fixtures/**` and `eval/cases/**`; `src/lib.rs`/`README.md` unaffected.
- `test_issue77_membership_retire_removes_serving_fixture_keeps_neighbor` — seeded ledger with the serving eval fixture (chunk_count=2) + neighbor: plan(membership) yields `RETIRE_DELETED_DOCUMENT` **only** for the fixture; apply deletes the ledger row + exactly the fixture's 2 deterministic UUIDs; the neighbor row survives.

**Exact r4 operational step (documented; NOT executed — production mutation forbidden):**
1. `neomind-local` source config: `exclude_dirs` += `"eval"` (Admin data-source edit; existing mechanism).
2. Authorized source-scoped re-sync → connector full enumeration = authoritative membership (or directly run the repair tool with the connector enumeration as membership).
3. `CorpusRepairTool.plan("neomind-local", membership=<enumeration>)` → `apply(plan)` → eval/** exits serving truth deterministically; verify zero serving eval chunks (ledger count + vector scan for `neomind-local/main/eval/`).
4. Physical residue cleanup via the existing GC (retired retention window).

## 3. #78 boundary (frozen) — verification

Zero diff lines against #78's surface: `INTENT_BOOST_FILTERS` values, `search_bucket` semantics/limits, `boost:0`/`boost:1` attribution, candidate admission. CONTROL-4 (product intent still exactly one `search_bucket` call) green. **Mechanical stacked verification repeated after R2**: temp stack (#77 R2 + merge of `origin/candidate/issue-78-recall-remediation-20260915`) → zero conflicts; #78 RED suite + #77 suite + rag + parity + comparison = **78 passed**; full pipeline/retrieval = **824 passed, 0 failed**. Chain: #78 admission → #77 eligibility/composition → official evidence survives → code-oriented query competitive → fixtures excluded from serving truth (post-r4-op). Temp branch deleted after verification.

## 4. Regression counts (post-R2)

| Run | Result |
|---|---|
| #77 focused suite (11 tests: RED-1/2/3, RED-B1/B2, RED-4, CONTROL-1..4) | **11 passed** |
| `tests/pipeline` + `tests/retrieval` + `tests/services` | **1154 passed, 0 failed** |
| `tests/api db auth llm connectors utils benchmark scripts project_automation` | **1346 passed, 5 skipped, 0 failed** |
| **Total (CI-practical, non-e2e)** | **2500 passed / 5 skipped / 0 failed** |
| Stacked focused / stacked pipeline+retrieval | **78 passed / 824 passed** |

Pre-existing environmental exclusions (A/B-proven on clean baseline in the R1 report; re-confirmed this round): standalone corpus-repair `TEST_DATABASE_URL` KeyError (full-suite ordering injects it), `test_lifespan_smoke` + combined `runtime+embedder` hangs, e2e (live services). No NEW unrelated failures observed post-cleanup.

## 5. Scope audit

Changed files (3): `backend/pipeline/rag.py` (predicate alias + 4 gate sites), `tests/pipeline/test_issue77_evidence_eligibility.py` (+RED-B1/B2), `tests/services/test_corpus_repair.py` (+2 contract tests) (+ this report). Untouched: reranker/threshold/top_k/RRF/symbol/query-rewrite/#78 surfaces/`INTENT_BOOST_FILTERS`/`search_bucket`/citation whitelists/prompt/content/production.

## 6. PROVEN / INFERRED / UNPROVEN

| Claim | Level |
|---|---|
| B1 gate RED→GREEN (A/B vs 3948be2) | PROVEN |
| B2 verdict: existing sync leaves still-present excluded files serving | PROVEN (code paths cited §2.1-4) |
| Membership-retire seam removes serving fixture + keeps neighbor | PROVEN (contract tests, real tool) |
| r4 operational effect on production | UNPROVEN until executed (post-#75) |
| Composition latency impact | INFERRED negligible (pure in-process reorder) |

**Explicit confirmations:** no merge · no deploy · no production config mutation · no production re-sync/reindex · no tag · no Wiki/content change.

**STOP.** Role A FINAL PASS review next.
