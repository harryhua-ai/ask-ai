# Issue #105 Execution (R3) — commerce metadata freshness along the REAL connector paths

- Claim: `harryhua-ai-20260922T055616-f5e6c1ac` (branch `agent/105/984124c3`)
- Execution base: `926dfb7a08bf506a635a259a41b9a60ebfdb62b1` (frozen main, exact)
- Lineage: `ce3dbfa` (R1 implementation) → `1bd54ab` (R1 candidate, reviewed REQUEST_CHANGES) → `dae3066` (R2 candidate, REVIEW_1 blockers passed, REVIEW_2 REQUEST_CHANGES) → **R3 candidate = current PR head (exact SHA in PR description)**
- Authority: implementation allowed; candidate only — no deploy, no production mutation
- Reviews remediated: PR #109 `5772503175` (REVIEW_1, 2 blockers — closed) · `5773201820` (REVIEW_2, AC6 blocker — closed in R3)
- Parent production evidence: #28 comment `5771553047` (identities `5110:5950` / `5110:5951`)

## 0. R3 — REVIEW_2 remediation: generic mirror-drift reconciliation (AC6)

**Problem (proven production residual shape).** For the existing repro identities the
active `DocumentVersion` hashes are current v2 truth and the row's `content_hash` is v2,
but the row JSONB is stale v1 truth. Any normal sync receiving the same v2 Store document
compares equal on both version hashes ⇒ `UNCHANGED` ⇒ never `CONTENT_CHANGED`, never
`METADATA_CHANGED` ⇒ `documents.metadata_` never repaired. R2 could only prevent future
divergence; it could not heal existing rows.

**Fix (bounded, generic).** In `GenerationBuilder.build_generation`, a doc classified
`UNCHANGED` is additionally checked with `_row_mirror_drifted(doc_row, doc)`: when the
row's mirror fields (`metadata_`, `product`, `branch`, `source_type` — the exact row-truth
set the activation and metadata-only paths write) diverge from the incoming connector
truth, the doc is routed into the **existing** `_apply_metadata_only` reconciliation
instead of being counted unchanged. Properties, by construction of that path:

- no new `DocumentVersion`, no new generation, no re-embed (zero embed);
- serving/chunk drift, if any, heals through the same **fail-closed, retry-safe**
  semantics fixed in R2 (serving-first, no authority advance on failure) — no new
  fail-open anywhere;
- idempotent: once the row converges, the doc classifies truly `UNCHANGED` with zero writes;
- generic for every source type (no woo-specific, no hard-coded identities); classifier
  vocabulary untouched (no new `ChangeClass` — the frozen FC-6 word list is intact);
- false-positive safety: the predicate is deliberately loose (plain dict/field compare);
  a spurious hit only routes a doc through an idempotent reconciliation that rewrites
  identical values.

**RED → GREEN (T8, real-connector documents throughout).**
`test_historical_mirror_drift_reconciled_by_normal_sync` reproduces the review recipe:
(1) ingest v1 (instock); (2) normally activate v2 (outofstock) — version hashes and
serving props are v2; (3) simulate the historical persistent state by restoring **only**
`documents.metadata_` to v1 (row-state simulation of what the old code already produced —
not a faked connector output); (4) feed the same real v2 document. RED on the R2 tree:
round counted `unchanged_docs == [SID]` and the row stayed stale. GREEN: routed to
metadata reconciliation (`metadata_docs == [SID]`), row mirror converges to v2, zero
embed, two versions before/after, generation count unchanged, serving and chunk truth
unchanged (no degradation); (5) same v2 again ⇒ true `UNCHANGED`, zero writes.

**AC6 consequence.** After this candidate is deployed, ONE normal canonical WooCommerce
re-sync of the current production rows (hash-equal incoming, stale row mirror) enters the
reconciliation path and converges Store truth → `DocumentVersion` → documents row →
serving/vector props. No reliance on a future Store change, manual repair, manual SQL,
`--reindex`, or direct vector mutation.

