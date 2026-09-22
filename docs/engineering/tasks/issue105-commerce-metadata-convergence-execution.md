# Issue #105 Execution (R5) — commerce metadata freshness along the REAL connector paths

- Claim: `harryhua-ai-20260922T055616-f5e6c1ac` (branch `agent/105/984124c3`)
- Execution base: `926dfb7a08bf506a635a259a41b9a60ebfdb62b1` (frozen main, exact)
- Lineage: `ce3dbfa` → `1bd54ab` *(R1, SUPERSEDED)* → `dae3066` *(R2, SUPERSEDED)* → `ee5cd22` *(R3, SUPERSEDED)* → `66473df` *(R4, reachability design accepted; SUPERSEDED)* → **R5 candidate = current PR head (exact SHA in PR description)**
- Authority: implementation allowed; candidate only — no deploy, no production mutation
- Reviews remediated: PR #109 `5772503175` (REVIEW_1) · `5773201820` (REVIEW_2) · REVIEW_R3 (reachability — closed in R4) · REVIEW_R4 (hook strictness — closed in R5)
- Parent production evidence: #28 comment `5771553047` (identities `5110:5950` / `5110:5951`)

## 0. R4 — REVIEW_R3 remediation: empty-incremental reachability for mirror-drift reconciliation

**Blocker (accepted point).** R3's builder-local Fix C never fires when the canonical
round is an **empty-incremental** round: `last_success > Store date_modified` ⇒
`fetch_changes(since)` returns `[]` ⇒ no documents reach `GenerationBuilder` ⇒ the
`UNCHANGED` + `_row_mirror_drifted` branch is unreachable ⇒ existing production rows
(5110:5950/5951 shape) can never converge and AC6 stays unreachable.

**Fix (smallest generic reachability).** The canonical empty-incremental path for
`DECLARES_DELETIONS = False` connectors (fs/woo — exactly the class named in the
blocker) **already materializes a full authoritative discovery every round**:
`_handle_no_change` → `_reconcile_source_absence` → `_discover_source_docs` →
`connector.fetch_all()`. R4 reuses those already-materialized documents (zero extra
fetch):

1. `_reconcile_source_absence` now returns the discovered `docs` alongside its result
   (only on complete discovery; `[]` otherwise).
2. New `_reconcile_mirror_drift(source_id, discovery_docs, session_factory, builder)`:
   filters the discovery set to documents present in the ledger (no accidental
   ingestion of unknown ids), then runs `builder.build_generation` — where precise
   detection stays with `_row_mirror_drifted` (healthy rows = zero writes; drifted
   rows = the R2 retry-safe `_apply_metadata_only` reconciliation).
3. `_handle_no_change` invokes it **before** vector verification and records the count
   as the additive projection-repair fact `mirror_reconciled_count` in
   `delta_counts` (same convention as `ledger_rebuilt_count` — never mixed into the
   document change buckets or `items_*`).

Properties preserved: zero re-embed, zero version fork, zero new generation, no new
`ChangeClass`, no hard-coded identities, generic across every source of the covered
connector class, reconciliation failures propagate (fail-closed — the round records
`failed`, the window does not advance, the next normal sync retries). Boundary stated
honestly: connectors that self-declare deletions (git/web) do not materialize a full
discovery on empty rounds, so this hook does not extend to them — adding it there
would reintroduce the full-walk cost the SHA short-circuit exists to avoid; flagged
for Role A rather than silently expanded.

**RED → GREEN (T9, end-to-end through real `_sync_one → WooCommerce connector →
GenerationBuilder`).** `tests/scripts/test_issue105_mirror_drift_reachability.py`
builds v1 → v2 with real connector documents (real PG + real Weaviate), reverts only
`documents.metadata_` to v1 (simulating the persistent state the old code produced),
seeds `last_success` LATER than the Store `date_modified`, and mocks the Store listing
so the modified-after window returns `[]` while full discovery returns the catalog —
the exact blocker shape. RED on the R3 tree (fix removed): the round recorded plain
`no_change` (`delta_counts.mirror_reconciled_count` absent) and the row stayed stale.
GREEN: the round reports `status=success` with `mirror_reconciled_count == 1`, the row
mirror converges to v2 (`stock_status=outofstock`, `date_modified=D2`), zero embed,
two versions and unchanged generation count, serving props not degraded; the second
normal sync is a true idempotent `UNCHANGED` (`mirror_reconciled_count == 0`,
`unchanged_count == 1`, no writes).

