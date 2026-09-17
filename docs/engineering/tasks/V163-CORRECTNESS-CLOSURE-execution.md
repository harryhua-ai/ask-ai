# V1.6.3 CORRECTNESS CLOSURE — Execution Report (#25 / #77 / #91 / #92)

Status: `WORK_IN_PROGRESS` (final status at bottom)
Executor: Role B
Date: 2026-09-17

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

## B/C. RCA

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

(pending — this section will be filled as RED suites are executed)

## H. GREEN evidence

(pending)

## I. Full regression

(pending)

## J. Production READ-ONLY observations

- PRE_COUNT (fresh, 2026-09-17, ssh tesla-t4 read-only SELECT):
  `neomind-local/main/eval/**` lifecycle=active = **298**; source serving total = 875.
- Live non-convergence loop observed (cron cycles 2026-09-16 16:54Z → 20:24Z → 23:53Z):
  per-cycle failures `lowpower-camera-local` (~37min/cycle), `ne301-local` (~1h42m/cycle),
  `neomind-local`, `neomind-extensions-local`, `wiki-documents-local` (StringDataRightTruncation).
  10/15 sources healthy per cycle. Backend healthy throughout; /ask unaffected.

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

(pending)

## M/N. Candidate SHA / PR

(pending)
