# Issue #77 — Role B Implementation Report: Evidence Eligibility / Composition Remediation

**Status:** `ISSUE_77_REMEDIATION = CANDIDATE READY` (unmerged; Role A FINAL PASS review required)
**Baseline:** `origin/main` = `f4e67515af810840aa10fa800f0203c2ba290df0` (verified after `git fetch origin`)
**Candidate branch:** `candidate/issue-77-evidence-eligibility-20260915` — fresh worktree `ask-ai-wt-77`, clean at `f4e6751` before edits
**Candidate implementation SHA:** `3948be2`; pushed tip: this branch (tip updated with this report commit)
**Dependency on #78:** **FROZEN INTERFACE / SEQUENTIAL (no compile dependency)** — see §2

---

## 1. Engineering root-cause confirmation (baseline `f4e6751`)

Re-verified against the baseline before implementation, consistent with the accepted RCA:

- `evidence_matches_slot` (evidence_selection.py) gates `PRODUCT_SPEC` only on `source_type ∈ PUBLIC_SOURCE_TYPES` — and `"github"` is in that whitelist, so a firmware `.c` chunk satisfies a user-facing product-spec slot (production proof: `4823df8b…` PRODUCT_SLOT `covered:true` by `api_device_module.c`). [PROVEN]
- Normal-path evidence set = rerank survivors (top_k=10 by weighted score) — a threshold-passing user-facing chunk ranked below the code wall is displaced; nothing downstream can re-admit it. [PROVEN]
- Fallback (`rerank 滤光 → fused[:top_k]`) takes the raw fused order — user-facing chunks buried by fused order stay buried. [PROVEN]
- Connector `ExclusionPolicy` honors per-source `exclude_dirs` at any path level; the NeoMind production source config (`exclude_dirs: [".github","docs"]`) does not boundary `eval/` — fixture JSON remains ingestible. [PROVEN, production config read 2026-09-15]

## 2. Dependency classification vs #78 (e936587 / bd98bcc)

**FROZEN INTERFACE + SEQUENTIAL merge order; NO compile/test dependency.**
- #78 = candidate *admission* (recall): `INTENT_BOOST_FILTERS` multi-bucket, `search_bucket` hybrid mode, `boost:i` attribution — untouched by #77 (verified: zero diff lines in those regions).
- #77 = post-admission *eligibility/composition* (`evidence_selection.py` slot truth; normal-path + fallback composition in `rag.py`).
- #77 candidate is based on `f4e6751` (main) and compiles/tests green WITHOUT #78 code. #78's implementation commit `e936587` is itself a direct child of `f4e6751` (stacked on main).
- **Integration ordering requirement:** merge #78 first, then #77 (or rebase #77 onto #78). Mechanical combined verification performed (§8): a local temp stack (#77 candidate + merge of origin `candidate/issue-78-recall-remediation-20260915`) auto-merged with **zero conflicts** and passed both suites plus the full pipeline/retrieval tree (822 passed).

## 3. Implementation HOW (exact surfaces)

**E — class-truthful slot coverage** (`backend/pipeline/evidence_selection.py`):
`evidence_matches_slot` now returns False for `PRODUCT_SPEC`/`SOLUTION_GUIDE` slots when the candidate's persisted `chunk_type == "code"` (getattr-safe, preserving the predicate's documented total/never-raises contract). Generic metadata rule — the same non-code/code structural fact the comparison path's tier1/tier2 uses; no vocabulary, no example specificity. `STORE_OFFICIAL` (woocommerce-only) and `CASE_EVIDENCE` (filesystem-only) were already class-closed.

**B — ordinary-query evidence composition** (`backend/pipeline/rag.py`, new `_compose_user_facing_evidence`, applied at the same position in answer + stream, non-comparison modes only):
threshold-passing user-facing (non-code) candidates — including those above threshold but below the truncation line, read from `rerank_scored`'s existing full weighted table — take precedence in the evidence set; code backfills by existing order; evidence size stays ≤ top_k; scores/threshold/ordering machinery untouched; identity when no user-facing threshold-passers exist; F-1' R3b-promoted items (absent from pool_scores) are preserved in place. Comparison mode is excluded (it already has per-target C1/C2 tier quotas).

**D — fallback eligibility** (`rag.py`, both fallback sites):
the fallback candidate set is now class-composed over the **full fused set** before the top_k cap (user-facing-first in fused order, code backfills) — instead of pre-truncating to `fused[:10]` and then burying deeper user-facing candidates. No threshold promotion is introduced: fallback remains below-threshold recall rescue; it merely obeys the same class boundary. Zero-change when no user-facing candidates exist in fused.

