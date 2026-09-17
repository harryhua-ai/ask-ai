# V1.6.3 CORRECTNESS CLOSURE — Execution Report (#25 / #77 / #91 / #92)

Status: `V1.6.3_CORRECTNESS_CANDIDATE_READY_FOR_ROLE_A_REVIEW_3`
Executor: Role B
Date: 2026-09-17

---

## 0a. REVIEW_3 CORRECTION — immediate content-change invalidation (no TTL wait)

Role A review 2 verdict: BLOCKED — the TTL-aging GREEN proved `unsafe → wait → safe →
re-evaluate`, but the contract requires same-source content change to invalidate
suppression **immediately**; the 7-day window must only be a bounded fallback.

### Corrected semantics (fingerprint-invalidated suppression, TTL as fallback)

- **Narrow connector capability (no redesign):** `GitHubConnector` gains the optional
  duck-typed capability `membership_content_fingerprints(source_ids) -> dict[str, str]`
  — the CURRENT authoritative content fingerprint per identity, computed with the
  EXACT same transform as ingestion's `content_hash` (`read_text(utf-8, replace)`
  universal-newline translation → utf-8 sha256) but read from the **git object
  database** (`git show origin/<branch>:<rel>`), so it is correct regardless of the
  transient multi-branch/reset state of the shared clone working tree. Narrow by
  construction: it is only invoked for identities that have an exclusion row
  (typically few), zero full-corpus cost.
- **Reconcile comparison (membership_currency):** for each in-window exclusion row:
  fingerprint == recorded `content_hash` (content unchanged) → suppression stands
  within the window; fingerprint differs (authoritative content changed) →
  suppression is invalidated IMMEDIATELY — the identity re-enters actionable
  `missing` → backfill re-fetches it → the builder re-judges under the current
  policy (safe → activate + clear row; unsafe → verdict swapped in place).
  Connectors WITHOUT the capability fall back to the Tier-2 suppression window
  (TTL remains the bounded fallback covering policy/safety-rule evolution).
- Everything from REVIEW_2 is preserved: builder-always-re-judges (tier 1),
  bounded TTL fallback, single-verdict-per-identity rows, expired-out-of-authority
  purge hygiene, zero re-embedding of unchanged excluded content, transient
  fail-closed.

### REVIEW_3 RED → GREEN

`test_immediate_content_change_reevaluation_without_ttl` (committed FIRST as RED,
`38db48b`; run against the REVIEW_2 tree — no TTL aging anywhere):

| Cycle | Behavior asserted | Pre-fix (1032954) | Post-fix |
|---|---|---|---|
| 1: X unsafe (hash A) | exclusion(A) persisted, not serving | PASS | PASS |
| 2 IMMEDIATELY: X → safe (hash B), fingerprint drift | stale exclusion must not suppress → refetch → safety passes → activate → row cleared → serving | **FAIL** (`TTL 窗口内永久缺席`) | **PASS** |
| 3: unchanged (hash B) | true no-change, zero re-embed, zero actionable missing | n/a | **PASS** |

Companion regressions: `test_fingerprint_match_keeps_suppression_without_reembed`
(fingerprint equality keeps suppression — the loop is NOT recreated) and
`test_fingerprint_capability_absent_keeps_ttl_fallback` (capability-less connectors
keep Tier-2 window behavior). Connector-level: `tests/connectors/test_issue91_content_fingerprints.py`
proves hash parity with `RawDocument.content_hash` byte-for-byte (including CRLF and
CJK newline-translation surfaces), drift detection across a moved remote ref, and
absence semantics for unknown/out-of-scope identities.

---

## 0. REVIEW_2 CORRECTION — stale-exclusion invalidation/re-evaluation (P0 blocker fix)

Role A review 1 verdict: BLOCKED — `reconcile_membership` collapsed exclusions to
`source_id` with **unbounded** suppression: once recorded, an identity could never
re-enter actionable missing even after its authoritative content changed, so the
builder never re-evaluated and valid content could remain permanently absent.

### Corrected semantics (two-tier, bounded)

- **Tier 1 — immediate (builder is the only judge).** The exclusion table is
  bookkeeping, never a decision gate: `GenerationBuilder` runs the CURRENT policy's
  `check_content` on every piece of content that reaches it. Any content change that
  reaches the builder (normal incremental `fetch_changes` path, refill, backfill) is
  re-evaluated immediately: safe → activates and the exclusion row is deleted in the
  activation transaction; unsafe-with-different-hash → the row is updated in place
  (single-verdict-per-identity).
