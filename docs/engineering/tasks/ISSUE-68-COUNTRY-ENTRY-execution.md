# Issue #68 执行报告 — Conversation Review 权威 Country/Region + Entry Channel

- Claim: `harryhua-ai-20260918T080904-ce39b4bb`(mode=implement,authority=allowed)
- Branch: `agent/68/b740a638`(base = `055451f` = main tip,零漂移起点)
- Contract: issue #68 body `ght-contract` v1 + `docs/engineering/tasks/CONVERSATION-REVIEW-PRODUCT-UI-CONTRACT-20260917.md`
- 状态: **CANDIDATE READY — 待 Role A review**(本报告 = Candidate 移交,不含 merge)

## 0. 契约准入备注(机械修正留痕)

A 批准的契约块 `authority.implementation` 值为 `authorized`,不是 v3 合法枚举
(`allowed|investigation-only`)。经 PO 指令授权做单 token 机械修正
`authorized → allowed`(语义零变化,issue 评论 5727135122 留痕),随后 claim。

## 1. 基线审计(实施前,契约要求的 fresh baseline/drift review)

| 契约预判 | 实测 | 一致 |
| --- | --- | --- |
| `Conversation.country String(10)` 已存在 | models.py:232 | ✓ |
| `session_id`/`site_id` 已存在且索引 | models.py:234/243 + idx_conversations_site/session_id | ✓ |
| `channel` 是 transport 语义(Admin UI 提供 widget/discord) | Conversations.tsx 渠道 select;后端 `Conversation.channel` 默认 widget | ✓ |
| 列表/详情 API 不暴露 country/site/session | admin/conversations.py 原始响应 | ✓ |
| 无 Country/Entry 服务端过滤 | 同上 | ✓ |
| **Accept-Language 启发式**是现有 country 唯一来源 | routes.py(旧)167-173:`en-US → US` | ✓(缺陷确认) |

**审计新增发现(契约外相邻面,已一并按呈现门处理)**:
`backend/api/admin/business.py` 地域分布聚合直接消费 `Conversation.country`
(WHERE country IS NOT NULL),即把 legacy 启发式值当地理事实呈现 —— 与 AC3
冲突,已加 `country_source IS NOT NULL` 同源门(见 §3.7)。

## 2. RED(先红后绿,因正确原因红)

新增四组测试,先于实现提交前运行确认失败形态:

| 文件 | RED 形态 |
| --- | --- |
| tests/services/test_geo_country.py(17 例) | `ModuleNotFoundError: geo_country`(模块不存在) |
| tests/db/test_country_truth_migration.py(4 例) | fixture TypeError/列不存在(迁移脚本不存在) |
| tests/api/admin/test_conversations_country_entry.py(9 例) | `Conversation(country_source=...)` TypeError(列缺失) |
| tests/api/test_routes_country_persistence.py(3 例) | Settings 无 `country_resolution_mode` 字段 |

GREEN 后 **40/40 全绿**。

## 3. 实现(GREEN)

### 3.1 权威 resolver — `backend/services/geo_country.py`(新)

- 唯一入口 `resolve_request_country(request, settings) -> (country, source)`;
  输出只有 ISO 3166-1 alpha-2 或 None;返回接口无 raw IP 位置(IP 仅瞬时参与
  解析,不落库/不进日志)。
- 权威序:①受信 ingress geo 头(`country_ingress_header` 显式配置)→
  ②服务端 GeoIP(`geoip_database_path`,geoip2 惰性加载,不可用降级 Unknown)→
  ③Unknown。
- **显式信任边界**:转发 geo/XFF 仅当直连 peer ∈ `geo_trusted_proxy_cidrs`;
  空 CIDR = 无人可信;GeoIP 模式下 XFF 第一跳仅在 peer 受信时采信。
- Accept-Language/locale/timezone/问题文本不在输入面(接口即证据,测试覆盖)。
- 模式值非法按 off 处理 + 告警;解析链路任何异常 fail-honest → Unknown。

### 3.2 配置 — backend/config.py(4 个新字段,env 注入)

`COUNTRY_RESOLUTION_MODE`(off 默认)/`COUNTRY_INGRESS_HEADER`/
`GEO_TRUSTED_PROXY_CIDRS`(逗号分隔)/`GEOIP_DATABASE_PATH`。
默认 off ⇒ 部署零配置时行为 = 恒 Unknown(fail-honest,不回归任何现有行为)。

### 3.3 模型 + 迁移

