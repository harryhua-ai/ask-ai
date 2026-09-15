# INC-WEB-EMBED-413 Candidate Report — Website Oversized Embedding Input / Zero-Active Repair

- Date: 2026-09-15 (Asia/Shanghai; production evidence timestamps UTC)
- Status: **INC_WEB_EMBED_413 = CANDIDATE READY**
- Candidate branch: `inc/web-embed-413-20260915` (from `origin/main` `f4e6751`)
- Candidate SHA: committed with this report; see "Candidate commit" below
- Report path: `reports/inc-web-embed-413-candidate-20260915.md`
- Production untouched: zero deploy, zero production mutation, zero data deletion performed by this investigation. All production evidence below was collected read-only.

## 1. Exact root cause (three stacked defects, all necessary for the observed condition)

Production symptom chain, reconstructed from production records and confirmed by code + data:

1. **Migration re-run contamination (trigger).** `scripts/migrate_p1_lifecycle_foundation.py` content backfill (`backfill_content_from_weaviate`) maps **every** Weaviate object to the document's **current** `document_version` (old `_version_id_map`: `source_id → current_version_id`, dedup only on `(version_id, chunk_index)`). When the migration re-ran during the 2026-09-14 deploy window, two `website-camthink` documents had already evolved (current version seq 2 / generation 10, built 08:17 and 12:28 with 1 enforced chunk each). The re-run attached their stale **legacy** chunk rows — 3005 and 2452 chars — into the **current** versions at 15:08:54–15:10:04 UTC (row `created_at` evidence). First affected sync at 15:20:37.
2. **Repair replay ships oversized payloads (failure point).** All repair surfaces replay persisted chunk texts verbatim into embeddings with **no character-contract enforcement**: `GenerationBuilder._build_and_activate_repair` (sync gap-heal) embeds all persisted rows of the current version (`generation_builder.py` repair embed, error format matches production verbatim: `修复代 {N} embed 失败(零激活)`); `document_repair.execute_repair_task` (admin per-doc / bulk repair-all) embeds missing indices' stored texts. The internal endpoint guard (`backend/api/internal_embeddings.py` — `any(len(t) > max_length)` → 413) rejected the oversized rows; the whole repair generation fails with zero activation. `website-camthink` accumulated 5 consecutive failed repair generations (ordinals 11–15, 2026-09-14 15:20–18:42 UTC, `index_generations.failure` = `{"error": "internal embeddings HTTP 413: ...", "stage": "repair_embed"}`), matching the user's "clicking Sync reproduces the failure" observation (three of the five are manual sync clicks at 18:38–18:42).
3. **Perpetual refill loop (why ordinary Sync cannot converge, even before the 413).** `verify_source_vectors` counted objects across **all** generations (generation-agnostic), while repair replay can only rewrite the current version's authoritative extent and can never remove other-generation residue (physical removal is retire/GC-only, and GC has no automatic trigger in production). The two documents were flagged `refill` every hour (sync_log 13:31/14:34: `需重灌 2 篇 … 复验 383/378, MISSING_LEGITIMATE=2`, status=partial forever). Once contamination added oversized rows to the replay payload, each refill attempt turned from futile partial into fatal 413.

## 2. Meaning and unit of `max_length=1024`

- It is **characters** (Python `len()` of the text string = Unicode code points), not tokens and not a model sequence length. Enforced at `backend/api/internal_embeddings.py` (`if any(len(t) > max_length for t in req.texts): 413`).
- Configured via env `EMBEDDER_MAX_LENGTH` (`backend/config.py`, default 8192). Production runs **1024** — verified in the host `.env` and in both `tesla-t4-backend-1` and `tesla-t4-sync-executor-1` container envs, and in production `Settings` (`embedder_max_length=1024`).
- The embedding model itself (BAAI/bge-m3, `backend/embedder/bge.py`) receives `max_length` in **tokenizer tokens** (default 8192) — a different contract at a different layer. The 1024-char service guard is the deployment's GPU-memory protection. The fix does not touch either limit; it enforces the char contract at the ingestion/repair boundary (established #45 pattern).

## 3. Affected pipeline / component (production path trace)

