# V1.6.3 CORRECTNESS PRODUCTION CLOSURE — Execution Report

Status: `V1.6.3_PRODUCTION_CLOSURE_CANDIDATE_READY_FOR_ROLE_A`
Executor: Role B (Production Execution round)
Date: 2026-09-17 (all timestamps CST = UTC+8)

## A. Release identity

- AUTHORITATIVE MAIN SHA: `14fdc0ff458e576d0272d90f5acaaf13e23dfc48`
- `git fetch origin` → origin/main = `14fdc0ff` (exact tip; ancestor gate PASS, zero commits beyond)
- Deploy vehicle: immutable release tag **`v1.6.3-r7`** → annotated at `14fdc0ff` (canonical deploy workflow only accepts exact tags; `-rN` form per TAG_RE convention; next free -rN after r6@67d426d)
- GitHub Release `v1.6.3-r7` created (release-publish guard invariant `GITHUB_RELEASE_EXISTS`)
- Image build: run `35187681897` (test 3m20s ✓ + build-and-push 4m19s ✓ → `ghcr.io/harryhua-ai/ask-ai:v1.6.3-r7`)
- Deployed from **main-derived tag only**; PR branch never deployed.

## B. Preflight (13:45–13:53)

- Pre-deploy runtime: `1.6.3-r6` @ `67d426d…` healthy (`/health` verified)
- Containers: backend healthy, sync-executor/sync-cron Up 13h; PostgreSQL/Weaviate healthy (Up 4 weeks)
- Migration preflight: 5 identity columns all `varchar(200)`; `to_regclass('ingestion_exclusions')` = NULL (absent); `MAX(length(source_id))` in documents = 198 (no >200 rows — long identities had always failed at INSERT); canonical runner = frozen-tree `deploy/prod/migrations.json`, fail-closed parser, idempotent entries, no ledger table
- Active-work check at 13:45: a cron pass was mid-flight (started ~04:4x UTC) → **waited for safe end** (last source woocommerce 13:53:57); no generation interrupted, nothing killed. Two zombie `processing` `index_generations` rows (wiki ordinals 43/51, pre-fix truncation residue — activation exception path predates the fix) documented; not active work.
- Executor/cron mutual exclusion: executor claims `sync_requests` `FOR UPDATE SKIP LOCKED`, runs `scripts/sync.py` per-request; cron = full pass + `sleep 3600` → ≥1h quiet window after each pass; all manual verification runs were dispatched via the executor handoff surface inside quiet windows.

## C. Backups / recovery point

- `~/ask-ai-backups/pre-v163r7-20260917.dump` (pg_dump -Fc, 105,279,732 bytes, 13:52 CST) — full `ask_ai` DB recovery point taken **before any mutation**
- Weaviate not backed up: both migrations are additive/metadata-only (widening + CREATE TABLE); rollback path = previous immutable tag re-dispatch (no automatic rollback, per workflow contract)

## D. Migration evidence (deploy run `35188305480`, log excerpts)

- `MIGRATION BEGIN:scripts/migrate_widen_document_source_id_500.py(执行环境 = 冻结镜像 v1.6.3-r7)` →
  `OK: 扩容至 VARCHAR(500): documents.source_id, documents.superseded_by, document_versions.source_id, document_repair_tasks.doc_source_id, document_recovery_events.doc_source_id` → `MIGRATION DONE` (06:24:11Z)
- `MIGRATION BEGIN:scripts/migrate_add_ingestion_exclusions.py` → `OK: ingestion_exclusions 就绪(幂等迁移完成)` → `MIGRATION DONE` (06:24:17Z)
- Executed in the frozen release image, **before** any app rollout (workflow ordering invariant)

**SCHEMA_91 = PASS** — `ingestion_exclusions`: PK = `source_id` (single), columns content_hash varchar(64) / reason / detail / stage / actor / times_confirmed / first_seen_at / last_confirmed_at, index `ix_ingestion_exclusions_source`.
**SCHEMA_92 = PASS** — all 5 identity columns = `varchar(500)`; source-level config-id columns remain 100 (unchanged, out of scope).
Data integrity: 12,407 documents; `MAX(length(source_id))` = 198 (unchanged); sample row md5 captured; no value rewrites (metadata-only widening).

