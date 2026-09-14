# V1.6.3-r3 Production Release / Runtime Acceptance

- Date: 2026-09-14 (Asia/Shanghai; evidence timestamps are UTC)
- Frozen release candidate: `5eac2b2b84d63a5889d8cb229e40e2bb083745d5`
- Authorized tag: `v1.6.3-r3`
- Final verdict: **BLOCKED**
- Acceptance manifest: `deployments/acceptance/1.6.3-r3.json`

## Verdict and boundary

The exact `v1.6.3-r3` tag was built and deployed successfully. The release
identity, ordered release migrations, backend/API behavior, Admin runtime,
Conversation ID policy read, and normal `/api/ask` path all passed their
runtime checks.

Overall runtime acceptance is **BLOCKED**, because a pre-existing production
security-hygiene defect was observed during authenticated runtime acceptance:
the production environment does not define `ADMIN_PASSWORD`, while the
application retains a built-in administrator credential fallback. The finding
was not introduced by this release and was not modified or hidden. The task
requires the affected acceptance gate to stop for Role A's remediation
decision. No rollback was performed because no r3-induced material runtime
regression was observed.

This report does not close Issues, declare the v1.6.3 iteration complete, or
authorize further remediation.

## 1. Release identity freeze

Before tag mutation, a fresh remote fetch established:

| Check | Evidence |
|---|---|
| `origin/main` | `5eac2b2b84d63a5889d8cb229e40e2bb083745d5` |
| `v1.6.3-r3` before creation | Absent |
| worktree before tag | Clean |
| created tag | Annotated tag object `808b1f1030a83696ebbaa1b431d69973d1d49d3c`, peeled commit `5eac2b2b84d63a5889d8cb229e40e2bb083745d5` |
| existing `v1.6.3-r2` | Remains object `0c66e04698c8a2be4de77231e94101883b919d40`; not moved, rewritten, deleted, or reused |

The tag was pushed normally and independently verified on the remote. No
force push or tag rewrite was used.

## 2. Tag build and artifact identity

The tag-triggered Build & Push workflow was run as GitHub Actions run
`34858174770`:

- head branch: `v1.6.3-r3`
- head SHA: `5eac2b2b84d63a5889d8cb229e40e2bb083745d5`
- Test job `104023085247`: success
- Build & Push job `104024168377`: success
- image tags: `ghcr.io/harryhua-ai/ask-ai:1.6.3-r3`,
  `ghcr.io/harryhua-ai/ask-ai:v1.6.3-r3`, and
  `ghcr.io/harryhua-ai/ask-ai:sha-5eac2b2`
- OCI index digest:
  `sha256:badce352e54b939c89dad8577bcabeb37f9facb7dcec660d10cb776bda30a89f`
- linux/amd64 manifest digest:
  `sha256:3368c07a0b90e6ff0ad910a63ff50988115a32b10f05b53cdd31ea3f1fcfabaa`
- OCI revision: `5eac2b2b84d63a5889d8cb229e40e2bb083745d5`
- OCI version: `1.6.3-r3`
- in-image `RELEASE.json` assertion: version and git SHA matched exactly

The in-image release file was independently read from the release image:

```json
{
  "version": "1.6.3-r3",
  "git_sha": "5eac2b2b84d63a5889d8cb229e40e2bb083745d5",
  "built_at": "2026-09-14T14:53:37Z",
  "image": "ghcr.io/harryhua-ai/ask-ai:v1.6.3-r3",
  "ci_run_id": "34858174770"
}
```

Artifact mapping:

```text
v1.6.3-r3
  -> 5eac2b2b84d63a5889d8cb229e40e2bb083745d5
  -> ghcr.io/harryhua-ai/ask-ai:v1.6.3-r3
  -> OCI index sha256:badce352e54b939c89dad8577bcabeb37f9facb7dcec660d10cb776bda30a89f
  -> production containers with the same tag, digest, OCI revision, and RELEASE.json identity
```

The first deployment dispatch, run `34859980850`, stopped at the repository
release-publish guard because GitHub Release `v1.6.3-r3` did not yet exist.
It performed no SSH or production mutation. The normal repository release
step then created the published immutable GitHub Release id `388492035`
targeting the frozen SHA. The local release-integrity guard passed all six
invariants, and the deployment was retried.

## 3. Pre-deployment production identity

Pre-deployment observation at `2026-09-14T14:48:41Z` (UTC):