## 0-pre. R5 — REVIEW_R4 remediation: the no-change hook is strictly mirror-drift-only

**Blocker (accepted point).** R4's `_reconcile_mirror_drift` fed **all** ledger-present
discovery docs into `build_generation`, so the no-change hook could process real
`METADATA_CHANGED` / `CONTENT_CHANGED` documents — embedding/version/generation churn
plus false `no_change` accounting.

**Fix.** `_reconcile_mirror_drift` now pre-filters each discovery doc against the exact
frozen conjunction — ledger row exists ∧ `lifecycle == ACTIVE` ∧ canonical classifier ==
`UNCHANGED` (via `lifecycle.classify_change` on the real `Document`/`DocumentVersion`
rows with the shared `incoming_metadata_hash(doc)` formula) ∧ `_row_mirror_drifted(doc_row, doc)`
— and only that bounded set reaches `builder.build_generation` (which by construction
routes it into the R2 retry-safe reconciliation). The metadata-hash formula previously
inlined in three sites (`classify_docs`, `_apply_metadata_only`, `_build_and_activate`
version creation) is consolidated into one shared helper `incoming_metadata_hash` — the
pre-filter and the classifier now share the same authoritative formula by construction.
Counting unchanged: `mirror_reconciled_count` = reconciled docs only.

**RED → GREEN (T10, four-shape sync integration).**
`test_no_change_hook_is_strictly_mirror_drift_only` seeds four real-connector variations
in one source — 5950 mirror-drift (v1→v2 activated, row JSONB-only reverted), 5951
healthy UNCHANGED, 5952 METADATA_CHANGED (same-hash purchasable flip), 5953
CONTENT_CHANGED (hash-different stock flip) — with `last_success` later than every
`date_modified` (empty incremental window) and full discovery returning all four current
payloads. RED on the R4 tree: hook processed 5952 (count `2`) and churned 5953. GREEN:
`mirror_reconciled_count == 1` (only 5950, converged to v2); 5951 row byte-identical
(zero write); 5952/5953 rows untouched by the hook (left for their normal fetch rounds,
per frozen acquisition semantics); zero embed, zero new version, zero new generation;
second sync idempotent (`mirror_reconciled_count == 0`).

## 0b. REVIEW_1/REVIEW_2 remediation summary (retained, unchanged in R5)

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
- **Empty-incremental reachability (R4, Fix-4)**: `_handle_no_change` routes the round's already-materialized authoritative discovery (fs/woo class) through `_reconcile_mirror_drift` → the same builder branch, so mirror drift converges even when `fetch_changes(since)` returns empty; count recorded as additive `mirror_reconciled_count` delta fact.
- Connector: `_variation_to_document` — fields in retrievable text (⇒ content-hash-changing): `sku`, `price`, `regular_price` (when ≠ price), `sale_price` (when ≠ price), `stock_status`, `stock_quantity` (when not None), attributes; fields outside text (⇒ metadata-only class): `purchasable`, `on_sale`, `permalink`, `date_modified`.

## 3. GREEN design (both fixes; frozen semantics preserved)

**Fix-1 — activation path converges the ledger row** (`_build_and_activate`, existing-row branch):
`doc_row.metadata_ = dict(p.doc.metadata)` plus `product` / `branch` / `source_type` — the same row-truth field set the metadata-only path already writes (title/url/content_hash/chunk_count were already synced via `activate_document_version`). One transaction with version activation: serving rebuild and ledger row converge atomically.

**Fix-2 — metadata-only fail-closed/retryable** (`_apply_metadata_only`):
Order is now serving-first: Weaviate object merge-update runs **without** a swallowing handler; any exception propagates out of `build_generation` (existing round fail-closed semantics — `SyncLog failed`, window not advanced) **before** the ledger transaction. Only after serving success does the single transaction update `documents.metadata_`, `DocumentVersion.metadata_hash`, and chunk-copy props. A failed round advances no authority ⇒ the next normal sync reclassifies `METADATA_CHANGED` and retries to full convergence. The old "账本先行,残留下轮自愈" comment was removed together with its behavior (it recorded false convergence and could never self-heal once metadata stopped changing).

