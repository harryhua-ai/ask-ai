# CAMTHINK_V1_P0B1_CORPUS_RECOVERY_RELEASE_ARTIFACT_2026-09-02

- Gate: P0-B1 — P0-A 修复 → Production Candidate Docker Image(发布工件)
- 执行窗口: 2026-09-02(本地 + GitHub Actions;**PRODUCTION ACCESS = NO**,零生产操作)
- 工作树: `/Users/harryhua/Documents/GitHub/ask-ai/.worktrees/technical-insights`(复用 P0-A worktree,未新建)
- 结论: **PASS** —— 候选镜像 `ghcr.io/harryhua-ai/ask-ai:sha-3bf945b` 已由权威 CI 构建并推送 GHCR,身份双向可追踪,可作为 P0-B2 唯一部署候选

---

## 1. Workspace / Lineage

| 项 | 值 |
|---|---|
| BASELINE_COMMIT | `1ed84bbfcad08224c8c322f7c7a7a817b8916147`(当前生产 RC) |
| CANDIDATE_COMMIT | `3bf945bdc80829efabe5134dbc99711508d92b47`(branch tip,worktree clean) |
| BRANCH | `release/camthink-v1-rc-2026-09-01` |
| WORKTREE | `.worktrees/technical-insights` |
| P0-A fix | `7c535d3d43b84cc10658057af23d3a851133d549` ✓ 在 lineage(`git merge-base --is-ancestor` 通过) |

## 2. Exact Diff / Release Composition(1ed84bb → 3bf945b)

活跃代码变更(非 docs)**仅 3 文件**:

| 文件 | 归属 | 验收状态 |
|---|---|---|
| `backend/pipeline/ingest.py`(+108/−27 逻辑) | P0-A prune/delete 文档局部性 | 已验收(P0-A PASS) |
| `tests/pipeline/test_ingest.py`、`tests/pipeline/test_ingest_prune_document_local.py` | P0-A 回归 | 已验收 |
| `deploy/prod/docker-compose.yml`、`deploy/prod/update.sh` | PA-0B 部署机制修复 | 已验收且已在生产 tooling 目录字节级部署(PA-0C/0D 实测) |

其余 `1ed84bb..3bf945b` 均为 `docs/` 下各 Gate 报告(无运行时影响)。

**并行 Codex B/C/D 污染审计**:
- Codex B(product-ux-closure-b):分支领先候选 **1 commit**(`cd12687` gitignore chore)—— **不在候选内**;
- Codex C(sales-lead-capture):**0 commits** 领先(仍停在已验收 main tip `76b2199`);
- multi-site-widget:0 commits 领先(`2d27dd8` 是已验收 RC 的一部分,属预期祖先);
- **UNAUTHORIZED_CAPABILITY_COUNT = 0**。

## 3. Re-executed Verification(本 Gate 全新执行,非引用旧报告)

- P0-A 关键回归全新跑(临时本地 Weaviate 1.28 容器):`test_ingest_prune_document_local`(18,含 document-local/收缩/兄弟隔离/幂等/部分失败/delete_document)+ `test_ingest` + `test_ingest_accounting` + `test_sync` + `test_vector_consistency` + `tests/db` → **87/87 passed**(3.69s)。
- CI 亦在 ubuntu-latest 上独立重跑了单元+关键集成(pipeline/retrieval/connectors/db),绿(见 §4)。
- 重点复验项:document-local uuid prune ✓ / shrink ✓ / sibling+token+path 隔离 ✓ / 幂等 ✓ / 部分失败安全 ✓ / delete_document 安全 ✓。

## 4. Authoritative Linux Build(项目既有 release path,无新机制)

- 触发:`gh workflow run build-image.yml --ref release/camthink-v1-rc-2026-09-01`
- **CI Run: 33584420796**,headSha `3bf945bdc80829efabe5134dbc99711508d92b47`,ubuntu-latest,~10 分钟 → **completed / success**
- 测试 job(单元+关键集成)→ 构建 job(native linux/amd64,非 QEMU)→ 推送 GHCR

## 5. Artifact Identity(双向追踪,registry API 核验)

| 项 | 值 |
|---|---|
| IMAGE | `ghcr.io/harryhua-ai/ask-ai:sha-3bf945b` |
| IMAGE_TAG | `sha-3bf945b`(immutable short-SHA tag;**latest 不作为身份**) |
| INDEX_DIGEST | `sha256:cfa05d1f33e0c27e13e93ec15cc8827e2b0b6d855ed400cd157c44684714b412`(tag `sha-3bf945b` 的 `Docker-Content-Digest`) |
| AMD64_DIGEST | `sha256:990147cca9d8871d0419a21869843df5cdb29f9257601a7887464158f21f2fd5`(manifest 响应头回读一致) |
| CONFIG_DIGEST | `sha256:d2d397935293104de9a29a939df0680c234b8e54cd4708a04c1c222f40950a54` |
| PLATFORM | `linux/amd64`(index 内 amd64/linux;另有 unknown/unknown attestation manifest) |
| IMAGE_GIT_SHA | `3bf945bdc80829efabe5134dbc99711508d92b47` |

