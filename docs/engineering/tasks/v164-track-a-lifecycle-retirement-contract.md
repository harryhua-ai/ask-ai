# v1.6.4 Track A Contract — Lifecycle Retirement & GC Closure (#25)

- Status: FROZEN WHAT / Boundary / Acceptance (implementation HOW open)
- Owner track: A · Issue: #25 · Base: main `5c501914` · Gate: v1.6.3 COMPLETE + drift check
- Factual basis: [v164-engineering-reality-audit.md](./v164-engineering-reality-audit.md) §1 (residuals 1–6)

## 1. Product semantics frozen (WHAT)

A-1. **Disappearance must be confirmable.** When a full, authoritative discovery of a source completes with the existing completeness guarantees, the difference between the ledger and the authoritative listing is a first-class lifecycle fact. For connectors that cannot declare deletions (filesystem; WooCommerce today), ledger-side confirmation (the mirror of the existing vector-side `EXTRA_CONFIRMED_RETIRED`) must be able to drive retirement. Git-backed and crawl-backed connectors already prove removals and keep doing so.

A-2. **Two consecutive confirmations to retire.** The first complete discovery observing an item absent ⇒ the item enters the existing `missing_candidate` grace state (still serving; visible as Needs Attention with reason). A second consecutive complete discovery observing the same absence ⇒ the item is RETIRED (leaves serving immediately per the frozen TB-P1 projection; `gc_eligible_at = retired_at + 7d`). Any incomplete/failed/low-coverage discovery is not a confirmation and does not advance the count.

A-3. **Policy absence is not source removal.** Items invisible because of `include_dirs` / `file_types` / exclusion policy must never be confirmed as removed by A-2; the design must classify them distinctly and surface them (Needs Attention with a policy reason), and a subsequent policy re-inclusion must restore them without resurrection side-effects.

A-4. **RETIRED/withdrawal/GC semantics are already frozen** (TB-P1): immediate withdrawal at the confirming commit, RETIRED retained 7 days, GC purge = generation-namespace objects + chunk rows, version metadata rows retained (audit). Track A reuses these unchanged — no state-model redesign.

A-5. **GC runs automatically, applies explicitly.** A production-safe scheduled trigger for the existing GC sweep must exist (wired like the sync-cron pattern), reporting by default; physical apply is config-gated and the first production apply is a controlled, recorded operator action (dry-run output archived). Tombstone GC stays opt-in-by-config (default off, unchanged).

A-6. **Retirement is auditable in data, not just logs.** Every retirement decision (tombstone, discovery-confirmed retire, GC purge) persists its reason, evidence (e.g. discovery run identifiers / confirmation count), and actor; idempotent re-execution changes nothing. The existing #50 document-detail surface displays the persisted reason.

A-7. **Reconciliation stays explicit.** No silent auto-heal is introduced; gap-repair behavior remains as-is (recorded, explicit). Track A must not widen repair to resurrect source-confirmed-removed content.

## 2. Boundary

- No changes to: lifecycle state vocabulary, serving projection semantics, retrieval filters, citation, evidence semantics (Track B/C territory), #50 IA (data-only), sync scheduling semantics for ingestion itself.
- Additive schema only (e.g. confirmation/persisted-reason fields); no destructive migration; production migration (if any) follows the one-time-container pattern with backup + verify.
- Connector capabilities may differ (proof mechanisms differ) but the lifecycle contract above is generic — filesystem and WooCommerce must both be able to reach RETIRED via A-2.
- `set_successor` (doc-level identity supersession) is out of scope for A unless B1's variation identity work requires it; if still unwired at iteration end it is explicitly recorded as a dormant capability, not silently dropped.

## 3. Acceptance

Unit/integration (must all be new or extended tests, green on the integration tree):

1. fs e2e: delete a file → sync #1 ⇒ `missing_candidate` + Needs-Attention bucket with reason; sync #2 (complete) ⇒ RETIRED; serving projection excludes it immediately; `gc_eligible_at = retired_at + 7d`.
2. Policy-absence: excluding a suffix/pattern never advances the absence count; distinct surfaced reason; re-inclusion restores.
3. Transient/failed/partial discovery resets or does not advance confirmation (existing G004-class guards continue to pass).
4. Woo fixture: ledger item absent from API listing for two complete discoveries ⇒ same flow as (1) (fixture-level; no live-store dependency in CI).
5. Idempotence + audit: re-running a confirming sweep changes nothing; persisted reason/evidence readable via admin detail endpoint.
6. GC trigger: scheduled sweep executes (dry-run) in integration; apply mode config-gated; purge behavior identical to existing suite.
7. Red lines: full backend suite green; serving-projection/fail-closed tests unchanged and passing.

Runtime acceptance (staging-or-controlled): the (1) chain exercised against a real filesystem source end-to-end; wiki/woo sources show zero unintended lifecycle movement (regression truth walk).

Production acceptance (post-deploy, controlled): operator deletes a designated file in a designated fs source; #50 shows missing → retired with persisted reason; serving stops; scheduled GC dry-run output recorded; (optional, explicit) first real `--apply` recorded with GCReport. Wiki 467 / woo counts stable.

Issue #25 closure: A-acceptance + production exercise recorded; delta audit flips R10/R3(automatic)/R6(persistence) to IMPLEMENTED.