No connector change; no schema change; no prompt/rerank/citation/retrieval change; no reindex; no manual data path; commerce props vocabulary unchanged (`COMMERCE_PROPS`); `commerce_synced_at` remains mapped from connector `date_modified` (Store snapshot truth, never fabricated).

## 4. RED → GREEN evidence (all builder/sync tests use real connector output)

Suite `tests/pipeline/test_issue105_commerce_metadata_convergence.py` (T1–T8, builder level) + `tests/scripts/test_issue105_mirror_drift_reachability.py` (T9–T10, end-to-end `_sync_one` integration). Documents are produced by the **real `_variation_to_document`** through mocked HTTP (same idiom as `tests/connectors/test_woocommerce_variations.py`); no test constructs a content/metadata state by hand.

- **T1 premise (unit)** — `test_content_equality_does_not_imply_commerce_metadata_equality`: real payloads show `purchasable`/`on_sale`/`permalink`/`date_modified` changes keep `content_hash` identical, while a `stock_status` change necessarily changes it — both natural classes established from connector semantics.
- **T2 metadata-only natural class** — `test_metadata_only_natural_class_converges_serving_and_ledger`: same-hash commerce change ⇒ `METADATA_CHANGED`, zero re-embed, zero version fork; serving commerce props (`purchasable`/`on_sale`/`commerce_synced_at`), ledger row, chunk copies all converge.
- **T3 stock class (RED on R1, GREEN after R2 Fix A)** — `test_content_changed_stock_class_converges_ledger_and_serving`: real stock_status flip ⇒ `CONTENT_CHANGED` ⇒ re-embed + v2; serving converges via rebuild **and `documents.metadata_` converges** (RED: `assert 'instock' == 'outofstock'` — row JSONB frozen at v1).
- **T4 price/sale/qty class** — `test_content_changed_price_sale_qty_class_converges`: real price/sale/on_sale/quantity change ⇒ `CONTENT_CHANGED`; ledger + serving converge on all fields incl. `commerce_synced_at`.
- **T5 production shape** — `test_production_shape_stock_flip_then_repeat_sync_stays_converged`: ingest(instock) → flip(outofstock) → repeat(UNCHANGED); row JSONB converges at the flip round and does not regress — the exact incident timeline, guarded permanently.
- **T6 blocker-2 failure injection (RED on R1, GREEN after R2 Fix B)** — `test_metadata_only_serving_failure_is_fail_closed_and_retryable`: injected `collection.data.update` outage ⇒ round raises; `DocumentVersion.metadata_hash`, row JSONB, chunk copies all unadvanced (no false convergence); second normal sync reclassifies `METADATA_CHANGED`, retries, converges three-way; zero embed, one version across both rounds.
- **T7 idempotency guard** — `test_repeat_sync_idempotent_after_convergence`: post-convergence repeat ⇒ `UNCHANGED`, zero writes.
- **T8 mirror-drift reconciliation (RED on R2, GREEN after R3 Fix C)** — `test_historical_mirror_drift_reconciled_by_normal_sync`: REVIEW_2's five-step recipe (v1 ingest → v2 activation → row-JSONB-only rollback to v1 → same real v2 doc ⇒ reconciliation; repeat ⇒ true UNCHANGED).
- **T9 empty-incremental reachability (RED on R3, GREEN after R4 Fix D)** — `test_empty_incremental_sync_reconciles_mirror_drift`: the REVIEW_R3 recipe end-to-end through real `_sync_one` (§0). RED on the R3 tree: round recorded plain `no_change`, `delta_counts.mirror_reconciled_count` absent (`assert None == 1`), row stayed stale. GREEN: `status=success` + `mirror_reconciled_count == 1`, row mirror = v2, zero embed / zero fork / zero new generation, serving undegraded; second sync = true `UNCHANGED` (`mirror_reconciled_count == 0`, `unchanged_count == 1`).