## E. Deployment SHA / runtime SHA

- DEPLOY_SHA = `14fdc0ff458e576d0272d90f5acaaf13e23dfc48`
- Deploy run `35188305480` = success (20m20s, production Environment)
- **RUNTIME_SHA = `14fdc0ff458e576d0272d90f5acaaf13e23dfc48`** — `/health` returns `{"version":"1.6.3-r7","git_sha":"14fdc0ff…"}` (version + git_sha double assertion, not image-tag-only); backend/sync-executor/sync-cron recreated on `ghcr.io/harryhua-ai/ask-ai:v1.6.3-r7`
- Post-restart cron pass began 14:25 CST (container-start semantics) — used as the #91 cycle-1 production vehicle

## F. #92 long-ID evidence

- `wiki-documents-local`: 17:04:48 CST sync = **success** (62.8s); zero `StringDataRightTruncation` (PRE: failed 06:52 and 10:24 today with truncation)
- LONG_SOURCE_ID = `wiki-documents-local/main/i18n/en/docusaurus-plugin-content-docs/current/1-neoedge-ng4500-series/2-ng4500-cb01-development-board/2-software-guide/1-driver-installation-and-updates/0-interface-and-modules-configure.md` (the exact identity that failed insertion PRE-fix, sampled from sync_log error_detail)
- LONG_SOURCE_ID_LENGTH = **216**
- End-to-end: `documents.source_id` exact (216, `lifecycle=active`, `current_version_id` set) → `document_versions` row (seq=1, active, chunk_count=19, generation_ordinal=64, source_id length 216 exact) → generation 64 ready → vector projection (19 deterministic UUIDs; retrieval access verified by probes below). Wiki corpus now has exactly 1 identity >200 (max_len=216).
- **#92_PRODUCTION_ACCEPTANCE = PASS**

## G. #91 cycle-1 evidence (deploy-restart cron pass, 14:25→17:06 CST)

PRE truth (13:45–13:50 snapshots; membership_checked_at per source):

| source | authoritative | serving PRE | missing PRE | last PRE sync |
|---|---|---|---|---|
| ne301-local | 15870 | 5379 | 10491 | failed 13:45 (gen 53, 88 excluded, zero activation, 6153s) |
| lowpower-camera-local | 6688 | 2405 | 4283 | failed 12:02 (gen 52, 76 excluded, 2239s) |
| neomind-local | 1516 | 875 | 641 | failed 10:22 (gen 48, 3 excluded, 292s) |
| neomind-extensions-local | 711 | 489 | 222 | failed 13:47 (gen 55, 4 excluded, 65s) |

Cycle-1 results (all SUCCESS — every one had failed identically for days):

| source | duration | missing | permanent_excluded | eligible | activated(new) | serving after | transient_failed |
|---|---|---|---|---|---|---|---|
| ne301-local | 6631s (1h50m), gen 65 ready | 10491 | **88** (82 binary + 6 secret) | **10403** | 10403 | 15777 | 0 |
| lowpower-camera-local | 2380s | 4283 | **76** (74 binary + 2 secret) | **4207** | 4207 | 6594 | 0 |
| neomind-local | 338s | 641 | **3** | **638** | 638 | 1513 | 0 |
| neomind-extensions-local | 111s | 222 | **4** | **218** | 218 | 707 | 0 |

Partition arithmetic is EXACT in all four: missing = eligible + permanent_excluded. `ingestion_exclusions` rows = 171 = 88+76+3+4 (reasons: binary_content/secret_content). Zero whole-generation zero-activation. Excluded identities: no ledger row, no version, no vector, never served. Transient failure path untouched (fail-closed suite green in release CI; no transient failures occurred in production during the window).

`membership_excluded` = 0 in cycle-1 deltas (reconcile precedes backfill — exclusions did not exist at reconcile time); from cycle-2 the reconcile face reports them (see H). Accounting keys `eligible_count` / `permanent_excluded` present in every delta.