- `/health`: `version=1.6.3-r2`
- production SHA: `fd5ca39d7ee1097abe10de513ce7e595f159270a`
- backend/sync image: `ghcr.io/harryhua-ai/ask-ai:v1.6.3-r2`
- r2 image RepoDigest:
  `ghcr.io/harryhua-ai/ask-ai@sha256:ae27e391c103a52629f5a025bbe6be89db50a103637db10d8f6441beee8a71a4`
- backend, sync-cron, sync-executor, Postgres, and Weaviate were running;
  backend/Postgres/Weaviate health checks were healthy and restart counts were
  zero.

## 4. Deployment procedure and migration result

Successful deployment workflow: `34860165030`, from main at the exact frozen
candidate SHA. The repository-defined production path was used:

```text
release-publish guard
  -> create in_progress deployment
  -> execute deploy/prod/migrations.json in declared order using the frozen image
  -> SSH production update.sh with v1.6.3-r3
  -> health and exact runtime identity verification
  -> record deployment success
```

Authoritative deployment record:

- deployment id: `6440060612`
- ref: `5eac2b2b84d63a5889d8cb229e40e2bb083745d5`
- status id: `18330134501`
- final state: `success`
- description: `success v1.6.3-r3 @ 5eac2b2b84d6`

Exactly the six migrations in `deploy/prod/migrations.json` ran, in order:

1. `scripts/migrate_add_site_launcher_presentation.py` — completed
   idempotently, zero backfill.
2. `scripts/migrate_p1_lifecycle_foundation.py` — schema and lifecycle
   verification passed; scanned `148001`, supplemented `0` properties,
   copied `3` chunks, ghosts `0`, NUL corrections `0`; final validation had
   `null_current=0`, `multi_active=0`, and `missing_ordinal=0`.
3. `scripts/migrate_add_track_c_product.py` — additive columns and repair/
   recovery tables completed; content-type backfill `0` rows.
4. `scripts/migrate_add_sync_delta_counts.py` — `sync_log.delta_counts`
   ready; idempotent completion.
5. `scripts/migrate_add_frontmatter_slug_property.py` — Weaviate schema
   property `frontmatter_slug` present; this migration does not backfill
   existing objects.
6. `scripts/migrate_add_conversation_id_policy.py` — completed; the active
   policy row is readable after deployment.

No extra migration, production backfill, manual schema change, or unrelated
maintenance was executed.

## 5. Independent production identity after deployment

Final independent remote check at `2026-09-14T15:30:35Z` (UTC):

```text
local /health : {"status":"ok","version":"1.6.3-r3","git_sha":"5eac2b2b84d63a5889d8cb229e40e2bb083745d5","app_mode":"production"}
public /health: {"status":"ok","version":"1.6.3-r3","git_sha":"5eac2b2b84d63a5889d8cb229e40e2bb083745d5","app_mode":"production"}
```

Running service identity:

| Service | Image | OCI revision | Version | Restart | State |
|---|---|---|---|---:|---|
| backend | `ghcr.io/harryhua-ai/ask-ai:v1.6.3-r3` | `5eac2b2b84d63a5889d8cb229e40e2bb083745d5` | `1.6.3-r3` | 0 | running, healthy |
| sync-cron | `ghcr.io/harryhua-ai/ask-ai:v1.6.3-r3` | same | `1.6.3-r3` | 0 | running |
| sync-executor | `ghcr.io/harryhua-ai/ask-ai:v1.6.3-r3` | same | `1.6.3-r3` | 0 | running |
| Postgres | `postgres:16-alpine` | n/a | n/a | 0 | running, healthy |
| Weaviate | `cr.weaviate.io/semitechnologies/weaviate:1.28.0` | n/a | n/a | 0 | running, healthy |

The production release image RepoDigest was
`ghcr.io/harryhua-ai/ask-ai@sha256:badce352e54b939c89dad8577bcabeb37f9facb7dcec660d10cb776bda30a89f`.
The runtime image ID was
`sha256:3a9f69adea3de96fa8b5bb0c550b7dd08d1024b5e56ef6a3b545e1a69ffa8243`.

Independent in-container `RELEASE.json`, `/health`, Admin release API,
container tag, OCI revision, and deployment record all agree on r3 and the
frozen SHA.

## 6. Runtime acceptance evidence

### Backend and data path

- `GET /api/admin/system/release`: HTTP 200; version, SHA, image tag, and CI
  run `34858174770` match the release artifact.
- `GET /api/admin/system/conversation-id-policy`: HTTP 200; active strategy
  `uuid4`, readable from the production policy store.
