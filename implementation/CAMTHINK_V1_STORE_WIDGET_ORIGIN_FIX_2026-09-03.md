# CamThink V1 — Issue #8 Store Widget Origin 修复(Executor 执行报告)

- 日期:2026-09-03
- 执行端:Executor(独立 worktree,基线 origin/main=d4dc676)
- 状态:**CANDIDATE_READY**(待 Planner FINAL REVIEW;生产零触碰)
- 候选分支:`worktree-exec/issue8-store-origin-fix-20260903`(已推 origin)
- FINAL_COMMIT:`c83d21443732499313cb1dc3870e6ec186f24f64`
- 上游基线:`d4dc67692728a16e887b0cb8e5529d0f0564f49e`(= origin/main @ 执行时)

---

## 1. STATUS

**CANDIDATE_READY** — 自评 PASS。全部 Required 项完成并实证;无生产 mutation。

## 2. BASELINE

- 代码基线:`origin/main = d4dc676`(revert: remove accidental planner probe file)。
  本地 main 当时落后于 origin/main 6 个提交;经核查这 6 个提交净效果为零
  (`804e2b3` 曾直推过同一修复但在 25 秒内被自行 revert,commit 信息
  「preserve planner read-only boundary」——即用户要求走本候选流程;其余为
  probe/回退噪音)。`git diff 1d6f6b5 origin/main -- tests/ backend/ config/` 为空。
- worktree:`.worktrees/issue8-store-origin`,分支自 origin/main。

## 3. FINAL_COMMIT

`c83d214` — 单提交,恰 4 文件,65+/8-:

| 文件 | 变更 |
|---|---|
| `config/sites.yaml` | store 段 allowed_origins 修正(+www/-废弃子域,4+/1-) |
| `tests/services/test_site_experiences.py` | 矩阵回归钉 + 旧断言改写(59 行区) |
| `tests/api/test_site_routes.py` | `STORE_ORIGIN` 常量对齐冻结真相 |
| `tests/api/test_unified_v1_gate.py` | 同上(兼 store 产品页 URL 样例) |

远端核验:`git rev-parse HEAD origin/worktree-exec/issue8-store-origin-fix-20260903` 同为 c83d214。

## 4. ROOT_CAUSE

**因果链全环闭合(逐环有实证):**

1. **页面事实**:生产页 `https://www.camthink.ai/store/neoeyes-503/`(只读 curl,
   451KB)内嵌 `camthink-ask-ai-loader`:`SITE_ID = "camthink-store"`,
   经 `script.dataset.siteId` 传给 widget;页面浏览器 Origin = `https://www.camthink.ai`。
2. **Origin 语义**:`/store/` 是 path,不属于 Origin(RFC 6454);浏览器发送的
   Origin 头 = `scheme://host[:port]`,无路径。
3. **配置缺陷**:修复前 `config/sites.yaml` 中 `camthink-store.allowed_origins =
   ["https://store.camthink.ai", "http://42.194.138.11"]`——含不存在的独立
   store 子域(OBSOLETE),缺 `https://www.camthink.ai`。
4. **服务端校验**:lifespan 启动 `seed_default_sites` 将该 YAML 幂等 upsert 进
   `site_experiences` 表(`backend/services/site_experiences.py:169-196`,对已存在
   site_id **覆盖** `allowed_origins`);运行时 `resolve_site` 读 DB,Origin 归一化
   后**精确命中**才放行(`backend/api/routes.py:148`,`backend/services/site_experiences.py:116-155`)。
   `https://www.camthink.ai ∉ allowed` → `SiteDenied` → `HTTPException(403,
   "站点未授权或来源不受信任")`(`routes.py:74,150`)。rag 不被调用、对话不落库。
5. **用户可见文案**:widget `useSSE.ts:66` 把 403 渲染为
   「此站点未被授权使用 Ask AI。」——与生产观测逐字一致。

CORS 非本次成因:CORS 白名单是独立 env 通道(`CORS_ALLOW_ORIGINS`,
`backend/main.py:468-477`);生产 www.camthink.ai 已在其中(官网 widget 同 Origin
正常工作),浏览器请求可达服务端后被步骤 4 拒绝。

## 5. STORE_SITE_ID

