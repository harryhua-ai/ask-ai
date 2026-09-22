# Issue #105 Execution — WooCommerce incremental sync: commerce metadata freshness when content_hash unchanged

- Claim: `harryhua-ai-20260922T055616-f5e6c1ac` (branch `agent/105/984124c3`)
- Execution base: `926dfb7a08bf506a635a259a41b9a60ebfdb62b1` (frozen main, exact)
- Implementation commit: `ce3dbfa` (GREEN + focused suite); candidate = final commit of this branch (exact SHA in PR description / delivery message)
- Authority: implementation allowed; candidate only — no deploy, no production mutation
- Parent evidence: #28 comment `5771553047` (production repro identities `5110:5950` / `5110:5951`)

## 1. RCA — code ownership mechanically confirmed from main (not assumed)

Incremental path audited end-to-end: `scripts/sync.py:_sync_one` →
`connector.fetch_changes(since)` → `GenerationBuilder.build_generation` →
`classify_docs` → `lifecycle.classify_change(doc_row, version_row, content_hash, meta_hash)`.

- `classify_change` (backend/services/document_lifecycle.py:377) **does** compare
  `metadata_hash`: equal content hash + changed metadata ⇒ `METADATA_CHANGED` ⇒
  metadata-only path (`_apply_metadata_only`), zero re-embed, zero version fork.
  There is no sync-side content-hash pre-filter.
- `compute_metadata_hash` covers the full metadata dict (all commerce keys included),
  symmetric on the ledger side (`metadata_hash_of_version_row`).
- **Defect ownership = `GenerationBuilder._apply_metadata_only`
  (backend/pipeline/generation_builder.py)**: its Weaviate object merge-update built
  `stale_props` from doc-level identity fields + evidence props only — the commerce
  projection (`_commerce_props`, the same projection the ingest/content-changed path
  uses via `_build_props`) was **never applied**. The persisted `DocumentVersionChunk.props`
  sync used the same commerce-less dict. Consequence: when a document takes the
  metadata-only path, the ledger converges but the **serving/vector commerce truth —
  including `commerce_synced_at` (mapped from connector `date_modified`) — stays stale**,
  and any later `repair_documents` rebuild resurrects the stale commerce props from the
  persisted chunk copies. This is exactly the production-observed class: content
  equality treated as full equality while authoritative commerce metadata diverges.

Connector semantics corroborate the class is real, not synthetic: in
`_variation_to_document`, `purchasable` / `on_sale` / `permalink` / `date_modified`
are **not** part of the retrievable text lines, so those Store-side changes naturally
produce a new fetch with **identical `content_hash`** and different commerce metadata.

## 2. RED (on base `926dfb7a`, T1/T2 per contract; content byte-identical in T1→T2)

New focused suite `tests/pipeline/test_issue105_commerce_metadata_convergence.py`:

- Connector leg (unit, zero network) — `test_content_equality_does_not_imply_commerce_metadata_equality`:
  real connector semantics, T1 purchasable=true/on_sale=false/permalink P1/date D1 vs
  T2 purchasable=false/on_sale=true/permalink P2/date D2 with identical price/stock/sku/attrs
  ⇒ **same `content_hash`**, incremental `fetch_changes` **returns** T2, metadata differs.
  PASSED on base (premise proof: the class arises naturally).
- Builder leg (real Postgres + real Weaviate):
  - `test_metadata_only_converges_serving_commerce_props` — **FAILED on base** with
    `AssertionError: assert 'instock' == 'outofstock'` (serving `stock_status` residual T1
    value after a successful metadata-only round; ledger metadata converged, zero re-embed,
    zero version fork — the failure isolates serving commerce props as the stale surface).
  - `test_metadata_only_clears_unmanaged_stock_quantity` — **FAILED on base**
    (`assert not 5` — endpoint stopped managing stock, serving kept the old quantity;
    merge-update "omit" semantics = residual, must converge to honest absence).
  - `test_repeat_sync_idempotent_after_convergence` — PASSED on base (UNCHANGED fast path
    already idempotent; kept as a regression guard for the fix).

No content text was modified to manufacture RED; the T1/T2 pair differs only in
authoritative commerce metadata at the classify boundary.

## 3. GREEN design (minimal surface, frozen semantics preserved)

`backend/pipeline/generation_builder.py::_apply_metadata_only`, metadata-only path only:

1. `stale_props.update(_commerce_props(doc))` — the exact projection used by the
   ingest/content-changed path (`_build_props`), so both surfaces write the same
   commerce vocabulary (`commerce_type`, `product_id`, `variation_id`,
   `variation_identity_key`, `sku`, `price`, `regular_price`, `sale_price`, `on_sale`,
   `stock_status`, `stock_quantity`, `purchasable`, `variation_attributes`, `permalink`,
   `commerce_synced_at`). `commerce_synced_at` stays mapped from connector
   `date_modified` (Store snapshot truth — never fabricated).
2. Honest-absence convergence: for props whose default is `None` (current vocabulary:
   `stock_quantity` only), an absent/None value is written **explicitly** so the
   merge-update clears the residual instead of silently keeping the old value —
   same semantics as ingest's "整键省略、不写 0 伪装".