`Website crawl → extraction/normalization (connector) → chunking (token-capped 600 tok ≈ up to ~2–3.5k chars for English) → generation build + atomic activation → embeddings (internal endpoint, char guard) → activation`.

- **New ingestion is NOT affected** since #45 (`ebc45c2`, first shipped v1.5.0): `_enforce_char_limit` hard-splits oversized chunks at the ingest boundary (`ingest.py`, `generation_builder.py` build path). Current-code website ingestion succeeds; production generations 3–10 on 09-14 prove it.
- **Repair surfaces ARE affected** (shared, all source types):
  - sync gap-heal: `scripts/sync.py` `_handle_no_change` → `GenerationBuilder.repair_documents` → `_build_and_activate_repair`;
  - admin per-doc repair: `POST /api/admin/data-sources/{id}/documents/repair` → `execute_repair_task`;
  - admin bulk repair: `POST /api/admin/data-sources/{id}/documents/repair-all` → same executor per document.

## 4. Blast radius — NOT Website-specific (shared ingestion-layer defect, Website merely first to expose it)

Oversized persisted chunk rows (`document_version_chunks` joined to current versions, `length(text) > 1024`), production read-only census:

| source | oversized rows | docs | max chars |
|---|---|---|---|
| ne301-local | 27,492 | 4,249 | 6,970 |
| lowpower-camera-local | 10,668 | 1,263 | 4,876 |
| ne503-apic-69d3594b | 6,972 | 1,042 | 5,431 |
| neomind-local | 4,872 | 555 | 7,780 |
| wiki-documents-local | 2,913 | 384 | 3,315 |
| neomind-extensions-local | 1,622 | 323 | 5,346 |
| aitoolstack-local | 847 | 27 | 4,315 |
| neomind-devicetypes-local | 747 | 132 | 2,786 |
| neoruntime-sdks-67cbac8f | 639 | 164 | 3,883 |
| **website-camthink** | **271** | **66** | **3,582** |
| knowledge-support-cases | 175 | 111 | 4,318 |
| neomind-dashboard-local | 146 | 16 | 3,118 |
| neoruntime-apps-1eea74dd | 131 | 37 | 3,507 |
| woocommerce-mall | 59 | 37 | 3,317 |
| meta-hailo-os-local | 18 | 10 | 2,636 |
| **total** | **57,402** | **~8,413** | 7,780 |

These rows are legitimate 1:1 backfills of legacy-era objects (embedded before the char contract existed, token-capped chunking ⇒ English chunks commonly >1024 chars). They are **latent landmines**: any consistency gap that routes such a document into replay repair 413s exactly like the incident. Additionally the **strict contamination set** (misattached rows on evolved current versions, `chunk_index >= version.chunk_count` on `generation_ordinal > 0` versions) is exactly **3 rows / 2 documents** in production — both `website-camthink` blog documents.

`website-camthink` state: 130 docs, all 66 oversized-row docs `lifecycle=active` with resolvable current versions (64 legacy ordinal-0, 2 at generation 10); **attention bucket = 0** — the admin bulk repair-all eligibility formula currently selects none of them; the operative repair surface is sync gap-heal.

## 5. Changed files