**`camthink-store` — 正确,无需修正**(Requirement #6)。

生产页实证(见 §4.1):loader 内 `SITE_ID = "camthink-store"`,
`API_URL = "https://wiki-data.camthink.ai"`,`LANG = "en"`。
**无 integration mismatch。**

## 6. STORE_ORIGIN

- **权威**: `https://www.camthink.ai`(因正式 Store 位于 `https://www.camthink.ai/store/`,
  path 不进 Origin)。
- **OBSOLETE / 已移除授权**: `https://store.camthink.ai`。
- **临时保留**(按既有验收合同,不动): `http://42.194.138.11`。
- **website 不变**: `https://www.camthink.ai` + `https://camthink.ai`(apex 属
  Issue #8 既有 Frozen Contract 的 REDIRECT ONLY 项,本次零触碰——注意:用户
  曾直推的 804e2b3 顺带删了 apex,该部分超出本次合同,未采纳)。
- **wiki 不变**: `https://wiki.camthink.ai`。

## 7. CONFIG_FIX

`config/sites.yaml` camthink-store 段(唯一生产语义变更):

```yaml
  - site_id: camthink-store
    display_name: CamThink Store
    allowed_origins:
      # Issue #8 冻结产品事实:正式 Store 位于 https://www.camthink.ai/store/ ——
      # /store/ 是 path 不属于 Origin,故授权 origin = https://www.camthink.ai;
      # store.camthink.ai 为 OBSOLETE 非权威 origin,不再授权。
      - https://www.camthink.ai
      # 外部 Widget 对接测试页 /store/(同一 Origin;路径不进授权,精确命中 scheme://host)。
      - http://42.194.138.11
```

约束核验:**无通配符**(`*` 全配置面测试持续在位);**无 path 入 origin**
(canonical 不变量测试持续在位);最小变更(website/wiki 段零 diff)。

## 8. RUNTIME_APPLY_PATH

**加载路径(已核验代码)**:

```
config/sites.yaml(权威源;env SITES_CONFIG_PATH 可覆盖)
  → lifespan 启动 seed_default_sites()            [backend/main.py:266-268]
  → 幂等 upsert 进 site_experiences 表             [site_experiences.py:169-196]
     (已存在 site_id:覆盖 allowed_origins 等全部配置字段)
  → 运行时 resolve_site() 读 DB 精确匹配            [routes.py:148 / site_experiences.py:116]
```

**修改如何进入运行时(二选一,均无需 schema 迁移)**:

1. **重启后端**(推荐,随下次镜像部署自然发生):新 YAML 随 lifespan upsert
   覆盖 DB 行;
2. 或对目标库跑 `uv run python scripts/migrate_add_site_experiences.py`
   (同一 seed 函数,可在不停机下先行生效)。

无 Admin 覆盖通道(V1 无站点 origins 编辑面);DB 不是权威,YAML 永远在
seed 时赢。⚠️生产应用属 PRODUCTION_MUTATION,**本次未执行**(见 §12)。

## 9. TESTS

**新增回归钉(`tests/services/test_site_experiences.py`)** — 4 个:

| 用例 | 断言 |
|---|---|
| `test_store_production_origin_authorized` | camthink-store + Origin `https://www.camthink.ai` → **authorized**(生产故障场景) |
| `test_store_url_path_not_part_of_authorization` | camthink-store + Referer 形式 `https://www.camthink.ai/store/neoeyes-503/` → **authorized**:授权只依据 Origin,path 归一化剥除后精确命中 |
| `test_obsolete_store_subdomain_origin_denied` | camthink-store + `https://store.camthink.ai` → **rejected**(修复回归钉) |
| `test_store_origin_frozen_truth_issue8`(配置面) | YAML:store 含 www / 无废弃子域 / 无通配符;website 含 www+apex 不变;wiki 独占子域不变 |

**改写(语义对齐冻结真相,丢弃「废弃子域=合法」旧断言)**:
`test_authorized_origin_resolved`(大小写不敏感样例改 www)、
`test_official_origins_remain_authorized`(store tuple→www;website apex 保留)、
`test_unknown_site_denied`、`test_disabled_site_denied`;
API 层 `STORE_ORIGIN` 常量 → `https://www.camthink.ai`
(`test_site_routes.py` mock 行默认 origins、`test_unified_v1_gate.py` 兼产品页 URL 样例)。

**wildcard→absent** 由既有 `test_no_wildcard_or_path_origins_anywhere` 全配置面
持续覆盖 + 新配置面用例双保险。**unknown origin→rejected** 既有
`test_unrelated_origin_denied`/`test_ask_spoofed_origin_denied_403...` 持续覆盖。

**已知保留引用(有意不改)**:`normalize_origin` 纯函数样例(剥端口)、
legacy None 样例、后缀伪装 `store.camthink.ai.evil.com`(修复后为**双重**有意义:
既非精确命中也属废弃域)、`test_schemas.py` page_context URL 样例(与授权无关)。

**实证结果**(env:`TEST_DATABASE_URL=postgresql+asyncpg://…@localhost:5432/ask_ai_test`,
`HF_HUB_OFFLINE=1`,主仓 .venv + PYTHONPATH=worktree):

1. **RED→GREEN**:stash 掉 config 修复(= 旧错误配置)+ 新测试 →
   `6 failed, 22 passed`(含 3 个新钉);恢复修复 → `28 passed`。
   证明用例真实钉住本次修复,非永真断言。
2. 定向 4 文件(site_experiences / site_routes / unified_v1_gate / multilingual_gate):
   **48 passed**。
3. **全量离线回归**:**1116 passed, 6 skipped, 4 errors**(34s)。
   4 errors 全在 `tests/embedder/test_bge.py`(离线 HF 网络错误),
   **基线对照实证为既有**:stash 本次全部改动后同文件复跑 → 同样
   `18 passed, 4 errors`。账目:基线全量 1112 绿 + 本次新增 4 用例 = 1116 ✓。

## 10. PRODUCTION_ACTION_REQUIRED

本次候选合入并发布后,生产生效最小动作(需授权,非本次执行):

1. 部署含 c83d214 的新镜像(backend + sync-cron 同 sha tag,惯例)或
   临时先跑 `scripts/migrate_add_site_experiences.py`(YAML 权威 upsert);
2. 重启/滚动 backend 使 lifespan seed 覆盖 `site_experiences.allowed_origins`;
3. 验收冒烟:浏览器开 `https://www.camthink.ai/store/neoeyes-503/`,Widget
   提问应正常回答;`curl -H "Origin: https://www.camthink.ai"` 打
   `GET /api/widget/site-config?site_id=camthink-store` 应 200;负例 Origin
   `https://store.camthink.ai` 应 403。

## 11. REPORT_PATH / REPORT_COMMIT

- 路径:`docs/implementation/CAMTHINK_V1_STORE_WIDGET_ORIGIN_FIX_2026-09-03.md`
- docs 仓 commit:见该仓 HEAD(本文件即报告;commit hash 以 docs 仓记录为准)。

## 12. PRODUCTION_MUTATIONS

**NONE。** 生产零触碰:无 SSH、无镜像操作、无 DB 变更、无迁移执行。
唯一生产交互 = 只读 `curl` 抓取公开页面 HTML(§4.1 证据)。

## 13. 执行期环境异常上报(非本任务产物,未处置)

1. **origin/main 噪音提交**:804e2b3(直推修复)+325d984/dbd4a70 revert +
   3da47a6/d4dc676 probe 文件加删。净效果零,但建议后续避免直推 main
   (与本协议一致)。
2. **worktree 内两次外来写入**(均非本执行端所为,未提交、未删除):
   - `.gitignore` 曾被删去 worktrees 相关注释行(mtime 17:33:30)→ 已
     `git restore` 还原,不入提交;
   - 未跟踪文件 `datasource-design-prototype.html`(mtime 17:36:08,数据源
     中心设计原型样貌)→ 按协议保留原地,疑为并行会话 bash cwd 陷阱落错
     目录,请归属窗口自行认领。
3. **主仓 main 工作区**:`.gitignore` 有一处未提交改动,尾部出现疑似手误
   的 `ght/` 行(会话开始前已存在)——非本次产物,建议用户确认后清理。

## 14. Verdict

| Required 项 | 结果 |
|---|---|
| 1. store.allowed_origins 含 www.camthink.ai | ✅ 并移除废弃子域 |
| 2. 不使用 wildcard | ✅ 测试持续在位 |
| 3. 不把 /store/ 写进 origin | ✅ canonical 不变量测试持续在位 |
| 4. site_experiences DB/runtime 加载路径核验 | ✅ §8(yaml 权威→seed upsert→DB 运行时读) |
| 5. 测试矩阵 | ✅ §9(RED→GREEN 实证) |
| 6. Store 页 site_id 核验 | ✅ camthink-store 正确,无 mismatch |
| 7. 修复+测试+持久报告 | ✅ c83d214 已推 origin + 本报告 |

**STATUS: CANDIDATE_READY** — 待 Planner FINAL REVIEW;生产应用待授权。
