# v1.6.4 Production Release Acceptance

```text
APPROVED_CANDIDATE: f158c779437e7faa043aea4c0ba2a7d30168062b (PR #110, Role A FINAL PASS comment 5776440064)
MERGE_SHA:          b818f8b662eca33b19f44e5fcb90cccb98cbfc34 (merge commit, parents dc5c0a0 + f158c779)
TAG:                v1.6.4 (annotated, target = MERGE_SHA, immutable)
RELEASE_SHA:        b818f8b662eca33b19f44e5fcb90cccb98cbfc34
TAG_CI_RUN:         35728080095 (test SUCCESS + build-and-push SUCCESS)
IMAGE:              ghcr.io/harryhua-ai/ask-ai:v1.6.4 (also sha-b818f8b)
IMAGE_DIGEST:       sha256:a2e1b8e564717d9a64c8f598ebd79c0e7c80ccb4651dea093a8325dd3a35625d (host-visible)
DEPLOYED_SHA:       b818f8b662eca33b19f44e5fcb90cccb98cbfc34 (deploy run 35730548575, all steps SUCCESS)
ROLLBACK_TARGET:    v1.6.3-r9 @ 926dfb7a08bf506a635a259a41b9a60ebfdb62b1 (host-local image 0ebdcf7b5300; NOT a GHCR artifact — r9 was a break-glass host build; rollback procedure = compose up with the resident image, update.sh pull step would fail)
```

## Release

- preflight: deploy run 35730548575 — release-publish guard PASS (after creating the required GitHub Release v1.6.4; first dispatch 35729710242 was fail-closed rejected pre-mutation for the missing Release, zero production impact), compatibility preflight PASS, migration plan = ledger 14 entries / zero new migrations / all previously applied (live-verified).
- tag: annotated `v1.6.4` → `b818f8b` exact (`git rev-parse v1.6.4^{commit}` verified pre-push; no collision).
- CI: 35728080095 — checkout at `b818f8b`; job test `2445 passed, 79 skipped` with job env `TEST_DATABASE_URL=…ask_ai_test` (postgres service `ask_ai_test` only); RELEASE.json `version=1.6.4 git_sha=b818f8b662eca33b19f44e5fcb90cccb98cbfc34`; in-image identity assertion PASS; pushed `v1.6.4` + `sha-b818f8b`.
- artifact: official tag CI image (no `0.0.0+main.*` identity in production).
- deploy: canonical `deploy-production.yml` dispatch → host flock → update.sh → runtime identity double-assert → Deployment success recorded.
- health: `/health` = `{"status":"ok","version":"1.6.4","git_sha":"b818f8b662eca33b19f44e5fcb90cccb98cbfc34","app_mode":"production"}`; all three services on `:v1.6.4`; backend `(healthy)`; 0 Traceback/ERROR in logs since start; basic smoke (323-token streamed factual answer with real wiki citations) PASS.

## #105 — commerce freshness (canonical normal sync only)

- pre-state (read-only, before any sync): Store truth for `5110:5950/5951` = `outofstock`, price `949/1149`, `purchasable=true`, `date_modified=2026-09-21T17:31:44`; documents rows still projected the stale v1-era mirror (`stock_status=instock`, row `date_modified=2026-09-18T14:02:32`, no commerce-sync projection); persisted chunk copy and current-generation (141) serving chunk already carried the v2 content-era `outofstock` with `commerce_synced_at=2026-09-21T17:31:44`; active-version `content_hash` unchanged (`1233ac44…`/`71b08703…`) ⇒ exactly the historical mirror-drift + UNCHANGED shape.
- sync: canonical normal sync only (`scripts/sync.py --source woocommerce-mall`, backend container, no `--reindex`, no SQL, no vector surgery). Run 1 (13:23Z): `source_changes`, 5 real METADATA_CHANGED products updated through the zero-re-embed metadata-only path. Run 2 (13:27Z): `no_change` round with **`mirror_reconciled_count=2`** — log: `mirror-drift 对账:2 篇行镜像追平(零重嵌/零新版本)`, updating exactly `5110/5950` and `5110/5951`.
- Store→ledger→serving (post): documents rows `stock_status=outofstock`, `date_modified=2026-09-21T17:31:44` (Store truth), real permalinks; persisted chunk copy `outofstock / commerce_synced_at=2026-09-21T17:31:44 / 949`; serving generation-141 chunk `outofstock / commerce_synced_at=2026-09-21T17:31:44`. `commerce_synced_at` is a projection key derived from connector `date_modified` — truthful Store snapshot semantics, no fabricated deploy-time. Note: documents-row metadata stores connector-native keys (`date_modified`); the `commerce_synced_at` projection lives on chunk copies and serving props (querying the row for the projection key returns None by design).
- idempotency: Run 3 (13:32Z) = `no_change`, `updated=0`, **`mirror_reconciled_count=0`**, unchanged 126; row/`content_hash` byte-stable; no new version (5950/5951 still 2 versions each), no re-embedding, no new generation.
- verdict: **PASS**.

