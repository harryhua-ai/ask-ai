# Issue #105 Execution (R2) — commerce metadata freshness along the REAL connector paths

- Claim: `harryhua-ai-20260922T055616-f5e6c1ac` (branch `agent/105/984124c3`)
- Execution base: `926dfb7a08bf506a635a259a41b9a60ebfdb62b1` (frozen main, exact)
- R1 candidate (reviewed, REQUEST_CHANGES): `1bd54ab0bbde5289752b3a9470bda07d39ed510e`
- R2 implementation: `ce3dbfa`(R1, retained: metadata-only commerce projection) + R2 commits (see PR head = exact Candidate SHA)
- Authority: implementation allowed; candidate only — no deploy, no production mutation
- Review being remediated: PR #109 durable review `5772503175` (Role A, REQUEST_CHANGES, 2 blockers)
- Parent production evidence: #28 comment `5771553047` (identities `5110:5950` / `5110:5951`)

## 0. REVIEW_1 remediation summary

| Blocker | Resolution |
|---------|-----------|
| B1: RED used a synthetic state (`VARIANT_CONTENT` + hand-changed `stock_status`); real connector puts stock/price/sale/qty in content ⇒ those changes are `CONTENT_CHANGED`, not `METADATA_CHANGED`; reconcile the production repro against the true classifier authority | Production forensics performed read-only (§1): the real path for `5110:5950/5951` is **`CONTENT_CHANGED`**, and the true root cause is that **the activation path never writes `documents.metadata_` for existing rows** — fixed (§3 Fix-1). Test suite rewritten: **all** builder tests now feed real `_variation_to_document` output (mock HTTP, zero network, zero synthetic content states) and cover both natural classes (§4) |
| B2: metadata-only serving update failed open (exception swallowed, ledger still advanced) ⇒ false convergence + non-retryable | `_apply_metadata_only` reordered fail-closed (§3 Fix-2): Weaviate objects update first, exceptions propagate **before any authority advance**; ledger/version-hash/chunk-copies commit only after serving success; next normal sync reclassifies `METADATA_CHANGED` and retries. Failure-injection regression added (§4 T6) |

R1's metadata-only commerce projection (`_commerce_props` on serving objects + chunk copies, explicit `stock_quantity` honest-absence clear, `commerce_synced_at` from connector `date_modified`) is **retained** — it remains the correct convergence mechanism for the metadata-only natural class, now proven with real connector documents (§4 T2).

## 1. Production forensics (read-only, 2026-09-22) — the REAL path and root cause

Queries against production `documents` + `document_versions` for the repro identities:

| source_id | row JSONB `stock_status` | row JSONB `date_modified` | row/content_hash | versions |
|---|---|---|---|---|
| `woocommerce-mall/5110/5950` | `instock` | `2026-09-18T14:02:32` | `1233ac443ffb5b31…` (= v2) | v1 `8bad56f9…` (09-18, superseded) → v2 `1233ac44…` (09-21 20:25, active) |
| `woocommerce-mall/5110:5951` | `instock` | `2026-09-18T14:02:32` | `71b08703141de2a2…` (= v2) | v1 `7eada0d8…` (09-18, superseded) → v2 `71b08703…` (09-21 20:25, active) |

Reading with the classifier's true authority (`DocumentVersion.content_hash` / `metadata_hash`, exactly as Role A required):

1. Store flipped the variations `outofstock` at `2026-09-21T17:31:44` (Store `date_modified`, wave evidence). The connector writes stock into the retrievable text (`Stock:` line) ⇒ the 09-21 20:25 sync took **`CONTENT_CHANGED`** and activated v2 with the outofstock content hash.
2. **The activation transaction synced only `content_hash/chunk_count/title/url` onto the documents row** (`_build_and_activate` writes `metadata_` solely on the new-row branch; `lifecycle.activate_document_version` docstring + code confirm the four-field sync set). The row JSONB therefore still carries **v1-era** `stock_status=instock` / `date_modified=2026-09-18T14:02:32` while the row's `content_hash` is already v2.
3. v2's `metadata_hash` was computed from the incoming (fresh) metadata, so every later sync compares equal on both hashes ⇒ **`UNCHANGED` forever** ⇒ the ledger-row commerce truth never converges. This reproduces the entire production observation (successful re-syncs, "126 unchanged", stale `stock_status`) **without** involving the metadata-only path.