- **Tier 2 — bounded backstop (suppression window).** `ingestion_exclusions` PK is now
  `source_id` alone (row = the verdict on the identity's CURRENT content; `content_hash`
  is an attributed column). Reconcile-time suppression is bounded by
  `INGESTION_EXCLUSION_REEVALUATION_DAYS = 7` (from `last_confirmed_at`,
  `backend/services/ingestion_exclusions.py`): an expired row no longer suppresses
  missing, so the identity re-enters actionable missing → backfill re-fetches it →
  the builder re-judges under the current policy → the verdict is refreshed
  (same-unsafe-content: `times_confirmed`+1, suppression window restarts, **zero
  embedding**; now-safe: activate + clear; changed-unsafe: verdict swapped in place).
  Policy/safety-rule evolution therefore has a deterministic re-evaluation path.
- **Hygiene:** inside the reconcile transaction, expired rows whose identity has LEFT
  the authoritative enumeration are purged (no suppression/audit purpose remains);
  expired rows still inside the enumeration are retained — they ARE the re-evaluation
  request.
- **Bounded cost:** a re-evaluation costs one content fetch + safety scan per expired
  identity (zero embedding) and a full `fetch_all` happens only in rounds where
  expired identities exist (≤ once per window per affected source) — the original
  repeated-GPU loop is NOT recreated (proven by
  `test_expired_exclusion_same_unsafe_content_reconfirmed_without_embedding`).

Single implementation surface: `backend/services/ingestion_exclusions.py`
(window constant, `record_permanent_exclusion` upsert with content-transition
semantics, `suppression_excluded_ids`, `purge_expired_out_of_authority`,
`delete_for_identities`); consumed by `membership_currency` and `generation_builder`.

### REVIEW_2 RED → GREEN

New suite `tests/pipeline/test_issue91_stale_exclusion_reevaluation.py`, committed FIRST
as RED against the pre-fix tree (`fb7f1f8`, run on a2b61ec behavior — implementation
stashed), then GREEN on the corrected tree:

| Test | Pre-fix (a2b61ec) | Post-fix |
|---|---|---|
| `test_stale_exclusion_cycle2_reevaluates_changed_content` (Role A 3-cycle sequence) | **FAIL** — content changed to safe → suppressed forever, never refetched (`永久缺席`) | **PASS** — expired suppression → refetched → activated → stale row cleared → cycle 3 true no-change, zero re-embed, zero actionable missing |
| `test_expired_exclusion_same_unsafe_content_reconfirmed_without_embedding` | **FAIL** — never re-confirmed (`times_confirmed` stuck) | **PASS** — re-confirmed, window restarts, still non-serving, **zero embedding** |
| `test_policy_evolution_reevaluates_previously_excluded_identity` | **FAIL** — no re-evaluation path | **PASS** — relaxed current policy re-judges after expiry → activates → row cleared |
| `test_reconcile_purges_expired_exclusions_out_of_authority` | **FAIL** — expired out-of-authority row kept forever | **PASS** — purged in-reconcile; in-enumeration expired rows retained |
| `test_incremental_content_change_bypasses_suppression_immediately` | **PASS** (protection; tier-1 already correct) | **PASS** |

### Preserved invariants (re-verified)

Eligible-set atomicity, zero re-embedding of unchanged excluded content, transient
fail-closed, no best-effort partial activation, secrets/binaries never in serving
truth, #71/#82 reconciliation, #77 evidence eligibility — all existing #91 suites
(12 tests) plus focused generation/membership/sync/#25/#77 suites re-run green (§I).

---

## A. Baseline

- origin/main SHA: `42b205aa350a9bf219ce6f726c5cd079b935b608` (fresh fetch; verified `git rev-parse origin/main`)
- Branch: `exec/v163-correctness-closure` (new isolated track worktree; no reusable same-track worktree existed)
- Worktree: `/Users/harryhua/Documents/GitHub/ask-ai-v163-correctness`
- Working tree at start: main repo had two pre-existing local items NOT touched by this round:
  `.gitignore` local modification (adds `ght/` to ignore, pre-dates this round) and untracked `.ght/`
  claim-state directory (ght tool state from previous rounds). Neither is part of this candidate.