- `GET /api/admin/system/runtime`: HTTP 200.
- `GET /api/admin/data-sources`: HTTP 200; 15 production data sources.
- Internal Weaviate schema inspection confirms `frontmatter_slug` is present.
- `OPTIONS /api/ask` from `https://wiki.camthink.ai`: HTTP 200 with the exact
  allowed origin.
- Widget site-config requests for the production Wiki, Website, and Store
  identities returned HTTP 200 with their configured production origins.
- Production Admin assets (`/admin/`, JS, CSS, widget JS/CSS) returned HTTP
  200.

### Normal `/api/ask` smoke

A normal production request asking “What interfaces does NE503 support?”
returned HTTP 200 and the complete SSE sequence `sources`, token events, and
`done`, with no error events. The returned Conversation ID was
`1e5a6242-6f78-46c1-814d-768b82285179` (length 36). The normal smoke path
created a regular conversation record; no direct administrative data write
was used.

Five returned citations were independently fetched successfully: three
GitHub blob URLs returned HTTP 206 under the range probe, and two CamThink
blog URLs returned HTTP 200. The captured GitHub sources include the NE503
specifications, core-board connection, and overview documents. This preserves
the accepted provenance/citation behavior; no guessed Wiki URL was introduced
by the release acceptance probe.

### Admin browser runtime

Real production Admin browser session: `https://wiki-data.camthink.ai/admin/`,
viewport `1536×1024`, DPR 1.

- System Information loaded and visibly showed `1.6.3-r3`, the complete
  frozen SHA, `production`, exact image tag, CI run, `/health=ok`, and loaded
  Tesla T4 runtime state.
- Data Sources loaded with 15 sources and existing source statuses/actions.
- Conversation Review list visibly abbreviated long IDs, for example
  `ID 1e5a6242…5179` while its full value remained available as the row
  tooltip.
- Opening the real smoke conversation visibly rendered the complete
  `1e5a6242-6f78-46c1-814d-768b82285179` and the copy control.
- Automated browser clipboard evidence after clicking the copy control:

  ```json
  {"expected":"1e5a6242-6f78-46c1-814d-768b82285179","copied":"1e5a6242-6f78-46c1-814d-768b82285179","equal":true,"copiedLength":36}
  ```

- At 1536px viewport width, `document.documentElement.scrollWidth` was
  `1536`, equal to `window.innerWidth`; horizontal overflow was false. The
  complete ID was present in the detail DOM. The detail style permits normal
  wrapping if a narrower layout requires it.
- System Information browser console: 0 messages. The initial login page
  had two favicon 404 messages; these are pre-existing static-resource
  omissions, not release-induced application errors.

Retained screenshots:

- `output/playwright/v163-r3-runtime/conversation-review-list-abbreviated.png`
- `output/playwright/v163-r3-runtime/conversation-detail-full-id-copy.png`
- `output/playwright/v163-r3-runtime/system-information-r3.png`

### Existing production observations

The Data Sources UI still displays an existing Website sync/embed failure
(`HTTP 413`, content/batch size related) in its historical operational status.
This was observed as pre-existing production state and was not altered or
reclassified as an r3 regression. Other tested Wiki/FS/Store sources remained
operational.

## 7. Findings and stopped gate

The authenticated Admin smoke exposed the following pre-existing finding:

- production environment variable names include database/JWT settings but no
  `ADMIN_PASSWORD`;
- the deployed application therefore retains its built-in administrator
  credential fallback path;
- the fallback path was sufficient for the authorized Admin login used by
  this runtime check;
- the repository already records this as an operational security risk;
- no credential, environment value, or application code was changed in this
  release task.

This is not evidence of an r3 code regression, but it is a real production
defect discovered during acceptance. The security-hygiene gate is therefore
**BLOCKED** and requires Role A direction. It must not be silently fixed or
treated as accepted by this report.

## 8. Rollback readiness

- Previous immutable release: `v1.6.3-r2`, remote tag unchanged.
- Repository rollback mechanism: the same production `update.sh` path with
  an explicitly selected immutable prior tag.
- Rollback executed: **No**. There was no r3-induced material runtime
  regression requiring rollback; the stopped gate is a pre-existing security
  hygiene finding.
- `v1.6.3-r3` was not moved, rewritten, deleted, or replaced.

## 9. Persistence

The acceptance manifest and this report are committed together. The commit
SHA is supplied in the execution response after the report commit is pushed;
that documentation commit does not change the frozen release tag or the
running production image.

**V163_R3_PRODUCTION_RUNTIME_ACCEPTANCE = BLOCKED**