## H. #91 cycle-2 convergence evidence (executor-dispatched, requests 55/56)

Triggered via the executor handoff surface (`sync_requests` pending rows; backend-credential-free path) after the pass ended:

- **ne301-local (request 55)**: picked 17:25:12, done 17:26:15; sync **success**, duration **57.8s** (cycle-1: 1h50m). Reconcile log line: `authoritative=15870 ledger_serving=15777 stale=0 retired=0 missing=5 permanent_excluded=88 residual=0`. delta: `membership_excluded=88` (in-window suppression via connector fingerprint match), `permanent_excluded=0` (no new), new=5. **No large missing refill, no mass embed, no zero activation** — the repeated-GPU loop is terminated.
- **lowpower-camera-local (request 56)**: success, duration **45.3s**, `membership_excluded=76`, new=18.
- Cycle-2 missing residues (5 / 18) = the **empty-chunk class** — see N (new finding, bounded, honest, zero-embed).

**#91_PRODUCTION_ACCEPTANCE = PASS** (ne301 two-cycle proof complete; lowpower cycle-2 corroborates).

## I. #77 before/after counts

- EVAL_PRE_COUNT = **298** (fresh recompute 13:50 CST: `neomind-local/main/eval/**` lifecycle=active; identical to historical baseline)
- Config operation (frozen scope): `neomind-local` `exclude_dirs` = `[".github","docs"]` → `[".github","docs","eval"]` — executed as a scoped update of the same `data_sources.config` surface the Admin edit path writes (Admin credentials unavailable to this round; no other key touched; rollback = remove `"eval"`). Applied 17:30 CST.
- Convergence sync (request 57): success 39.9s → authoritative enumeration without `eval/**` → #71 membership reconciliation tombstoned the serving eval corpus: **384/384 tombstoned rows are `eval/**` paths (zero collateral)** — 298 historical serving + 86 eval rows that cycle-1 had ingested minutes earlier. Ledger/lifecycle plane: **serving-eligible eval = 0**; legit non-eval NeoMind serving = 1127 intact.
- **EVAL_POST_SERVING_COUNT = 0**

## J. #77 retrieval probes (production /api/ask, SSE `sources` event = evidence universe)

| probe | query | sources | eval hits |
|---|---|---|---|
| negative (eval-exclusive vocabulary) | "analysis-cross-compare market-install eval fixtures list-and-delete" | 0 | **0** |
| positive (webhook topic) | "NeoMind 如何配置推送 webhook" | 5 (wiki user-guide 8-notifications / 3-onboard-device + NeoMind webhook.rs / ChannelEditorDialog.tsx / MessageChannelsTab.tsx) | **0** |
| positive (onboarding topic) | "NeoMind 设备首次使用如何配网激活" | 5 (onboard-device / five-minute-guide / install-setup / OCR / object-detection) | **0** |

No eval fixture surfaces as evidence candidate even under its own exclusive terms; legitimate docs/code fully retrievable. Physical weaviate residue: sampled eval identities still hold objects (5/5/1 chunks) — retained per retired-retention semantics (I-4/I-5); physical GC separately gated, **not** authorized here.

## K. #77 real /ask probes

The three probes above ARE fresh production `/ask` calls (POST /api/ask, channel=widget): no numbered citation or answer evidence from `eval/**` in any response; legitimate official documentation remains retrievable and cited. Full SSE transcripts on prod host: `/tmp/probe1.json`, probe script `/tmp/ask_probe.py`.

**#77_PRODUCTION_ACCEPTANCE = PASS** — EVAL_PRE_COUNT = 298 → EVAL_POST_SERVING_COUNT = 0; RETRIEVAL_PROBE = PASS; ASK_PROBE = PASS.

## L. #25 runtime regression (verification only)