- `conversations.country_source VARCHAR(20) NULL` + `idx_conversations_country`。
- `scripts/migrate_add_country_truth.py`(幂等,已登记 deploy/prod/migrations.json
  第 13 条):加列/建索引按 catalog 判定;**legacy 处置 = 转换 Unknown**
  (`country_source IS NULL AND country IS NOT NULL → country=NULL`,契约 AC3
  两个可选路径中取"转换",禁止 silent grandfathering)。
- **呈现门**(双保险):API 投影层 `_surfaced_country` 只在 `country_source`
  非空时把 country 作为地理事实呈现 —— 迁移执行窗口内旧代码写入的行也诚实。

### 3.4 /api/ask 写入路径 — backend/api/routes.py

- 删除 Accept-Language 启发式块,替换为 resolver 单一调用;
- 两个 Conversation 创建点(budget-declined + 主路径)均持久化
  `country` + `country_source`;
- `apply_lead_turn(country=...)` 自动继承权威值(销售线索新数据归真)。

### 3.5 Admin API — backend/api/admin/conversations.py

- 列表/详情响应新增:`country`(呈现门后)、`country_source`、
  `entry: {site_id, display_name} | None`(site_id → SiteExperience.display_name
  服务端权威投影;站点配置缺失 → None,无 URL/channel 猜测)。
- 新过滤参数(服务端、分页/计数前、与既有过滤器组合):
  `country`(ISO alpha-2 或 `UNKNOWN`,pattern 校验,非法 422)、
  `entry`(site_id 或 `UNKNOWN`)。
- 新候选端点(viewer+ 只读):`GET /conversations/entry-options`(站点标识+权威
  标签)、`GET /conversations/country-options`(仅可信来源值去重排序;
  注册在 `/{conversation_id}` 之前避免 UUID 路由吞并)。

### 3.6 Admin UI — admin/src(渐进增强,无表格化/无重设计)

- 过滤行在渠道 select 后新增 **访问入口**(全部入口/未知入口/站点权威标签,
  候选来自 entry-options)与 **国家/地区**(全部/未知/可信码,候选来自
  country-options);entry/country 支持 URL 深链(与 intent/channel 同模式)。
- 卡片问题行新增紧凑元数据 `GeoEntryMeta`(`AR · 官网`;Unknown 中性呈现
  "未知 · 未知";title 携带完整值含 site_id);容器加 flex-wrap 适应窄宽。
- 详情侧栏新增 chips:国家/地区(含权威来源 title)、入口(含站点标识 title);
  与列表同源。
- 既有 channel(transport)筛选原样保留,命名"渠道";新维度命名"入口" ——
  契约兼容性门:已实证现有渠道过滤语义 = transport(widget/discord),
  两个过滤器语义不同、视觉不同、命名不混淆。

### 3.7 相邻面矫正 — backend/api/admin/business.py

地域分布聚合增加 `country_source IS NOT NULL`(legacy 值不再进入地理分布)。

## 4. 测试与验证

### 4.1 目标测试(40/40 GREEN)

- resolver 单元 17:AC1(语言/时区不可判定 + off 默认)、AC2(伪造头拒绝/
  受信头接受/非法值 fail-honest/未配置头名或 CIDR 恒 Unknown/XFF 仅受信 peer/
  IP 不外泄/接口无 IP 位置)。
- 迁移 4:legacy 转 Unknown、trusted 保留、幂等(二跑 no-op)、
  列+索引缺失重建分支(物理 DROP 后迁移重建,再次 legacy 转换)。
- Admin API 9:呈现门(legacy 不呈现)、entry 投影、country/UNKNOWN/entry/
  UNKNOWN 过滤、组合过滤+计数一致、非法 country 422、详情同源、
  两候选端点。
- /api/ask 持久化 3(production-like,真实 ASGI + 真实测试库 + 真实 resolver,
  budget-declined 探针不经 LLM):受信 ingress → `("US","ingress")` 落库;
  伪造头非受信 peer → Unknown;仅 Accept-Language → Unknown。

### 4.2 全量回归

| 面 | 结果 |
| --- | --- |
| backend pytest 全量 | **2958 passed / 2 failed / 7 skipped**(37min);
  2 failed = test_gap_export 窗口继承时间炸弹(**基线既有**:种子日期
  2026-09-11 随真实时间跌出 7d 窗口;在未含本候选的干净 worktree
  ask-ai-v163-correctness 同样复现 2 failed)。本轮曾出现的 14 个 ask 流
  500 失败已定位并修复(见 §3.8),修复后相关文件重跑全绿 |
| admin vitest | **600/600**(73 文件;含 mock 面更新的 2 个既有页面测试 +
  新增 GeoEntryMeta 3 例) |