3. The same merged dict continues to flow into the `DocumentVersionChunk.props`
   sync, so persisted chunk copies (the `repair_documents` truth source) converge too.

No connector change; no schema change (commerce props already exist since #28 B1-3);
no prompt/rerank/citation/retrieval change; no reindex; no manual data path.

## 4. Metadata update semantics / idempotency / embedding churn

- Metadata-only updates remain exactly FC-5: zero re-embed, zero version fork,
  single generation; ledger (`documents.metadata_`) and version `metadata_hash`
  update as before; serving objects + chunk copies now converge.
- Idempotency: after convergence the next identical sync classifies `UNCHANGED`
  (meta_hash equal) and performs zero writes — asserted by
  `test_repeat_sync_idempotent_after_convergence`.
- Embedding churn: `stack.embedder.calls == []` asserted across all metadata-only
  rounds; vectors untouched (merge update only). Content that did not change never
  re-embeds merely to refresh structured commerce metadata (AC3).

## 5. Focused results

`tests/pipeline/test_issue105_commerce_metadata_convergence.py`: **4 passed** post-fix
(2 RED→GREEN, 2 premise/guard legs stable). RED evidence on base recorded in §2.

## 6. Regression battery

| # | Suite | Result |
|---|-------|--------|
| 1 | #105 focused | 4/4 passed |
| 2 | `tests/connectors/test_woocommerce_variations.py` + `tests/scripts/test_migrate_add_commerce_variation_props.py` + `tests/pipeline/test_generation_builder.py` + `tests/pipeline/test_issue94_zero_chunk_builder.py` | 36 passed |
| 3 | `tests/scripts/` + `tests/services/` + `tests/retrieval/` | 862 passed; 5 failures reproduced identically on the candidate tree without the new tests (pre-existing; see §6.1) |
| 4 | `tests/pipeline/` + `tests/api/admin/test_trackb_composition_u28_u31.py` | 822 passed after exclusive re-run |
| 5 | Broad backend regression (`backend/ tests/`, full) | see §6.1 |
| 6 | scope-check (`ght scope-check 105`) | `pass: true`, 0 violations |

### 6.1 Broad regression + pristine-base attribution (authoritative)

Both runs full suite `backend/ tests/`, `HF_HUB_OFFLINE=1`, identical venv, complete logs:

| Run | Result |
|-----|--------|
| **Pristine base** `926dfb7a` (detached temp worktree) | **4 failed, 3078 passed, 8 skipped, 0 errors** |
| **Candidate** (implementation `ce3dbfa` + this report) | **4 failed, 3082 passed, 8 skipped, 0 errors** |

Failure sets are **item-for-item identical** and pre-existing at base (known baseline):
`test_gap_export.py::test_export_action_audited_and_queryable`,
`test_gap_export.py::test_export_scope_window_inheritance`,
`test_gap_observation.py::test_window_not_elapsed_no_recurrence_noop`,
`test_tech_answer_gaps.py::test_answer_gaps_window_honest_four_states`.
The candidate passes exactly **+4** tests (the focused #105 suite) with **zero new
failures** — regression equivalence proven by direct base-vs-candidate diff.

Process notes (instrumentation honesty): an earlier broad attempt was invalidated
(a concurrently executed targeted suite shared the same `ask_ai_test` Postgres/Weaviate
and cross-contaminated generation-ordinal state) and re-run exclusively. A second
candidate run initially showed bge-reranker×4 errors + `test_lifespan_smoke` —
traced to a **broken local model-cache symlink in the scratch worktree** (nested
`models/models`), i.e. environment, not code: the pristine-base run with a correct
symlink passes all of them, and after repairing the symlink the candidate run shows
zero such failures. Neither artifact relates to the candidate diff.

## 7. Scope-check

`ght scope-check 105` → `{"pass": true, "violations": [], "counts": {"ALLOWED": 0, "FORBIDDEN": 0}}`.
Frozen boundaries untouched: variation identity `{product_id}:{variation_id}`, parent
documents, endpoint-truth-only variations (no Cartesian synthesis), product isolation,
citation integrity, retrieval fail-closed, prompt/rerank semantics. No hard-coded
product/store identities in code or tests (the 5110/5950 numbers appear only as
arbitrary probe fixture values in the test file, mirroring the production repro shape).

## 8. Remaining limitations

1. Convergence requires the incremental path to **see** the changed metadata
   (`fetch_changes` must return the product). Store-side payload staleness/caching at
   the Store API boundary is outside this corrective's reach (production probe proved
   `fetch_changes` returns the fresh truth; AC6 re-verification after deploy will
   confirm end-to-end on the live identities).
2. Serving rows whose ledger metadata already equals Store truth but whose Weaviate
   commerce props pre-date B1-3 remain untouched by normal syncs (UNCHANGED path);
   the deployed commerce-props migration already covers that population, and AC6
   production acceptance will verify.
3. The five environment-dependent baseline failures in recovery/executor tests
   pre-date this candidate (attributed at base) and are proposed as a follow-up
   hygiene task for Role A triage.