- Diff audit: `67d426d..14fdc0ff` touches **zero** lifecycle-retirement surfaces (document_lifecycle / lifecycle_gc / filesystem connector / gc_lifecycle — empty diff)
- Live exercise during this round: membership reconciliation tombstone path executed 384× with immediate serving withdrawal (the same retirement machinery #25 composes with) — correct, auditable, idempotent
- Two-discovery/`missing_candidate` semantics: code unchanged from the accepted r5 Track A + r6 state; focused fs-retirement suite green on this exact tree pre-deploy (release CI test job green)
- No physical GC applied
- **#25_RUNTIME_REGRESSION = PASS**

## M. Post-deploy health (17:49 CST)

- Zero sync failures and zero failed generations since deploy (14:25 CST) — every executed source round succeeded
- backend healthy (`1.6.3-r7` @ `14fdc0ff`), postgres/weaviate healthy, executor/cron Up on v1.6.3-r7
- Executor/cron log error-scan: only benign path-substring matches (eval fixture filenames containing "error"); no tracebacks
- GPU 12925/16384 MiB (shared-services baseline), load 1.27, disk 29%
- Absences confirmed: no migration error loop, no executor retry storm, no repeated ne301 embedding, no truncation errors, no eval serving leakage
- `ingestion_exclusions` = 171 rows (88+76+3+4, exact)

## N. Remaining risks / new findings

1. **NEW FINDING (follow-up candidate, no code change made): empty-chunk authoritative identities.** Authoritative files whose semantic chunking yields zero chunks (`.mk`/`.cmake`/`license.txt`/`__init__.py`-style) are counted in the backfill batch, skipped by the pre-existing "切分为空" semantics, never ledgered, and therefore re-enter `missing` every cycle: ne301 = 5, lowpower = 18, bounded small counts, zero embedding, zero poisoning, honest accounting. Same deterministic-partition family as #91; recommend a follow-up issue to partition chunk-empty identities (and to fold them into the exclusion accounting) under Role A authorization. NOT fixed in this round per the no-hot-patch rule.
2. eval/** physical weaviate objects remain (retired-retention window) — physical cleanup is GC-domain and separately gated (#90 is distinct and untouched).
3. Citation `link_state: "stale"` observed on some /ask sources (pre-existing #55 truth surface; unrelated to this round; noted as observation).
4. ne301 cycle-2 residue of 5 means `membership_missing` will report 5 every cycle (honest); lowpower 18; expected stable.
5. Zombie `processing` generations (wiki 43/51) from pre-fix failures remain in `index_generations`; harmless (no worker attached), GC/audit-domain.

## O. Exact timestamps (CST)

| event | time |
|---|---|
| preflight + PRE snapshots | 13:45–13:50 |
| DB backup `pre-v163r7-20260917.dump` | 13:52 |
| cron pass end (quiet window) | 13:53:57 |
| tag `v1.6.3-r7` push | 13:55 |
| image build success (35187681897) | 14:04 |
| deploy dispatch (35188305480) | 14:04:57 |
| migrations executed (frozen image) | 14:24:05–14:24:17 |
| rollout complete, RUNTIME_SHA verified | 14:25:20 |
| cycle-1 cron pass | 14:25:19 – 17:06 |
| ne301 cycle-1 | 15:06 – 16:56:16 (6631s) |
| ne301 cycle-2 (request 55) | 17:25:12 – 17:26:15 (57.8s) |
| lowpower cycle-2 (request 56) | 17:31:38 – 17:32:28 (45.3s) |
| #77 config + neomind resync (request 57) | 17:30 config; 17:38:52 – 17:39:36 sync |
| retrieval //ask probes | 17:44–17:48 |
| final health | 17:49 |

## P. Production run IDs / generation IDs

- Deploy workflow run: `35188305480` (success); image build: `35187681897`; failed first dispatch (missing Release): `35188246801` (guard fail-closed, zero mutation)
- sync_requests: 55 (ne301 cycle-2, done/exit 0), 56 (lowpower cycle-2, done/exit 0), 57 (neomind #77, done/exit 0)
- Generations: ne301 ordinal 65 (ready, cycle-1); wiki ordinal 64 (ready, carries the 216-char identity); pre-fix zombies 43/51 documented

## Q. Report commit

This file, committed on `exec/v163-correctness-closure` (REPORT_COMMIT in the final response).