| tsc -b | exit 0 |
| vite build | PASS |

### 4.3 唯一既有测试改动及理由

- `tests/api/admin/test_analytics_business.py::test_business_overview_geo_pct_and_90d`:
  原断言"无来源 country 值进入地域分布"恰是被契约禁止的 legacy 呈现语义;
  改为权威值播种 + 断言 legacy 行被排除(count==1 各)。
- `tests/ConversationsReview.test.tsx` / `tests/FinalPolish.test.tsx`:
  useConversations 模块 mock 工厂补齐新增的 useEntryOptions/useCountryOptions
  (mock 面扩展,断言不变)。

### 4.4 视觉验收(AC7/AC15,对照真实当前基线)

evidence/issue68/(1536×1024,真实登录态 + 真实 dev 数据):

1. `01-list-with-country-entry.png` — 列表:过滤器行 [渠道|入口|国家/地区|...],
   卡片 `AR · 官网` / `DE · Wiki` / `未知 · 未知` 中性呈现,问题优先级/密度不变;
2. `02-filter-country-DE.png` — country=DE 服务端过滤:恰 1 行,总数=1;
3. `03-detail-country-entry-chips.png` — 详情 chips:国家/地区 AR(权威来源
   ingress)、入口 官网(站点标识 title)、渠道 widget 独立;
4. `04-filter-entry-web.png` — entry=官网:恰 2 行(含 无国家·官网 行,
   证明 entry 维度独立于 country 信任),总数=2。

### 4.5 生产化注意(部署时)

- 迁移 `scripts/migrate_add_country_truth.py` 已登记清单,部署编排按冻结发布树
  在 rollout 前执行(幂等,在线安全)。
- 生产启用权威来源需运维显式配置(二选一):
  ingress 模式 = `COUNTRY_RESOLUTION_MODE=ingress` + `COUNTRY_INGRESS_HEADER=<头名>`
  + `GEO_TRUSTED_PROXY_CIDRS=<边缘网段>`;或 geoip 模式 = `...=geoip` +
  `GEOIP_DATABASE_PATH=<MMDB>`。未配置 = 恒 Unknown(诚实缺省)。

### 3.8 回归期发现与修复 — mock 测试面 settings 缺失

ask 流测试(reliability/multilingual/routes/gap_export 共 14 例)直接构造
`app.state` 而不经过 lifespan,首轮全量回归中出现 500
(`State has no attribute 'settings'`)。修复:routes 侧防御式读取
`getattr(app.state, "settings", None)`,resolver 对 None 按 off 处理
(→ Unknown)—— 与未配置部署语义一致,生产零影响;修复后上述文件 55/57 绿
(余 2 = §4.2 基线既有)。

## 5. 契约验收对照(AC1-AC7)

| AC | 证据 |
| --- | --- |
| AC1 RED 证明语言系不能定国家 + trusted→ISO/untrusted→Unknown | test_geo_country 17 例 + test_routes_country_persistence 3 例 |
| AC2 显式信任边界、伪造头非权威、raw IP 不暴露不保留 | resolver 接口无 IP 位置 + 信任边界用例;Admin 响应无 IP 字段(模型零新增 IP 列) |
| AC3 legacy 不呈现为地理事实 + provenance 区分 | 迁移转换 + 呈现门 + business.py 门 + Admin API 测试 |
| AC4 channel 保持 transport;Entry=site_id 权威投影;列表=详情 | 渠道 select 保留 + entry 投影测试 + 截图 3 |
| AC5 服务端过滤先于分页/计数、组合、UNKNOWN 一等 | Admin API 过滤测试(counts 断言)+ 截图 2/4 |
| AC6 保留紧凑高密度 UI,无表格化/常驻列/多Pane | 截图 1-4;卡片元数据行渐进增强 |
| AC7 聚焦前后端测试绿 + 截图对照基线 | vitest 600/600 + 40/40 + evidence 4 张 |

## 6. 边界与不做

- 未动 #87(Thread,独立契约)、#48、未做销售线索存量清洗(线索 country 经
  写入路径自动归真;存量线索语义属 Sales Lead 面,超本契约,留 A 裁决);
- 未引入新 PII;未改 product 语义;未触生产;
- 依赖零新增(geoip2 为可选运行时依赖,惰性导入;不装即 Unknown 降级)。

## 7. Candidate

- Branch: `agent/68/b740a638`(推送后以 PR 为准;ght preserve 记录 exact SHA)
- 交付物 = 本报告 + 代码 + 测试 + 迁移 + 截图证据。
- **STOP:等待 Role A review;不自行 merge。**