- Baseline focus evidence gathered on this tree:
  - `tests/scripts/test_fs_disappearance_retirement.py tests/api/admin/test_issue25_lifecycle_detail.py tests/services/test_membership_currency.py` → **23 passed**
  - `tests/pipeline/test_issue77_evidence_eligibility.py tests/services/test_corpus_repair.py` → **18 passed**
  - Production read-only PRE_COUNT (`neomind-local/main/eval/**` lifecycle=active) = **298** (2026-09-17, unchanged from historical baseline)

## B. Issue matrix (canonical close gates = latest Role A Final Acceptance Contracts)

### #25 — filesystem retirement closure (Final Acceptance Contract items 1–8)

| AC | Verdict | Evidence on current main `42b205aa` |
|---|---|---|
| 1. Two-discovery retirement (`missing_candidate` → RETIRED) | **SATISFIED** | `DocLifecycle.MISSING_CANDIDATE` grace + `confirm_absence_retirement` (document_lifecycle.py); `tests/scripts/test_fs_disappearance_retirement.py::test_two_complete_discoveries_retire_disappeared_file` green this round |
| 2. Failed/partial/permission/low-coverage discovery does not advance | **SATISFIED** | incomplete-discovery no-advance tests green this round (A-2) |
| 3. Policy absence distinct + restore | **SATISFIED** | `policy_absent` classification + `test_policy_absence_frozen_then_reinclusion_restores` green this round |
| 4. Retirement truth: retired_at/reason/evidence/actor + gc_eligible_at = retired_at + 7d; GC gated | **SATISFIED** | `gc_eligible_at` anchor in lifecycle; `test_gc_apply_requires_config_gate` green (composition suite); scheduled sweep + config-gated apply shipped in r5 |
| 5. Idempotency/auditability + Admin detail truth | **SATISFIED** | idempotent re-confirmation tests; `tests/api/admin/test_issue25_lifecycle_detail.py` green this round |
| 6. Repair cannot resurrect source-confirmed-retired content | **SATISFIED** | A-7 withdrawn-identity guard (r6 hardening `67d426d`) + refill exclusion tests green |
| 7. #71/#82 connector/membership regression | **SATISFIED** | `test_membership_currency.py` + `test_issue82_scope_backfill.py` green this round (10 + 6 tests) |
| 8. Full regression green, serving-projection/fail-closed unchanged | **SATISFIED** | full suite A/B (§I) — zero diff-attributable failures |
| Woo two-discovery fixture | **SATISFIED** | woo fixture test green (r5 contract; included in fs retirement suite family) |

**#25 verdict: code-level scope = PASS (no code change required this round).** Production
physical GC apply remains separately gated (close condition excludes it).

### #77 — evidence eligibility (Final Acceptance Contract items 1–9)