## 0b. REVIEW_1 remediation summary (retained, unchanged in R3)

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
- **UNCHANGED path (R3, Fix-3)**: `_row_mirror_drifted(doc_row, doc)` guard in `build_generation` routes historical row-mirror drift into the same `_apply_metadata_only` reconciliation (bounded; no new `ChangeClass`; classifier vocabulary untouched).
- Connector: `_variation_to_document` — fields in retrievable text (⇒ content-hash-changing): `sku`, `price`, `regular_price` (when ≠ price), `sale_price` (when ≠ price), `stock_status`, `stock_quantity` (when not None), attributes; fields outside text (⇒ metadata-only class): `purchasable`, `on_sale`, `permalink`, `date_modified`.

## 3. GREEN design (both fixes; frozen semantics preserved)

**Fix-1 — activation path converges the ledger row** (`_build_and_activate`, existing-row branch):
`doc_row.metadata_ = dict(p.doc.metadata)` plus `product` / `branch` / `source_type` — the same row-truth field set the metadata-only path already writes (title/url/content_hash/chunk_count were already synced via `activate_document_version`). One transaction with version activation: serving rebuild and ledger row converge atomically.

**Fix-2 — metadata-only fail-closed/retryable** (`_apply_metadata_only`):
Order is now serving-first: Weaviate object merge-update runs **without** a swallowing handler; any exception propagates out of `build_generation` (existing round fail-closed semantics — `SyncLog failed`, window not advanced) **before** the ledger transaction. Only after serving success does the single transaction update `documents.metadata_`, `DocumentVersion.metadata_hash`, and chunk-copy props. A failed round advances no authority ⇒ the next normal sync reclassifies `METADATA_CHANGED` and retries to full convergence. The old "账本先行,残留下轮自愈" comment was removed together with its behavior (it recorded false convergence and could never self-heal once metadata stopped changing).

No connector change; no schema change; no prompt/rerank/citation/retrieval change; no reindex; no manual data path; commerce props vocabulary unchanged (`COMMERCE_PROPS`); `commerce_synced_at` remains mapped from connector `date_modified` (Store snapshot truth, never fabricated).

## 4. RED → GREEN evidence (all builder tests use real connector output)

Suite `tests/pipeline/test_issue105_commerce_metadata_convergence.py` (**8 tests**). Documents are produced by the **real `_variation_to_document`** through mocked HTTP (same idiom as `tests/connectors/test_woocommerce_variations.py`); no test constructs a content/metadata state by hand.

- **T1 premise (unit)** — `test_content_equality_does_not_imply_commerce_metadata_equality`: real payloads show `purchasable`/`on_sale`/`permalink`/`date_modified` changes keep `content_hash` identical, while a `stock_status` change necessarily changes it — both natural classes established from connector semantics.
- **T2 metadata-only natural class** — `test_metadata_only_natural_class_converges_serving_and_ledger`: same-hash commerce change ⇒ `METADATA_CHANGED`, zero re-embed, zero version fork; serving commerce props (`purchasable`/`on_sale`/`commerce_synced_at`), ledger row, chunk copies all converge.
- **T3 stock class (RED on R1, GREEN after R2 Fix-1)** — `test_content_changed_stock_class_converges_ledger_and_serving`: real stock_status flip ⇒ `CONTENT_CHANGED` ⇒ re-embed + v2; serving converges via rebuild **and `documents.metadata_` converges** (RED: `assert 'instock' == 'outofstock'` — row JSONB frozen at v1).
- **T4 price/sale/qty class** — `test_content_changed_price_sale_qty_class_converges`: real price/sale/on_sale/quantity change ⇒ `CONTENT_CHANGED`; ledger + serving converge on all fields incl. `commerce_synced_at`.
- **T5 production shape** — `test_production_shape_stock_flip_then_repeat_sync_stays_converged`: ingest(instock) → flip(outofstock) → repeat(UNCHANGED); row JSONB converges at the flip round and does not regress — the exact incident timeline, guarded permanently.
- **T6 blocker-2 failure injection (RED on R1, GREEN after R2 Fix-2)** — `test_metadata_only_serving_failure_is_fail_closed_and_retryable`: injected `collection.data.update` outage ⇒ round raises; `DocumentVersion.metadata_hash`, row JSONB, chunk copies all unadvanced (no false convergence); second normal sync reclassifies `METADATA_CHANGED`, retries, converges three-way; zero embed, one version across both rounds.
- **T7 idempotency guard** — `test_repeat_sync_idempotent_after_convergence`: post-convergence repeat ⇒ `UNCHANGED`, zero writes.
- **T8 mirror-drift reconciliation (RED on R2, GREEN after R3 Fix-3)** — `test_historical_mirror_drift_reconciled_by_normal_sync`: the review's five-step recipe (§0).