| file | change |
|---|---|
| `backend/pipeline/generation_builder.py` | `repair_documents`: replay bounded to the version's authoritative extent (`chunk_index < chunk_count`); documents with incomplete authoritative sets or any authoritative text exceeding `pipeline._max_chunk_chars` are routed to `unrepairable` (existing source-rebuild fallback) with diagnostic logging. Healthy documents in a mixed batch repair normally — one oversized document can no longer zero-activate the whole batch. |
| `backend/services/vector_consistency.py` | `verify_source_vectors` aligned with the frozen INT-C-01 in-serving-generation projection: objects count as serving only when `generation_ordinal` == the document's current version ordinal (prop-less objects excluded, same as `chunk_serving_for_doc`). Other-generation residue no longer produces phantom refill; report dataclass and all fields unchanged for consumers. |
| `backend/services/document_repair.py` | `execute_repair_task` new optional `max_chunk_chars`: fail-fast contract pre-check on the texts it is about to embed — task fails with a precise, classified error (mentions `max_length`, recommends sync source-rebuild) instead of sending a request doomed to 413. |
| `backend/api/admin/data_sources.py` | Both repair endpoints pass `max_chunk_chars` from `app.state.settings.embedder_max_length`. |
| `scripts/sync.py` | Gap-heal fallback log wording now names all unrepairable reasons (no persistent copy / incomplete authoritative set / over-contract). |
| `scripts/migrate_p1_lifecycle_foundation.py` | `_version_id_map` now resolves the target version by the object's own generation attribution (`(source_id, generation_id) → version_id`); objects whose attribution matches no version are counted as ghosts (reported, never attached to current). Re-runs are convergent; fresh legacy installs keep the previous behavior (prop-less objects stamped legacy → attach to the doc's ordinal-0 version, which **is** current there). |
| `scripts/migrate_remove_contaminated_version_chunks.py` | **New** corrective migration: deletes rows provably misattached (`generation_ordinal > 0` AND `chunk_index >= chunk_count`); preserves ordinal-0 legacy 1:1 rows and all in-range rows; fail-closed on plan/delete/residual mismatch; idempotent. |
| `deploy/prod/migrations.json` | Corrective migration registered (ordered release migrations; executes via the deploy bridge, **not** run now). |

## 6. Tests (RED → GREEN), all in candidate tree

New tests (RED before the fix — verified — and GREEN after; integration tests use real local Postgres + Weaviate, skip if unreachable):

- `tests/pipeline/test_generation_builder.py`
  - `test_repair_routes_oversized_persisted_chunks_to_unrepairable` — production 413 class reproduced pre-fix (contract embedder raises `HTTP 413 text exceeds max_length` on the oversized replay payload); post-fix the document routes to `unrepairable` with **zero embed calls** and zero activation. *(Acceptance 1, 2, 3, 7)*
  - `test_repair_batch_with_oversized_doc_still_repairs_healthy_doc` — mixed batch: healthy document repaired, oversized routed; batch no longer dies. *(8)*
  - `test_repair_bounds_replay_to_authoritative_chunk_count` — misattached out-of-range rows are never replayed into the serving generation. *(4)*
  - `test_repair_repeat_converges_serving_projection` — repeated repair: exactly one serving generation, version identity unchanged, no duplicate active knowledge. *(9)*
  - `test_repair_replay_preserves_provenance_props` — replayed objects preserve `source_id`/`url`/`title`/`content_hash`/`text` and all five evidence-semantic props from the persisted truth. *(11)*
- `tests/services/test_vector_consistency.py` (4 new + 7 updated to the aligned口径)
  - residue in other generations is not refill; missing chunks **inside** the serving generation still refill (incl. whole-doc-missing and prop-less-object cases); iterator property projection now includes `generation_ordinal`. *(10)*
- `tests/api/admin/test_data_sources_track_c.py`
  - `test_u8_repair_oversized_persisted_chunk_fails_fast_without_embed` — admin repair fails fast with `max_length` in the task error, **zero embed calls**, audit row persisted. *(2, 7, 8)*
- `tests/db/test_migration_p1_lifecycle.py` (2 new)
  - backfill re-run attaches chunks by object generation attribution (legacy rows stay on the legacy version; current version keeps exactly its own authoritative set; re-run inserts 0 rows);
  - object with unknown generation attribution = ghost (counted, never attached to current).
- `tests/db/test_inc_web_embed_413_corrective_migration.py` (new file)
  - corrective migration removes exactly the 3 misattached production-shaped rows; preserves legacy 1:1 rows (incl. oversized ones), in-range rows, and healthy documents; idempotent re-run.

