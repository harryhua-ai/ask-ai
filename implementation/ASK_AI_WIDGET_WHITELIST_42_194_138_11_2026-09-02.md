# ASK-AI Widget 白名单新增 http://42.194.138.11/ 执行报告

- 日期:2026-09-02
- 执行模式:并行 FAST-LANE 小任务(与阶段⑨「同步任务与在线服务隔离」并行,零接触)
- RELEASE_INTENT:FAST-LANE PRODUCTION HOTFIX(本窗口仅 IMPLEMENTATION + TEST + COMMIT + REPORT,未部署)
- 自评:**PASS**(AC1–AC8 全过;一处产品假设需 Planner 确认,见 §2.3)

---

## 1. Root Cause / Current Whitelist Architecture

Widget 白名单不是单一开关,而是**双层授权**,本次两层级均需覆盖:

| 层 | 位置 | 作用 | 运行时机制 |
|----|------|------|-----------|
| 服务端站点授权(权威) | `config/sites.yaml` → `site_experiences` 表 | 决定 403 与否 | lifespan 启动与 `scripts/migrate_add_site_experiences.py` 把 YAML **幂等 upsert** 进 DB(`seed_default_sites`,YAML 为权威);运行时 `resolve_site` 读 DB |
| 浏览器 CORS(执行层) | env `CORS_ALLOW_ORIGINS`(`backend/main.py:467-480`) | 决定浏览器是否放行跨域请求 | FastAPI CORSMiddleware;生产值在服务器 `.env`(不入镜像、不入仓) |

匹配语义(`backend/services/site_experiences.py::normalize_origin` + `resolve_site`):

- 请求来源优先 `Origin` 头,缺失回退 `Referer` 的 origin 部分;
- 归一化 = `scheme://host[:port]` 小写,**剥路径/查询/尾斜杠**,http 默认端口 80 与 https 默认端口 443 剥除,其余端口保留;
- 授权 = 站点存在且 enabled + 归一化后**精确命中**该站点 `allowed_origins`;scheme 是身份的一部分(http ≠ https);
- 禁止通配符(冻结契约);任何不满足 → `SiteDenied` → 403 统一文案。

## 2. Canonical Format 与决策

### 2.1 canonical 形式

用户提供 `http://42.194.138.11/`;浏览器 Origin 实际为 `http://42.194.138.11`(无尾斜杠、无路径)。
按现有规则其 canonical 形式 = **`http://42.194.138.11`**:

- 尾部 `/` 属路径,归一化剥除;
- http 默认端口 80 剥除、不显式写。

已用测试锚定:`normalize_origin("http://42.194.138.11/") == "http://42.194.138.11"`。

### 2.2 挂靠站点

`allowed_origins` 是**按站点**的。新增 origin 挂到 **`camthink-website`**,依据:外部对接者照抄的官方 Quick-Start 片段即 `data-site-id="camthink-website"`(docs/integration/CAMTHINK_ASK_AI_WEBSITE_INTEGRATION.md §1.3),且该站语义(发现/咨询)与通用对接测试页最契合。

### 2.3 ⚠️ 产品假设(Planner 确认点)

- 若外部测试页实际以 `camthink-wiki` / `camthink-store` 接入,需把同一行镜像到对应站点(每站一行,机械改动);
- 本 origin 是 **http** scheme。若对接方后续在 443 上挂 https,`https://42.194.138.11` 需另行显式新增(当前测试锚定其为拒绝,防连带放行)。

## 3. Changes

1. `config/sites.yaml`:`camthink-website.allowed_origins` 追加 `http://42.194.138.11`(附注释说明 canonical 规则);现有三站其余来源零改动。
2. `deploy/prod/.env.example`:`CORS_ALLOW_ORIGINS` 模板追加同一 origin,并注明与 sites.yaml 成对(⚠️ 生产服务器实际 `.env` 的修改属 Release Gate 职责,不在本窗口)。
3. `tests/services/test_site_experiences.py`:8 个回归用例(§5)。

**未放宽任何安全边界**:无通配符、无宽正则、无 scheme/端口规则改动;精确命中语义原样。

## 4. Files Changed(实现 commit `ebe10b8`)

```
config/sites.yaml                       |  3 +++
deploy/prod/.env.example                |  4 +-
tests/services/test_site_experiences.py | 48 +++++++
3 files changed, 54 insertions(+), 1 deletion(-)
```

## 5. Tests(真实 whitelist path,非仅字符串断言)

服务层用例走**真实路径**:repo `config/sites.yaml` → `seed_default_sites` 真实 upsert 进隔离 Postgres → `resolve_site` 完整授权判定。

新增 8 用例:

1. `test_bare_ip_trailing_slash_is_canonicalized` — `http://42.194.138.11/` → canonical `http://42.194.138.11`;
2. `test_bare_ip_integration_origin_allowed_for_website` — Origin(带尾斜杠)与 Referer(带路径)均命中 camthink-website;
3. `test_unlisted_bare_ip_variants_denied_for_website` — 相邻 IP `42.194.138.12`、`https://42.194.138.11`、`http://42.194.138.11:8080` 全部拒绝;
4. `test_bare_ip_origin_scoped_to_website_only` — wiki/store 不被连带授权;
5. `test_repo_yaml_origins_are_canonical` — YAML 全量来源 canonical 不变量(防未来手写污染);
6. `test_bare_ip_integration_origin_listed_for_website_only` — YAML 清单位置锚定(仅 website);
7. (既有)`test_unrelated_origin_denied` 等原有拒绝/精确匹配用例全绿;
8. API 层 `tests/api/test_site_routes.py` 既有 403/无副作用用例全绿。