**双向追踪证明**(config blob 实测):
- OCI label `org.opencontainers.image.revision = 3bf945bdc80829efabe5134dbc99711508d92b47`;
- 历史 `RUN |1 GIT_SHA=3bf945b… echo "git_sha=$GIT_SHA" > /app/.git-sha`(与生产 `/app/.git-sha` 读取机制一致);
- CI run headSha = candidate commit = image revision,五级链:Commit → CI Run 33584420796 → tag `sha-3bf945b` → index/manifest digest → config GIT_SHA。

## 6. P0B1-G001..G010

| 验收 | 结果 |
|---|---|
| G001 lineage 含 P0-A fix | PASS(merge-base --is-ancestor) |
| G002 无 Codex B/C/D 未验收能力 | PASS(分支级 commit 审计,计数 0) |
| G003 P0-A critical regression 全绿 | PASS(87/87 全新跑) |
| G004 既有回归无新增失败 | PASS(pipeline/db 等同日基线一致;CI 绿) |
| G005 权威 Linux Docker build PASS | PASS(run 33584420796 success) |
| G006 GHCR 发布成功 | PASS(registry API 可见 tag+manifest) |
| G007 immutable identity | PASS(sha-3bf945b + digest 锚定) |
| G008 git_sha == Candidate Commit | PASS(label + history 双证) |
| G009 linux/amd64 可识别 | PASS(index platform + manifest 回读) |
| G010 未访问 Production | PASS(零 SSH/零 pull/零变更) |

## 7. Production Access Statement

PRODUCTION_ACCESS = NO;PRODUCTION_MUTATION = NO。全程仅:本地 worktree、本地一次性 Weaviate 容器(已销毁)、GitHub Actions、GHCR registry API 匿名读。

## 8. Proposed P0-B2 Recovery Inputs(只读计划,未执行)

1. **部署顺序**(复用 PA-0D 隔离模式,不跑 update.sh 全程):
   ① `cd /home/ubuntu/ask-ai && ASKAI_IMAGE_TAG=sha-3bf945b docker compose -f deploy/prod/docker-compose.yml up -d backend`(健康门:~120s 轮询,`/app/.git-sha` 应读出 `3bf945b…`);
   ② `… up -d sync-cron`(同 tag;启动即跑增量,PA-0E 语义);
   ③ 回滚锚:backend=当前 `sha-1ed84bb`(镜像 ID `05f7d396…`);sync-cron 回滚同 tag。
2. **website-camthink recovery 命令路径**(任选其一,均在部署①②之后):
   - 管理端内联(推荐,PA-0F 实证 backend 进程可 embed):`POST /api/admin/data-sources/website-camthink/sync`;
   - CPU 覆盖一次性(PA-0E 验证模式):`cd /home/ubuntu/ask-ai && ASKAI_IMAGE_TAG=sha-3bf945b docker compose -f deploy/prod/docker-compose.yml run --rm -e EMBEDDER_DEVICE=cpu sync python scripts/sync.py`;
   - 依赖 GPU 容量解决后由 cron 自然收敛(当前 15.37/15.56G 常驻,不可依赖)。
   ⚠️ 修复镜像部署前禁止以上任何重灌(P0-A 残留风险)。
3. **恢复后验收 counters**(对照 PA-0F 基线):
   - Weaviate 总量:126,204 → 预期 126,204 − 163 + (~348~361) ≈ **126,389~126,402**;`source_type=web_crawl` ≈ **348~361**;
   - 账本↔实际收敛:下一 cron 轮 `sync_log.website-camthink = success`(PA-0F 时为 failed/refill-OOM);
   - 逐篇抽查(如 `ai-species` 账本 4 ↔ 实际 4);
   - `channel_visibility`:api=widget=总量(trust boundary 语义零变化);
   - backend:health 200、Restarts=0、git_sha=`3bf945b…`;一次受控检索冒烟引用恢复页;
   - conversations/traces 计数按冒烟 +1。
4. **风险**:sync-cron 旧镜像若未随①②对齐,仍按旧语义跑(恢复前必须完成②);GPU 容量问题未解前 cron 侧任何新内容 embed 仍会 OOM(PA-0F P1,与恢复正交);恢复会以新抽取内容覆盖旧 web_crawl 内容(−11 块级内容漂移为合法语义)。

## 9. Final Commit

本 Gate 仅新增本报告:REPORT_COMMIT 见交付(工作树 tip)。

**STATUS = PASS**