**A — fixture exclusion (existing `exclude_dirs` mechanism; zero code):**
the accepted fixture domain (`neomind-local` `eval/` tree: `eval/fixtures/*.json`, `eval/cases/**`) is boundary-able with the existing `ExclusionPolicy.exclude_dirs` — verified at the real class level (RED-4/CONTROL-3). **Operational change required (NOT executable here — production config mutation is forbidden):** add `"eval"` to `exclude_dirs` of the `neomind-local` source (currently `[".github","docs"]`), then a re-sync of that source (currently gated by #75's 413 wedge). Until then, the runtime complement is the existing U-12 per-source HISTORICAL policy channel (`knowledge_role=historical` on a fixture-only source) — also config, also untouched here.

## 4. RED evidence (baseline `f4e6751`, before implementation)

`tests/pipeline/test_issue77_evidence_eligibility.py` (real `answer()` flow with real `RerankPipeline` thresholds; scripted LLM per repo convention; scripted Weaviate boundary):

| Test | Baseline | Failure shown |
|---|---|---|
| RED-1 `test_red1_official_evidence_not_displaced_by_code` | **FAIL** | official chunk threshold-passing (0.25×1.2=0.30≥0.3) but truncated out; evidence = 10 code |
| RED-2 `test_red2_fallback_respects_same_class_boundary` | **FAIL** | all-below-threshold → fallback raw fused order buries the user-facing chunk |
| RED-3 `test_red3_code_candidate_cannot_satisfy_product_spec_slot` | **FAIL** | `evidence_matches_slot(PRODUCT_SPEC, .c chunk) == True` (class-blind) |
| RED-4 fixture mechanism | PASS (contract test) | pre-condition proven: fixture path ingestible under production config mirror; `exclude_dirs+eval` boundary works |
| CONTROL-1 code-only pool identity | PASS | composition is identity; code evidence intact |
| CONTROL-2 qualified official stays eligible | PASS | non-code official matches PRODUCT_SPEC |
| CONTROL-3 neighbors remain ingestible | PASS | crates/web/README/src unaffected by eval boundary |
| CONTROL-4 recall path unchanged | PASS | product intent still exactly one `search_bucket` call |

## 5. GREEN evidence (after implementation, same worktree)

All 8 tests above **PASS** (7-file report: `7 passed` + CONTROL-4 → final file = 8 tests, all green). Additionally:
- RED-1 asserts BOTH: official enters the evidence set AND ≥9 code chunks remain (no global code suppression).
- RED-2 asserts fallback still answers (`is_answered`) with the composed evidence.

## 6. Focused + broad regression

| Run | Result |
|---|---|
| `tests/pipeline` + `tests/retrieval` (with changes) | 815 total incl. new file — final clean runs **814-815 passed, 0 failed**; see §7 for flake A/B |
| `tests/api` + `tests/db` + 8 service/infra trees + pipeline + retrieval (full non-e2e, post-cleanup) | **2495 passed, 6 skipped, 0 failed** (114s) |
| Stacked (#77 + #78): RED suites of both + rag + parity | **47 passed** |
| Stacked: full `tests/pipeline` + `tests/retrieval` | **822 passed, 0 failed** |
| Lint | `test_issue77…` file ruff-clean; pre-existing baseline lint noise on touched files unchanged (baseline itself fails the same checks) |

## 7. Baseline A/B for excluded failures/hangs (acceptance 17)

All A/B performed via `git stash -u` ↔ `stash pop` in the same worktree:

| Symptom | With changes | Clean baseline | Verdict |
|---|---|---|---|
| `test_ingest_ledger_identity` 5× setup `KeyError (frozen os)` teardown errors | yes | **yes (identical)** | pre-existing environmental |
| `test_projection_rebuild::test_repair_unrepairable…` ordering flake | passes 3/3 isolated; failed once in a full-tree ordering | passes 3/3 isolated; full-tree ordering nondeterministic (one baseline full run: `1 failed, 4 errors`; another: clean) | pre-existing ordering/environmental |
| combined `runtime+embedder` invocation hang | yes | **yes** | pre-existing environmental |
| `test_lifespan_smoke` hang | yes | **yes** | pre-existing environmental |
| `tests/e2e` | excluded (live services) | — | policy |
| `test_rag_trace::test_answer_produces_trace_payload` (`MagicMock.threshold` vs `>=`) | initially failed → **fixed** by sanitizing non-numeric thresholds to conservative class-order mode (now passes; genuinely caused by the new code path) | n/a | fixed in-candidate |
| `test_g001_patch_system_prompt_hot_reloads` (`SimpleNamespace` lacks `chunk_type`) | initially failed → **fixed** by getattr-safe access preserving the predicate's never-raises contract (now passes) | n/a | fixed in-candidate |

## 8. Combined #78 → #77 semantics (mechanical)

Local temp stack `tmp/stacked-77-over-78-check` = #77 candidate (`3948be2`) + `git merge origin/candidate/issue-78-recall-remediation-20260915` (bd98bcc, containing e936587): **auto-merge, zero conflicts**. On the stacked tree: #78 RED suite + #77 suite + rag + parity = 47 passed; full pipeline+retrieval = 822 passed. Chain proven: #78 admits the authoritative user-facing candidate (bucket `boost:1`) → #77 recognizes it as qualified user-facing evidence (slot truth + tier composition) → code cannot satisfy/displace the role → reranker/planning/citation operate unchanged. Temp branch deleted after verification (not pushed; reproducible from the two pushed candidates).

## 9. PROVEN / INFERRED / UNPROVEN

| Claim | Level |
|---|---|
| Baseline seam facts + RED failures + GREEN passes + regression counts | PROVEN (executed) |
| Zero-conflict stack + combined suites | PROVEN (executed locally) |
| Fixture boundary via `exclude_dirs` | PROVEN at mechanism level (real `ExclusionPolicy`); production config change + effect | PROVEN mechanism / **PENDING ops execution** (config + re-sync; re-sync gated by #75) |
| Production-answer improvement | UNPROVEN until deploy + probes (post-#75) |
| Composition latency impact | INFERRED negligible (pure in-process reorder; no extra retrieval/LLM) |

## 10. Scope audit

Changed files (3): `backend/pipeline/evidence_selection.py`, `backend/pipeline/rag.py`, `tests/pipeline/test_issue77_evidence_eligibility.py` (+ this report). Verified untouched: reranker/threshold/top_k/RRF/symbol/query-rewrite/`INTENT_BOOST_FILTERS`/`search_bucket` (#78 surface)/evidence reservation logic (#77 only inherits its output)/citation whitelists/connectors/prompts/content/production.

**Explicit confirmations:** no merge to main · no deployment · no tag · no production resync/reindex · no production mutation · no Wiki/content change.

**STOP.** Role A independent review next (FINAL PASS / REWORK / integration eligibility).