### 测试执行证据

- 目标文件(隔离一次性库 `ask_ai_test_wl42`,用后已 DROP):**33/33 PASS**(含全部新用例逐条 PASSED,pytest -v 输出留档于本报告 git 历史);
- 全量 backend 套件(同隔离库,`HF_HUB_OFFLINE=1`):**958 passed / 4 failed / 5 skipped**;
- 4 个失败全部位于 `tests/embedder/test_bge.py`(BGE 模型加载 OSError,文件内顺序依赖):在**未改动的 main@193f206 主仓基线复跑同文件,同样 4 个失败** —— 既有测试隔离缺陷,与本改动无关(与 09-02 集成门记录的「embedder 4 失败=基线既有测试隔离缺陷」一致);
- 共享库 `ask_ai_test` 在并行执行期被其他窗口反复重建导致首次运行 `db_engine` setup ERROR(已知干扰),改用一次性隔离库取证后稳定;
- Widget 前端未触碰 → 无需 widget build/typecheck;`black` 对新增代码已格式化(仅触及新增行)。

## 6. Acceptance Criteria

| AC | 结论 | 证据 |
|----|------|------|
| AC1 目标 origin 通过白名单 | PASS | §5 用例 2(真实 YAML+DB 路径) |
| AC2 canonical 格式正确 | PASS | `http://42.194.138.11`;§5 用例 1、5 |
| AC3 无 wildcard/宽匹配放宽 | PASS | diff 仅追加一行来源;零规则改动 |
| AC4 未授权 Origin 仍拒绝 | PASS | §5 用例 3、4 + 既有 spoofed/unrelated 拒绝用例 |
| AC5 现有 allowed origins 无回归 | PASS | 三站既有来源零改动;既有全部站点用例绿 |
| AC6 相关测试实际执行 PASS | PASS | 33/33;全量 958 绿/4 失败=main 基线同败;widget 前端 N/A |
| AC7 未触碰 Data Source/Sync 主线 | PASS | 变更仅 §4 三文件,与 ingest/sync/RAG/admin 零交集 |
| AC8 无生产访问/部署/变更 | PASS | 全程本地;生产零接触(§7) |

## 7. Production Access Statement

**PRODUCTION_ACCESS: NONE。** 本窗口未 SSH/未触碰 tesla-t4、未改生产 `.env`、未触发迁移、未构建/推送镜像、未 merge main。

## 8. Scope Audit

- 与阶段⑨ ingest-safety worktree(`f481f94`@`.worktrees/ingest-safety`)零接触;基于 main@193f206 独立 worktree `.worktrees/widget-whitelist-42-194-138-11`,独立分支 `fix/widget-whitelist-42-194-138-11`;
- worktree 内 `.env` 为物理拷贝(契约要求,未提交);`models` 软链仅本地测试便利,均不入 commit;
- docs 本地仓报告单独 commit,未夹带其他窗口 dirty 文件。

## 9. Final Commit 与 Release 组成

- BASELINE_COMMIT: `193f206`(main,= 当前生产基线 sha-193f206)
- IMPLEMENTATION_COMMIT: **`ebe10b8`**(branch `fix/widget-whitelist-42-194-138-11`,单 commit)
- **WIDGET-WHITELIST-ONLY RELEASE 组成** = 生产基线 193f206 + ebe10b8(2 个文件改动 + 测试),不含任何 Data Source Reliability / Sync / 其他 worktree 内容。

### 9.1 Release Gate 必办(Planner/发布窗口,非本窗口)

1. 服务器 `.env` 的 `CORS_ALLOW_ORIGINS` 追加 `http://42.194.138.11`(模板已在 ebe10b8 同步,实际 `.env` 在服务器上,不入镜像);
2. 新镜像上线后,lifespan `seed_default_sites` 会按 YAML 幂等 upsert(自动写入新 origin);如需不重启即生效可跑 `scripts/migrate_add_site_experiences.py`;
3. 生产验收按 RELEASE 需求清单 1-9(含现有三站接入无回归、未授权 origin 仍 403)。

## 10. Final Response 快照

```
STATUS: PASS
BASELINE_COMMIT: 193f206a3d0e8695f1c40766a1ba54667fcba2fb (main = 生产基线)
IMPLEMENTATION_COMMIT: ebe10b8 (fix/widget-whitelist-42-194-138-11,基线 193f206)
FILES_CHANGED: config/sites.yaml; deploy/prod/.env.example; tests/services/test_site_experiences.py
WHITELIST_ARCHITECTURE: 双层 = sites.yaml→site_experiences 表精确 Origin 授权(YAML 权威幂等 upsert) + CORS_ALLOW_ORIGINS 浏览器层;normalize_origin=scheme://host[:port] 小写剥路径/默认端口,精确命中,无通配符
CANONICAL_ALLOWED_ORIGIN: http://42.194.138.11 (挂在 camthink-website)
TESTS: 隔离库 33/33 绿(8 新用例);全量 958 passed/4 failed(=main 基线既有 embedder 隔离缺陷,已对照复现);widget 前端未触碰
ACCEPTANCE: AC1-AC8 全 PASS
PRODUCTION_ACCESS: NONE
RELEASE_INTENT: FAST-LANE PRODUCTION HOTFIX
RELEASE_STATUS: READY FOR PLANNER REVIEW(组成 = 193f206 + ebe10b8,widget-whitelist-only)
```