- **T10 hook strictness (RED on R4, GREEN after R5 Fix E)** — `test_no_change_hook_is_strictly_mirror_drift_only`: four-shape integration proving the no-change hook is strictly mirror-drift-only (§0-pre).

RED records: R1 tree — T3/T4/T5 row-JSONB assertions + T6 fail-open `pytest.raises`; R2 tree — T8 `unchanged_docs == [SID]`; R3 tree — T9 plain `no_change` (`mirror_reconciled_count` absent); R4 tree — T10 `mirror_reconciled_count == 2` (hook churned a METADATA_CHANGED doc). **All 10 GREEN on the R5 candidate.**

## 5. Regression battery (R5)

| # | Suite | Result |
|---|-------|--------|
| 1 | #105 focused (T1–T8 builder + T9/T10 sync integration) | **10/10 passed** (T10 RED on R4 tree pre-fix) |
| 2 | Targeted battery: woo variations, commerce migration, `tests/pipeline/`, `tests/services/`, `tests/retrieval/`, `tests/scripts/`, trackb composition, sync-delta schema | **1707 passed, 0 failed** |
| 3 | **Broad full suite, pristine-base diff** (identical venv/env, complete logs) | base `926dfb7a`: 4 failed / 3078 passed / 0 errors — candidate R5: **4 failed / 3088 passed / 0 errors**; failure sets **item-for-item identical** (known baseline: `gap_export`×2, `gap_observation`×1, `tech_answer_gaps`×1) — zero candidate-attributable failures |
| 4 | scope-check + preserve | `ght scope-check 105` pass / 0 violations; preserve ACTIVE |

Flake attribution (recovery×4): the same `tests/scripts/test_recovery_semantics.py` items (a) passed inside the 1706-pass targeted battery minutes earlier on the full diff, (b) fail standalone **on the pristine base tree in the current host state** (detached temp worktree: 3 failed), and (c) flip between runs on both trees (real-`/bin/sh` drain timing). None relate to the candidate diff; proposed for hygiene triage together with the four known-baseline failures.

Process honesty notes: an R1-era broad attempt was invalidated by concurrent pytest runs sharing `ask_ai_test` PG/Weaviate — all later runs executed exclusively. A worktree-local model-cache symlink pitfall produced transient R1-era embedder errors — environment, fixed, absent from R3/R4 logs. A test-only UUID-ordering nondeterminism in my own helper was fixed to order by `version_seq`.

## 6. Scope-check & boundaries

`ght scope-check 105` → pass, 0 violations. Frozen boundaries untouched: variation identity `{product_id}:{variation_id}`, parent documents, endpoint-truth-only variations, no Cartesian synthesis, product isolation, citation integrity, retrieval fail-closed, prompt/rerank semantics, no hard-coded store/product truth in code (probe fixture values are generic). No reindex, no manual SQL, no vector-DB surgery, no deploy, no production mutation (production access this round = the read-only forensic queries in §1, as required by the review).

## 7. Remaining limitations

1. Convergence requires the sync round to **see** the document: content/metadata changes flow via `fetch_changes`; mirror-drift rows flow via the empty-incremental authoritative discovery (R4, fs/woo connector class). Store-API-side payload staleness remains out of scope. With R4, AC6 is satisfiable by ONE normal canonical Woo re-sync of the current production rows: `fetch_changes` empty (last_success > Store date_modified) ⇒ the authoritative-discovery reconciliation path fires ⇒ Store truth → `DocumentVersion` → documents row → serving/vector props all converge — no future-Store-change dependency, no manual repair/SQL, no `--reindex`, no direct vector mutation.
2. Connectors that self-declare deletions (git/web_crawl) have no full-discovery pass on empty rounds; their historical mirror drift (if any) is not covered by this hook — flagged for Role A rather than silently expanding the sync cost the SHA short-circuit exists to avoid.
3. Known-baseline failures (`gap_export`×2 / `gap_observation` / `tech_answer_gaps`) plus the environment-flaky `test_recovery_semantics` items pre-date this candidate (reproduced at pristine base) — proposed for hygiene triage.