Conclusion: R1's RCA attributed the production incident to the wrong path. The production root cause is the activation-path row-JSONB lag (Fix-1). The metadata-only serving-commerce gap (R1's finding) is a real but **separate** convergence hole on the `purchasable`/`on_sale`/`permalink`/`date_modified` natural class — its fix is retained and now covered by real-connector regressions.

## 2. Code ownership (mechanically confirmed from main, per path)

- `scripts/sync.py:_sync_one` → `fetch_changes(since)` → `GenerationBuilder.build_generation` → `classify_docs` → `lifecycle.classify_change(doc_row, version_row, content_hash, meta_hash)` (compares `DocumentVersion.content_hash` then `DocumentVersion.metadata_hash`; no sync-side pre-filter).
- **CONTENT_CHANGED path**: `_build_and_activate` — version row gets fresh content/metadata hashes; Weaviate objects + `DocumentVersionChunk.props` rebuilt via `_build_props` (commerce included); **documents row JSONB not synced for existing rows ⇒ Fix-1**.
- **METADATA_CHANGED path**: `_apply_metadata_only` — R1 commerce projection retained; **failure semantics were fail-open ⇒ Fix-2**.
- Connector: `_variation_to_document` — fields in retrievable text (⇒ content-hash-changing): `sku`, `price`, `regular_price` (when ≠ price), `sale_price` (when ≠ price), `stock_status`, `stock_quantity` (when not None), attributes; fields outside text (⇒ metadata-only class): `purchasable`, `on_sale`, `permalink`, `date_modified`.

## 3. GREEN design (both fixes; frozen semantics preserved)

**Fix-1 — activation path converges the ledger row** (`_build_and_activate`, existing-row branch):
`doc_row.metadata_ = dict(p.doc.metadata)` plus `product` / `branch` / `source_type` — the same row-truth field set the metadata-only path already writes (title/url/content_hash/chunk_count were already synced via `activate_document_version`). One transaction with version activation: serving rebuild and ledger row converge atomically.

**Fix-2 — metadata-only fail-closed/retryable** (`_apply_metadata_only`):
Order is now serving-first: Weaviate object merge-update runs **without** a swallowing handler; any exception propagates out of `build_generation` (existing round fail-closed semantics — `SyncLog failed`, window not advanced) **before** the ledger transaction. Only after serving success does the single transaction update `documents.metadata_`, `DocumentVersion.metadata_hash`, and chunk-copy props. A failed round advances no authority ⇒ the next normal sync reclassifies `METADATA_CHANGED` and retries to full convergence. The old "账本先行,残留下轮自愈" comment was removed together with its behavior (it recorded false convergence and could never self-heal once metadata stopped changing).

No connector change; no schema change; no prompt/rerank/citation/retrieval change; no reindex; no manual data path; commerce props vocabulary unchanged (`COMMERCE_PROPS`); `commerce_synced_at` remains mapped from connector `date_modified` (Store snapshot truth, never fabricated).

## 4. RED → GREEN evidence (all builder tests use real connector output)

Suite `tests/pipeline/test_issue105_commerce_metadata_convergence.py` (7 tests). Documents are produced by the **real `_variation_to_document`** through mocked HTTP (same idiom as `tests/connectors/test_woocommerce_variations.py`); no test constructs a content/metadata state by hand.