| AC | Verdict | Evidence |
|---|---|---|
| 1. Ingestion exclusion (future eval/**) | **PARTIAL → ops** | mechanism accepted & tested (`test_issue77_eval_boundary_via_existing_exclude_dirs`); config change is the authorized production operation |
| 2. Existing corpus 298 → 0 | **PARTIAL → ops** | PRE_COUNT refreshed 2026-09-17 = **298**; acceptance seam `CorpusRepairTool.plan(membership)` tested green this round |
| 3. Ledger/vector consistency post-op | **PARTIAL → ops** | repair apply deletes ledger row + deterministic UUIDs (contract tests green) |
| 4. Retrieval gate | **PARTIAL → ops** | post-op production probes required |
| 5. Real /ask gate | **PARTIAL → ops** | post-op production probes required |
| 6. No collateral exclusion | **SATISFIED (mechanism)** | neighbor-preservation contract tests green |
| 7. Before/after evidence | **PARTIAL → ops** | PRE captured this round; POST awaits authorized op |
| 8. Separation from #90 | **SATISFIED** | #90 untouched |
| 9. Regression gate | **SATISFIED** | `tests/pipeline/test_issue77_evidence_eligibility.py` + `tests/services/test_corpus_repair.py` = 18 passed this round |

**#77 verdict: engineering PASS (already accepted/released in `67d426d`; zero rewrite).
Remaining = authorized production operation only.**

### #91 — permanent exclusion non-convergence (Final AC items 1–12)

| AC | Verdict |
|---|---|
| 1. RED characterization | **PASS** (§G, commit `ca271cb`) |
| 2. Eligibility partition auditable | **PASS** (`ingestion_exclusions` + `excluded_docs`) |
| 3. Eligible atomic activation | **PASS** (builder tests) |
| 4. Not actionable missing forever | **PASS** (membership suppression tests) |
| 5. Second-cycle no-change | **PASS** (zero-re-embed test) |
| 6. New-content detection | **PASS** (new-member backfill test) |
| 7. Transient fail-closed | **PASS** (embed-failure tests, both levels) |
| 8. Safety preservation | **PASS** (excluded never in ledger/vector truth) |
| 9. Policy interaction semantics | **PASS** (policy-vs-safety no-mismatch test) |
| 10. Truth/observability | **PASS** (eligible/excluded/transient/activated accounting) |
| 11. #71/#82/#77 regression | **PASS** (focused + full A/B) |
| 12. Production acceptance | **PARTIAL → authorized production run** |

### #92 — source_id capacity (Final AC items 1–12)

| AC | Verdict |
|---|---|
| 1. Dependency audit | **PASS** (5 composite identity columns + sibling-risk inventory) |
| 2. RED >200 | **PASS** (StringDataRightTruncation reproduced) |
| 3. Lossless GREEN | **PASS** (byte-for-byte read-back) |
| 4. ≤200 IDs unchanged | **PASS** (control test) |
| 5. Relational integrity | **PASS** (version/lifecycle/membership/repair/recovery tests) |
| 6. Generation/vector provenance | **PASS** (e2e projection test) |
| 7. API/Admin truth | **PASS** (schemas audited: plain `str`, no truncation) |
| 8. Migration discipline | **PASS** (idempotent + manifest-registered, executed ×2 in tests) |
| 9. No workaround | **PASS** (no exclusion/hashing/aliasing) |
| 10. End-to-end fixture | **PASS** (long i18n path ledger→generation→vector) |
| 11. Regression | **PASS** (§I) |
| 12. Production acceptance | **PARTIAL → authorized production migration/deploy** |

## C. RCA

### ROOT_CAUSE_91 (P0 — non-converging sync generations)

Two engineering defects multiply into a deterministic resource-amplification loop:

1. **Whole-generation failure contract on deterministic exclusions.**
   `backend/pipeline/generation_builder.py:_build_and_activate` Phase 1 runs
   `pipeline._safety.check_content(doc.content)` per document. A deterministic, content-level
   safety rejection (reasons: `binary_content`, `secret_content`, `poor_decode` — pure functions
   of content) records `DocFailure(error_class="permanent_safety_excluded", retryable=False)`
   and `continue`s (the doc is never chunked/embedded), **but stays in the `failed` list**.
   After Phase 3 writes and embeds the entire eligible set, `if failed:` (generation_builder
   line ~336) marks the whole generation failed, cleans up ALL written objects and raises
   `IngestFailures` → **zero activation for the eligible set**.
   This all-or-nothing contract is correct for transient failures (fail-closed preservation is
   required) but is applied indiscriminately to deterministic permanent exclusions.

2. **Enumeration-vs-ingestion domain mismatch in membership reconciliation.**
   `backend/connectors/github.py:membership_source_ids()` enumerates paths with a *path-level*
   filter only (`_should_include_path` = file_types + `check_path` + `ExclusionPolicy`). Content-level
   exclusions (`check_content`) are structurally impossible at enumeration (zero-content read).
   `backend/services/membership_currency.py:reconcile_membership` computes
   `missing = enumeration − ledger_serving`, so deterministically non-ingestible files are
   **eternal actionable missing members**. `_backfill_missing_members` (scripts/sync.py) then
   re-fetches, re-chunks and re-embeds them every round — and defect 1 discards the whole round.

Production loop (proven live on tesla-t4, 2026-09-17):
`authoritative=15870, ledger_serving=5379, missing=10491` for `ne301-local` → refill 10491 →
~1h42m embed → 88 permanent exclusions poison generation → zero activation → same missing next
cron. Three consecutive cycles observed with identical failure payload. `lowpower-camera-local`
same shape (4283 missing, ~37min, 76 exclusions); `neomind-local`/`neomind-extensions-local`
same shape at smaller scale (3–4 exclusions). `wiki-documents-local` fails separately (#92).

The safety filter itself is **correct** (firmware binaries, private keys, fonts must never enter
serving truth); the defect is partition semantics, not the filter.

### ROOT_CAUSE_92 (P1 — source_id varchar(200) truncation)

`backend/db/models.py`:
- `Document.source_id = mapped_column(String(200), primary_key=True)` (:68)
- `Document.superseded_by = mapped_column(String(200))` (:88) — carries a successor document identity
- `DocumentVersion.source_id = mapped_column(String(200), index=True)` (:118) + unique index
  `uq_document_versions_source_seq` + `idx_document_versions_source_status`
- `DocumentRepairTask.doc_source_id = mapped_column(String(200), index=True)` (:930)
- `DocumentRecoveryEvent.doc_source_id = mapped_column(String(200), index=True)` (:960)

Canonical document identity is the composite `<source>/<branch>/<rel_path>` (github.py
`_make_document`). Real production Docusaurus i18n English paths exceed 200 chars
(observed live: `wiki-documents-local/main/i18n/en/docusaurus-plugin-content-docs/current/…/0-interface-and-modules-configure.md`
≈ 245 chars) → PostgreSQL `StringDataRightTruncation` on INSERT → the whole `wiki-documents-local`
sync fails every cycle (observed live 2026-09-16/17).

Source-level (config) ids live in `String(100)` columns (SyncLog/SyncRun/SyncRequest/
IndexGeneration/KnowledgeSettingsPreview) — those hold the source config id, not the composite
document identity; out of scope (recorded as observation). API Pydantic schemas use plain `str`
(no max_length) — no application-layer truncation. Weaviate props are schemaless strings.

### ROOT_CAUSE_25 (filesystem retirement closure)

Founding defect + r5 Track A state:

- Founding defect: fs/woo connectors cannot self-declare deletions (`fetch_deleted()` returns `[]`);
  refill cannot reproduce vanished source_ids (`fetch_all` filter) → permanent unrepairable
  partial health (2026-09-05 production incident: 26 ledger rows, 481/507).
- Track A (r5, contract in issue body) implemented ledger-side absence confirmation:
  `DocLifecycle.MISSING_CANDIDATE` grace (serving, Needs Attention), two consecutive complete
  discoveries → `confirm_absence_retirement` (serving-ineligible immediately,
  `gc_eligible_at = retired_at + 7d`), incomplete/failed discovery never advances counts,
  policy absence distinct (`policy_absent`, never counted), restore semantics, audit actors
  (`ACTOR_SYNC_ABSENCE`), GC scheduler + config-gated apply (`scripts/gc_lifecycle.py`),
  document-detail truth exposure. Accepted with composition gate (Role A review v1:
  ACCEPTED_WITH_COMPOSITION_GATE), composed with #82 at `ef8b3fb`
  (LIFECYCLE_COMPOSITION_ACCEPTED / INTEGRATION_ELIGIBLE=YES), shipped via r5 integration →
  r6 release (`67d426d`).
- **Current-main evidence (this round):** focused suites green on `42b205aa`:
  `test_fs_disappearance_retirement.py` + `test_issue25_lifecycle_detail.py` +
  `test_membership_currency.py` = 23 passed.
- This round therefore performs an **AC-by-AC gap audit against the Final Acceptance Contract**
  (comment 7 of #25) and only remediates PARTIAL/MISSING items.

### ROOT_CAUSE_77 (evidence eligibility — engineering/operation boundary)

- Engineering implementation (R1 `3948be2` + R2 `07d1308`) is **accepted and released** inside
  `67d426d` (deployed): class-truthful slot coverage (`evidence_selection.py`),
  user-facing composition + code-oriented competitive gate (`rag.py`, `_is_code_oriented_query`
  alias), fallback composition. Focused suites green on current main (18 passed this round).
- Remaining scope per Final Disposition + Final Acceptance Contract = **production operational
  convergence only**: `neomind-local` config `exclude_dirs += ["eval"]` → membership
  enumeration → reviewed retirement (`CorpusRepairTool.plan(membership)` accepted seam) →
  verify serving eval corpus PRE_COUNT→0 → retrieval + `/ask` probes.
- Fresh read-only PRE_COUNT (this round, 2026-09-17): **298** `neomind-local/main/eval/**`
  documents lifecycle=active (identical to historical audit baseline).
- Production mutation is **out of scope this round** (see §K remaining gates).

## DEPENDENCY_GRAPH

```
#92 (schema widening) ── independent, but #91's new exclusion table must adopt the
│                         widened identity capacity from day one (no second migration)
├──→ #91 (partition permanent exclusions)
│      ├── consumes: membership_currency.reconcile_membership (subtract exclusions from missing)
│      ├── consumes: generation_builder (partition, not fail)
│      ├── must preserve: #71/#82 reconciliation semantics (tests green)
│      └── must preserve: #77 evidence-eligibility semantics (no serving-truth change)
├──→ #25 (gap audit only; Track A already merged)
│      └── interacts with #91: absence retirement vs exclusion partition are disjoint
│              lifecycle surfaces (retirement = was serving; exclusion = never serving)
└──→ #77 (no code rewrite; regression + truth-surface verification only)
```

Cross-issue invariants I1–I10 (contract §8) are covered by the test matrix in §G/H.

## MINIMAL_IMPLEMENTATION_PLAN

1. **#92 migration first** (contract ordering: schema before dependent app code):
   - `scripts/migrate_widen_document_source_id_500.py` (idempotent; widens the 5 identity
     columns to `varchar(500)`; registered in `deploy/prod/migrations.json`)
   - `backend/db/models.py`: the 5 columns `String(200)` → `String(500)`
2. **#91 partition:**
   - new `IngestionExclusion` model (PK `(source_id, content_hash)`; String(500) identity;
     reason/detail/stage/first_seen_at/last_confirmed_at/times_confirmed/actor) +
     idempotent migration `scripts/migrate_add_ingestion_exclusions.py` + manifest registration
   - `generation_builder._build_and_activate`: deterministic safety exclusion →
     persist/upsert exclusion row + `BuildAccounting.excluded_docs` + `continue` (NOT `failed`);
     transient failures unchanged (fail-closed); activation deletes obsolete exclusion rows
     for activated identities (policy-change self-heal)
   - `IngestFailures` gains additive `excluded: list[DocFailure]` (partitioned identities stay
     visible in the failed-round accounting without poisoning the generation)
   - `membership_currency.reconcile_membership`: `missing = enumeration − serving − permanently_excluded`;
     `MembershipReconciliation` gains `excluded_ids`; truth detail gains sample; sync.py
     delta_counts gains `membership_excluded` / `permanent_excluded` additive keys
3. **#25:** AC-by-AC audit table; code change only if a gap is proven (none expected)
4. **#77:** engineering-completeness verification (already green); no rewrite; remaining
   production gates documented

## CHANGE_BOUNDARY

EXPECTED: `backend/db/models.py` (5 widened columns + 1 new table),
`scripts/migrate_widen_document_source_id_500.py` (new),
`scripts/migrate_add_ingestion_exclusions.py` (new), `deploy/prod/migrations.json` (2 entries),
`backend/pipeline/generation_builder.py` (partition + accounting),
`backend/pipeline/ingest.py` (IngestFailures additive attr only),
`backend/services/membership_currency.py` (subtraction + fact fields),
`scripts/sync.py` (delta_counts additive keys), tests (new files + additive assertions).

REQUIRED SUPPORTING (recorded if touched): `backend/api/admin/*` only if truth surfaces need
the new counts (additive schema fields); none planned beyond additive delta keys.

FORBIDDEN (contract): production mutation of any kind; lifecycle vocabulary redesign; connector
rewrite; generic best-effort partial activation; tombstone-GC defaults; #90 cleanup; exclude_dirs
as the core #91 fix; identity hashing/aliasing for #92.

## RISK_REGISTER

| Risk | Mitigation |
|---|---|
| Suppression could mask a genuine regression of ingestion capability | Exclusion rows keyed by (identity, content_hash); content change → new key → re-evaluated; activation deletes row; membership truth exposes excluded counts |
| Safety-policy change (e.g. armor regex updated) leaves stale suppression | Suppression = row ∧ identity-not-serving; if policy relaxes and content re-syncs, check_content passes → activation removes row; if file unchanged and never re-fetched, row persists but is honest (content genuinely excluded by current policy at last evaluation) |
| varchar(500) still exceeded someday | Out of scope by contract (no second identity system); 2.5× observed production max; recorded as follow-up observation |
| Weaviate/DB failure during exclusion upsert | Upsert happens inside builder session; failure raises → transient fail-closed path (no silent best-effort) |
| Shared local test DB churn across suites | SRC-prefix isolation per existing suite convention; cleanup fixtures |

## G. RED evidence

Commit `ca271cb` preserves the RED suites; executed on pristine baseline `42b205aa`:

| Suite | Baseline result | Failure mechanism observed (production-faithful) |
|---|---|---|
| `tests/pipeline/test_issue91_exclusion_partition.py` (6 tests) | **6 failed** | `build_generation` raises `IngestFailures(生成 1 构建失败(1 篇,零激活): … stage=SAFETY_FILTER class=permanent_safety_excluded detail=binary_content)` — the exact production error string; `IngestionExclusion` import fails (no persistence surface); long-identity truncation |
| `tests/pipeline/test_issue91_convergence.py` (5 tests) | **4 failed / 1 passed** | sync round ends `status=failed` with `生成 1 构建失败(1 篇,零激活)…` — the ne301-style loop reproduced end-to-end; the 1 pass = transient fail-closed control (already green at baseline, by design) |
| `tests/services/test_issue91_membership_exclusion.py` (2 tests) | **2 failed** | `MembershipReconciliation` has no `excluded_ids` surface; BIN reported as actionable `missing` |
| `tests/db/test_issue92_source_id_capacity.py` (4 tests) | **4 failed** | `StringDataRightTruncation: value too long for type character varying(200)` — production error class; migration script absent |

The transient fail-closed tests (builder + sync level) pass on BOTH trees: they protect
AC7 and were never expected to be RED.

## H. GREEN evidence

Final candidate tree — all new suites green:

| Suite | Result |
|---|---|
| `tests/pipeline/test_issue91_exclusion_partition.py` | 6 passed (partition + audit idempotency + transient fail-closed + policy self-heal + long-identity e2e projection) |
| `tests/pipeline/test_issue91_convergence.py` | 5 passed (first-cycle convergence + second-cycle true no-change/zero-re-embed + new-member detection + transient fail-closed + policy-vs-safety no-mismatch) |
| `tests/services/test_issue91_membership_exclusion.py` | 2 passed (missing suppression + control) |
| `tests/db/test_issue92_source_id_capacity.py` | 4 passed (lossless >200 insert/read-back + short-ID byte-for-byte + repair/recovery surfaces + idempotent widening of all 5 columns) |

Contract coverage map (#91 Final AC): AC1→RED table; AC2→exclusion_row_auditable; AC3→
excluded_partitioned_eligible_generation_activates; AC4/AC5→second_cycle_true_no_change_zero_reembed;
AC6→new_eligible_member_still_backfilled; AC7/AC8→transient_embed_failure tests (both levels);
AC9→policy_absence_and_safety_exclusion_no_mismatch; AC10→delta keys
`eligible_count`/`permanent_excluded`/`membership_excluded` + counters `docs_permanent_excluded`;
AC11→focused membership/generation suites green; AC12→loop-termination proven at fixture level,
production proof remains the authorized run gate.

#92 Final AC coverage: AC1→dependency inventory (§B); AC2→RED; AC3→lossless read-back;
AC4→short-ID byte-for-byte; AC5→version/lifecycle/repair/recovery relational tests; AC6→
vector props preserve exact identity (e2e projection test); AC7→API schemas use plain `str`
(audited, no truncation); AC8→idempotent migration registered in `deploy/prod/migrations.json`;
AC9→no exclusion/workaround; AC10→long-identity e2e projection test; AC11→regression green;
AC12→production gate remains.

Cross-issue invariants: I1 (membership ≠ blind ingest) reconciled domain excludes only
deterministic exclusions; I2 (permanent ≠ transient) enforced by partition vs fail-closed
split with tests; I3/I4/I5 (#25 lifecycle vocabulary untouched); I6 (lossless identity,
#92); I7 (repair cannot resurrect: excluded identities have no ledger row and are suppressed
from refill; #25 A-7 guard untouched); I8 (atomic generation preserved for the eligible set);
I9 (failures still reported — excluded are counted separately, never hidden); I10 (truth
surfaces: active/missing/permanent-excluded/retired/failed counts all exposed).

## I. Full regression

Full backend suite on the REVIEW_3 candidate tree (`tests --ignore=tests/e2e
--ignore=tests/runtime`, HF_HUB_OFFLINE=1, ~177s):

**2870 passed / 3 failed / 5 skipped / 4 errors** (second same-scope run surfaced the
shared-DB flake family: same tree, drifting failure membership — the established
four-point discipline). Every deterministic failure/error reproduced identically on
the pristine baseline `42b205aa` (clean detached worktree A/B):

| Symptom | Candidate | Baseline | Verdict |
|---|---|---|---|
| `test_gap_export` ×2 | failed | failed | baseline-existing (known signature since r5) |
| `test_lifespan_smoke` | failed | failed | baseline-existing environmental |
| `embedder/test_bge` ×4 | error (HF offline) | error (HF offline) | baseline-existing environmental |
| `test_recovery_semantics` ×4 | failed isolated | failed isolated (4F/19P identical) | baseline-existing on this machine/DB state |
| `analytics_business`/`leads` KPI family | drifts run-to-run on identical tree | same drift | shared-DB ordering flake family |

**Zero diff-attributable failures.**

Focused/subsystem evidence (REVIEW_3 tree): stale-exclusion suite 8/8 (immediate
3-cycle RED first: `38db48b`); connector fingerprint suite 3/3 (hash parity + drift +
absence semantics); existing #91 suites 12/12; builder/membership/#82/#25 focused 54
passed; #77 focused 18 passed; migration-manifest suites green; ruff clean on all
touched files.

## J. Production READ-ONLY observations

- PRE_COUNT (fresh, 2026-09-17, ssh tesla-t4 read-only SELECT):
  `neomind-local/main/eval/**` lifecycle=active = **298**; source serving total = 875.
- Live non-convergence loop observed (cron cycles 2026-09-16 16:54Z → 20:24Z → 23:53Z):
  per-cycle failures `lowpower-camera-local` (~37min/cycle), `ne301-local` (~1h42m/cycle),
  `neomind-local`, `neomind-extensions-local`, `wiki-documents-local` (StringDataRightTruncation).
  10/15 sources healthy per cycle. Backend healthy throughout; /ask unaffected.
- Wasted work quantified over the 3 observed cycles: ~2h19m of embedding per cycle
  (ne301 1h42m + lowpower 37min) is discarded by zero-activation, i.e. ~7h GPU-embedding
  per day at the current 3.5h cron cadence, until this fix deploys.

## K. Remaining production acceptance gates (NOT authorized this round)

1. **#91**: authorized production convergence proof — a previously looping source
   (e.g. `ne301-local`) no longer repeats `large missing → refill/embed → zero activation →
   same missing`; before/after counts + next-cycle no-change captured.
2. **#92**: authorized production migration (`migrations.json` entry executes on deploy) +
   `wiki-documents-local` long-path class completes sync; exact long identity verified in
   ledger + serving provenance.
3. **#77**: authorized production operation — config `exclude_dirs += ["eval"]` →
   membership/retirement plan review → apply → POST_COUNT = 0 (PRE_COUNT=298 refreshed
   2026-09-17) → fresh retrieval + `/ask` probes with no eval leakage.
4. **#25**: production physical GC apply remains separately authorized/operator-gated
   (not required for code acceptance).

## L. Risks / follow-ups

- **Semantics note (recorded, unchanged behavior):** an *already-serving* document whose
  future content turns safety-excluded will keep serving its previous version (partition
  applies to new versions; no retroactive withdrawal). This matches today's behavior for
  serving content and stays within contract; retroactive corpus re-evaluation remains the
  separate `historical_artifact_verdict` / U-12 surface.
- `source_id`-level (config id) columns remain `String(100)` (SyncLog/SyncRun/SyncRequest/
  IndexGeneration/KnowledgeSettingsPreview). Composite document identities are now 500;
  source config ids are operator-controlled short identifiers. FOLLOW_UP_CANDIDATE: none
  required now; revisit only if source ids ever approach 100.
- varchar(500) is a capacity bound, not an identity redesign; a path longer than 500 would
  still truncate-fail (honest failure, not silent corruption). Not observed in production
  (max observed ≈ 245).
- #90 (261 tombstone physical hygiene) untouched, as contracted.
- Known baseline flake families (gap_export ×2, analytics/leads KPI, lifespan_smoke,
  embedder-offline) remain repository-level hygiene items, outside this round's boundary.

## M/N. Candidate SHA / PR

- Candidate commits (branch `exec/v163-correctness-closure`, REVIEW_3):
  - `45738ef` docs: RCA + dependency graph + minimal plan
  - `ca271cb` test: RED characterization round 1 (baseline-failing evidence)
  - `468646d` migrate(#92): identity widening migration + manifest registration
  - `41917d6` feat(#92): model columns 200→500
  - `c6fc27c` feat(#91): exclusion partition + membership subtraction + accounting
  - `cc5ba38`/`a2b61ec` docs: execution report round 1
  - `fb7f1f8` test(#91): RED for stale-exclusion blocker (fails on a2b61ec behavior)
  - `5811a41` fix(#91): bounded suppression window + re-evaluation (REVIEW_2)
  - `1032954` docs: REVIEW_2 report
  - `38db48b` test(#91): RED for immediate content-change re-evaluation (no TTL)
  - `c0ae155` fix(#91): fingerprint-invalidated suppression (REVIEW_3)
  - REVIEW_3 report commit: (see git log)
- PR: https://github.com/harryhua-ai/ask-ai/pull/93 (base `main`, not merged, not deployed)