Existing regression anchors still green: `test_ingest_char_contract.py` (ingestion boundary, #45), citation/provenance suites (`test_citation_integrity.py`, `test_rag_citation_source.py`), admin Track C suite (461 passed incl. bulk repair-all idempotency/concurrency tests), sync gap-heal/lifecycle suites (63 passed).

## 7. Migration / backfill requirement

- **Required at next authorized deploy**: `scripts/migrate_remove_contaminated_version_chunks.py` (registered in `deploy/prod/migrations.json`) removes the 3 production misattached rows. It is required to restore the U-9 chunk-serving row-count projection for the two documents (the UI would otherwise show a phantom missing index that cannot ever be served). It deletes only structurally-provable corruption; it does **not** touch the 57,402 legitimate legacy rows.
- **No backfill is required** for the 57,402 legacy oversized rows: after this candidate they are inert (never replayed — bounded routing; never counted — aligned verifier; never embedded — fail-fast pre-check). Should such a document ever develop a serving gap, sync gap-heal routes it to source rebuild, which converges it with enforced chunking.

## 8. In-place repairability of the affected production knowledge; is re-crawl required?

- The two production-stuck documents **converge without any data migration**: after the verifier alignment they are already healthy in the serving-generation口径 (in-serving = generation-10 object `{0}` == expected `{0}`); no further refill, no 413. The misattached rows are removed by the corrective migration at next deploy.
- For oversized-row documents that develop real gaps, replay-from-PG is **not** deterministic-safe: re-chunking the concatenation of persisted chunk texts would (a) corrupt section semantics (overlap duplication) and (b) create a version whose `content_hash` matches no authoritative content, causing permanent content-change churn. The repository's authoritative reconstruction path is therefore **source rebuild via sync** (existing fallback: connector fetch → `build_generation(force_rebuild=True)`), which produces a properly hashed version with contract-enforced chunks, atomic activation, and old-generation retirement. The connector fetch is a normal read-only crawl of the authoritative source — non-destructive; superseded versions are retained per lifecycle (no data loss).
- The admin repair surface has **no connector access by architecture** (deliberately zero-source-fetch replay). After this candidate it reports oversized documents honestly instead of failing obscurely; bulk repair-all continues to repair every *eligible* item without per-item interaction. Note the production population in question (66 docs) is `active` with resolvable versions ⇒ attention-eligibility is 0 ⇒ recoverability for them is delivered by the automatic sync-surface bulk repair (gap-heal), consistent with contract C's carve-out that Sync is the authoritative reconstruction path.

## 9. Contract compliance summary (A–F)

- **A New ingestion**: unchanged behavior already contract-safe (#45); no oversized input leaves for embeddings on any ingestion/replay path (audit of all `embed(` call sites in Changed-files section 6 evidence).
- **B Existing affected knowledge recoverable**: yes — sync gap-heal converges oversized/gapped documents via authoritative source rebuild; no per-administrator-item interaction.
- **C Ordinary Sync**: post-fix, unchanged sources verify healthy (residue no longer produces refill); changed documents re-chunk under the contract; no hidden repair semantics added to Sync beyond routing non-replayable payloads to the existing, already-accepted source-rebuild fallback.
- **D Failure semantics**: no truncation, no tail discard, no fake success, no validation weakening, no limit raised; failed generations still fail closed with zero activation and cleanup.
- **E Provenance**: replay preserves persisted props verbatim (new regression test); source rebuild preserves document identity and evidence classification through the unchanged build path.
- **F Idempotency**: repeated sync/repair converge (one serving generation, deterministic UUIDs, version identity stable on replay; source rebuild converges because the rebuilt version hashes to the authoritative content — subsequent syncs classify UNCHANGED).

## 10. Hard boundaries honored

No production deploy; no manual production knowledge edits; no production data deletion (the corrective migration ships as code for the authorized deploy bridge only); no embedding-limit change; no incident closure. Admin credential remediation not touched.

## 11. Verification

- New/updated tests: 4 builder + 4 verifier + 1 admin + 2 migration + 1 corrective-migration file (all RED→GREEN verified; the idempotency anchor was GREEN before and after by design).
- Full backend regression (`pytest tests/ --ignore=tests/e2e`): see "Full regression" below.
- Production read-only verification of the aligned verifier semantics was **not** run as code against production (no candidate code executes against production pre-deploy); the production census numbers in section 4 were collected with read-only SQL and the production verifier itself.

## Candidate commit

- Candidate branch tip: see `git rev-parse inc/web-embed-413-20260915` (pushed to origin as part of this delivery).
- This report is committed on the candidate branch; the pair (code + report) shares the branch tip SHA.