RED records: on the R1 tree T3/T4/T5 failed on row-JSONB assertions and T6 on `pytest.raises` (fail-open); on the R2 tree T8 failed with `unchanged_docs == [SID]` on the mirror-drift round (AC6 residual). All 8 GREEN on the R3 candidate.

## 5. Regression battery (R3)

| # | Suite | Result |
|---|-------|--------|
| 1 | #105 focused | **8/8 passed** (T8 RED on R2 tree pre-fix) |
| 2 | `tests/connectors/test_woocommerce_variations.py` + `tests/scripts/test_migrate_add_commerce_variation_props.py` + `tests/pipeline/` + `tests/services/` + `tests/retrieval/` + `tests/api/admin/test_trackb_composition_u28_u31.py` | **1333 passed, 0 failed** |
| 3 | **Broad full suite, pristine-base diff** (identical venv/env, complete logs) | base `926dfb7a`: 4 failed / 3078 passed / 0 errors — candidate R3: **4 failed / 3087 passed / 0 errors**; failure sets **item-for-item identical** (known baseline: `gap_export`×2, `gap_observation`×1, `tech_answer_gaps`×1); delta = +9 passed (8 new focused tests + 1 environment skip difference), **zero new failures** |
| 4 | scope-check + preserve | `ght scope-check 105` pass / 0 violations; preserve ACTIVE |

Process honesty notes: an R1-era broad attempt was invalidated by concurrent pytest runs sharing `ask_ai_test` PG/Weaviate (cross-contaminated generation ordinals) — all later runs executed exclusively. A worktree-local model-cache symlink pitfall (nested `models/models`) produced transient bge/lifespan errors in one R1 run — environment, not code; the R3 full-suite log shows zero such errors. A test-only ordering bug (UUID-PK `versions[1]` nondeterminism in my own helper) was fixed to order by `version_seq`.

## 6. Scope-check & boundaries

`ght scope-check 105` → pass, 0 violations. Frozen boundaries untouched: variation identity `{product_id}:{variation_id}`, parent documents, endpoint-truth-only variations, no Cartesian synthesis, product isolation, citation integrity, retrieval fail-closed, prompt/rerank semantics, no hard-coded store/product truth in code (probe fixture values are generic). No reindex, no manual SQL, no vector-DB surgery, no deploy, no production mutation (production access this round = the read-only forensic queries in §1, as required by the review).

## 7. Remaining limitations

1. Convergence requires the incremental path to **see** the document (`fetch_changes` must return it); Store-API-side payload staleness remains out of scope. With R3 in place, AC6 is satisfiable by ONE normal canonical re-sync: the current production rows are exactly the mirror-drift shape (hash-equal incoming, stale row JSONB) ⇒ the reconciliation path fires and converges Store truth → `DocumentVersion` → documents row → serving/vector props, with no future-Store-change dependency, no manual repair/SQL, no `--reindex`, no direct vector mutation.
2. The four known-baseline failures (`gap_export`×2 / `gap_observation` / `tech_answer_gaps`) pre-date this candidate (proven at pristine base) — proposed for hygiene triage.