## #106 — solution/case pre-pool recall (frozen #31 EN/ZH queries, real /ask)

- ZH (`我是做水表业务的,请推荐适合我的一套 OCR 抄表解决方案`, session wave164-zh-acc): intent=product conf 0.9; plan = SOLUTION_GUIDE(required) + PRODUCT_SPEC + CASE_EVIDENCE; pool 32; **first-party Case `website-camthink/case-studies/nexascent-water-meter-ocr-ne101` admitted at rank 4 with `paths=['role:case']`** — the role lane is precisely what repairs the production 0/85 miss (ZH global competition alone does not recall it). Answer generated (462 streamed tokens), internal tickets did not occupy the case slot.
- EN (`We run a water utility. Recommend an OCR meter-reading solution for us.`, session wave164-en-acc): identical plan; pool 76; **first-party Case at rank 1 with `paths=['hybrid','boost','role:case']`**; Product/Wiki evidence (water-meter-recognition solution-description / engineering-intro chunks) well represented. Lane recall primitive probed directly with the exact EN extracted query: case page recalled with and without product labels.
- EN/ZH parity: same plan/slots both languages; first-party Case present in both pools (EN rank 1 via main+lane paths, ZH rank 4 via lane-only) — semantically equivalent authority-role coverage, no systematic evidence-class disappearance by language.
- OCR authority: `EXTERNAL_CONTENT_GAP` preserved — no fabrication, no claimed retrieval, no substitute insertion; absence phrasing remained conservative (no overbroad official-absence claim observed).
- citation/isolation: sources events map to real URLs; product isolation intact (role lanes inherit the same product-label hard filter as all recall paths — the `solutions/infrastructure-monitoring` page, which carries `product=unknown`, is excluded from product-scoped queries by the accepted isolation contract, not by a lane defect; the lane primitive itself reaches the page when unqualified — probe evidence).
- cost: ≤2 role lanes/query (structural: solution+case only), `limit=10` per lane, ≤2 additional query embeddings (hybrid lanes only), no corpus-wide loop, no per-result LLM fanout (code structure + trace pool sizes 32/76, not inflated). Attribution provenance for lanes = `candidates[].paths` (`role:*`); the stream-path `stages.retrieve.buckets` attribution key is not projected on the streaming route (same family as the known #108 streaming-trace gap; non-blocking, lane membership remains provable from candidates paths).
- verdict: **PASS** (with one recorded observation, non-blocking: first-party Solution pages in the production corpus carry `product=unknown` and solution-segment titles without the lexical authority signal, so the accepted product-isolation and authority predicates keep them out of product-scoped pools. This is corpus metadata truth, not a retrieval defect; recorded for Role A as a corpus-enrichment follow-up.)

## #107 — release CI test-DSN contract

- TEST_DATABASE_URL: supplied by tag CI job env (build-image.yml line 36); referenced in run 35728080095 logs.
- lock-safety: official tag run test job GREEN (`2445 passed, 79 skipped`) — includes the #102 lock-safety suite against the intended `ask_ai_test` database; no `database "ask_ai"` harness failure.
- primary artifact path: build-and-push SUCCESS on the official tag → canonical production deploy consumed the official `v1.6.4` image.
- break-glass required: **NO** (this release used the canonical artifact path end-to-end; contrast r9's forced break-glass host build).
- verdict: **PASS**.

## Production

- version: 1.6.4; git_sha: b818f8b662eca33b19f44e5fcb90cccb98cbfc34; app_mode: production.
- health: backend `(healthy)`, zero error/traceback lines since start; DB + Weaviate reachable (acceptance queries executed live).
- smoke: streamed factual query with real citations; frozen #106 EN/ZH pair executed end-to-end; canonical single-source sync executed cleanly.

## Rollback

- required: NO (no rollback trigger fired; all acceptance gates PASS).
- target: v1.6.3-r9 @ 926dfb7a (resident host image `0ebdcf7b5300`; see header caveat — GHCR has no r9 tag because r9 was a host build).
- evidence: n/a (not exercised).

## FINAL VERDICT

PRODUCTION_ACCEPTED