- **T1 premise (unit, passes on base and candidate)** — `test_content_equality_does_not_imply_commerce_metadata_equality`: real payloads show `purchasable`/`on_sale`/`permalink`/`date_modified` changes keep `content_hash` identical, while a `stock_status` change necessarily changes it. Both natural classes established from connector semantics.
- **T2 metadata-only natural class** — `test_metadata_only_natural_class_converges_serving_and_ledger`: same-hash commerce change ⇒ `METADATA_CHANGED`, zero re-embed, zero version fork; serving commerce props (`purchasable`/`on_sale`/`commerce_synced_at`), ledger row, and chunk copies all converge.
- **T3 stock class (RED on R1 candidate, GREEN after Fix-1)** — `test_content_changed_stock_class_converges_ledger_and_serving`: real stock_status flip ⇒ `CONTENT_CHANGED` ⇒ re-embed + v2; serving converges via rebuild **and `documents.metadata_` now converges** (RED on R1 tree: `assert 'instock' == 'outofstock'` — row JSONB frozen at v1).
- **T4 price/sale/qty class** — `test_content_changed_price_sale_qty_class_converges`: real price/sale/on_sale/quantity change ⇒ `CONTENT_CHANGED`; ledger + serving converge on all fields incl. `commerce_synced_at`.
- **T5 production shape** — `test_production_shape_stock_flip_then_repeat_sync_stays_converged`: ingest(instock) → flip(outofstock) → repeat(UNCHANGED); row JSONB converges at the flip round and does not regress — the exact incident timeline, guarded permanently.
- **T6 blocker-2 failure injection (RED on R1 candidate, GREEN after Fix-2)** — `test_metadata_only_serving_failure_is_fail_closed_and_retryable`: injected `collection.data.update` outage ⇒ round raises; `DocumentVersion.metadata_hash`, row JSONB, chunk copies **all unadvanced** (no false convergence); second normal sync reclassifies `METADATA_CHANGED`, retries, converges serving + ledger + chunk copies; zero embed and one version across both rounds.
- **T7 idempotency guard** — `test_repeat_sync_idempotent_after_convergence`: post-convergence repeat ⇒ `UNCHANGED`, zero writes.

R2 RED (recorded on the R1 candidate tree before these fixes): T3/T4/T5 failed on the row-JSONB assertions (root cause), T6 failed on `pytest.raises` (fail-open behavior). T1/T2/T7 passed (R1 fix retained and correct for its class).

## 5. Regression battery

| # | Suite | Result |
|---|-------|--------|
| 1 | #105 focused R2 | 7/7 passed (4/7 were RED on the R1 tree pre-fix) |
| 2 | `tests/pipeline/` + `tests/api/admin/test_trackb_composition_u28_u31.py` | 830 passed, 0 failed |
| 3 | Woo variation + commerce migration + generation-builder + issue94 combos | passed (22/22 combined run) |
| 4 | **Broad full suite, pristine-base diff** (identical venv/env, complete logs) | base `926dfb7a`: 4 failed / 3078 passed / 0 errors — candidate R2: **4 failed / 3086 passed / 0 errors**; failure sets **item-for-item identical** (known baseline: `gap_export`×2, `gap_observation`×1, `tech_answer_gaps`×1); delta = +8 passed (7 new focused tests + 1 environment skip difference), **zero new failures** |
| 5 | scope-check + preserve | `ght scope-check 105` pass / 0 violations; preserve ACTIVE |

Process honesty notes: an R1-era broad attempt was invalidated by concurrent pytest runs sharing `ask_ai_test` PG/Weaviate (cross-contaminated generation ordinals) — all R2 runs executed exclusively. A worktree-local model-cache symlink pitfall (nested `models/models`) produced transient bge/lifespan errors in one R1 run — environment, not code; the R2 full-suite log shows zero such errors. A test-only ordering bug (UUID-PK `versions[1]` nondeterminism in my own helper) was fixed to order by `version_seq`.

## 6. Scope-check & boundaries

`ght scope-check 105` → pass, 0 violations. Frozen boundaries untouched: variation identity `{product_id}:{variation_id}`, parent documents, endpoint-truth-only variations, no Cartesian synthesis, product isolation, citation integrity, retrieval fail-closed, prompt/rerank semantics, no hard-coded store/product truth in code (probe fixture values are generic). No reindex, no manual SQL, no vector-DB surgery, no deploy, no production mutation (production access this round = the read-only forensic queries in §1, as required by the review).

## 7. Remaining limitations

1. Convergence requires the incremental path to **see** the change (`fetch_changes` must return the product); Store-API-side payload staleness remains out of scope. AC6 production acceptance (post-merge/deploy, normal Woo re-sync on `5110:5950/5951`) will verify end-to-end: after Fix-1 the next content-changed or metadata-changed round converges the row; for the current production rows specifically, the *first* post-deploy sync will classify `UNCHANGED` on both hashes — **note**: their ledger JSONB is stale while their version hashes are current, so convergence for these two identities requires the row-JSONB repair surface (deploy-time migration or a Role A-authorized correction) rather than the incremental classifier, which cannot see a row/version divergence it does not compare. This is flagged honestly for the AC6 plan.
2. The four known-baseline failures (`gap_export`×2 / `gap_observation` / `tech_answer_gaps`) pre-date this candidate (proven at pristine base) — proposed for hygiene triage.
