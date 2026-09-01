# CAMTHINK V1 — Admin P1:数据源健康语义 + 信息架构(DSH-01/02)

- TASK_ID = CAMTHINK_V1_ADMIN_P1_DATA_SOURCE_HEALTH
- 执行模式 = PARALLEL CODEX C(与 P0+P1 Integration / LLM Provider / Citation Integrity 相互独立)
- 日期 = 2026-09-01
- BASELINE_COMMIT = 76b2199ff334194a4e145c80ab844726d7e50293(main,与任务书一致)
- FINAL_COMMIT = 07e53cff7d04cca4b520b4e1f8fef2684c717a95
- BRANCH = worktree-exec/admin-p1-data-source-health(已推 origin,远程核验一致)
- WORKTREE = /Users/harryhua/Documents/GitHub/ask-ai-data-source-health

---

## 1. 调查结论(先调查,后动手)

**"50%" 不是计算 bug。** 它是两种不同口径在两处 UI 上未标注语义造成的表面矛盾。

### 1.1 "50%" 的精确定义

`GET /api/admin/analytics/source-health`(改前 `backend/api/admin/analytics.py:366-430`):

```
sync_success_rate = COUNT(sync_log WHERE status='success' AND started_at >= now()-days)
                    / COUNT(sync_log WHERE started_at >= now()-days)     -- 按源分组
```

即:**窗口内"同步次数"中成功次数的占比**——不是文档级成功率,不是内容新鲜度,更不是最近一次的结果。

关键口径细节:**`partial`(向量一致性自愈)计入分母、不计入成功数**。partial 由 `scripts/sync.py::_handle_no_change` 在"无增量但一致性校验发现缺口→自动补灌"时写入——这类运行自我修复了缺口,但在成功率里按"未成功"计。

### 1.2 窗口与分母

- 窗口 = `days` 查询参数,前端硬编码 30(`Analytics.tsx` 的 `fetchSourceHealth(30)`)。
- 24h 同步间隔的源 ≈ 最多 30 次运行。payload 根节点本有 `days` 字段,但 UI 从不渲染 → **裸百分比**。
- 3a0c766(T28)已把文档数按 `split_part(source_id,'/',1)` 前缀聚合修正,本次保留该口径。

### 1.3 "降级"的判定(改前)

硬编码阈值:`rate ≥ 0.9 → healthy;≥ 0.5 → degraded;< 0.5 → critical`。三个缺陷:
1. **禁用 ≠ 不健康**:禁用源带历史失败照样显示"降级/严重";
2. **无历史/少历史被伪造结论**:新源 1 次失败 → 0% → "严重";1 次成功 → 100% → "健康";
3. **列表由 sync_log 驱动**:从未同步的源根本不出现在洞察页。

### 1.4 "最新成功"与"50% 降级"为何合法共存

- 数据源页"最新同步" = `sync_log` 中该源 `MAX(started_at)` 的**单行**(无论成败,`data_sources.py:286-310`);
- 洞察页"成功率" = 同一张 `sync_log` 的 **30 天聚合**。
- 例:上周连续失败/补齐、12 分钟前修复成功 → 同时"最新:成功"且"30 天 50%"。**同一底层事实(sync_log/data_sources/documents,同一 Postgres),两种口径,无数据分歧**——纯粹是呈现层的语义缺失。
- 另:partial 自愈也会压低成功率而"最新成功"照常显示,加剧"看不出为什么 50%"。

### 1.5 `website` vs `website-camthink` 命名

数据源页显示 `product`(website)+ 地址副标题(www.camthink.ai);洞察页显示裸 `source_id`(创建时按 `{product}-{hash8}` 自动生成)。同一来源、无任何关联提示,且洞察页另有一列"产品"再显示一遍 product 值。确认令人困惑。

### 1.6 生产侧证据(只读观察)

本地 dev 库(ask_ai)有 `website-camthink`(web_crawl, product=website, 24h)但 **sync_log 为空**——观察到的"75 docs / 50% / 降级"来自 T4 生产数据,本次未连接生产。本地以等价种子(五黄金场景)做了活体复现,机制完全一致(生产 sync_log 曾经历 Weaviate 只读事故与 clone 回退,失败/partial 混杂后修复成功,正是 1.4 的形态)。

---

## 2. 实现

### DSH-01 健康语义(backend `analytics.py` 重写,口径不变、语义显式)

响应字段(T28 契约的超集,无删减):

| 字段 | 语义 |
|---|---|
| `window_days` | 成功率统计窗口(天),与请求 `days` 一致 |
| `success_syncs` / `partial_syncs` / `failed_syncs` / `total_syncs` | 分子 / 自愈 / 失败 / 分母,全显式 |
| `sync_success_rate` | success/total(不变;partial 计分母不计成功) |
| `last_sync` / `last_sync_status` / `last_sync_error` | **当前态**:全时间范围最近一次尝试(与 /data-sources 同口径) |
| `health` | `healthy / degraded / critical / insufficient_data / disabled` |
| `doc_count` / `chunk_count` | 内容量(T28 口径不变) |

health 判定(既有阈值一个没动):

```
disabled          enabled=False(禁用≠不健康,不作可靠性评价)     [G005]
insufficient_data enabled 且 total_syncs < MIN_SYNC_RUNS=3        [G004]
healthy           rate ≥ 0.9(样本 ≥ 3)                           ——不变
degraded          0.5 ≤ rate < 0.9                                ——不变
critical          rate < 0.5                                      ——不变
```

- 列表改由 **data_sources 全表驱动**:零历史源也出现(不缺席、不伪造结论);sync_log 幽灵行保持可见(product=unknown,T28 兼容)。
- `MIN_SYNC_RUNS=3` 为最小样本数常量,低于它不给可靠性结论(写进 docstring 与测试)。

### DSH-02 信息架构(前端)

**数据源管理 = 健康主展示位**(`DataSources.tsx`,经 `useSourceHealth()` join source_id):

- 新增 **健康(近30天)** 列:结论徽标(正常/不稳定/严重/样本不足/已禁用)+ 第二行带窗口分母的历史文案(`96% 成功 · 近30天 25 次` / `仅 2 次同步,暂不评估` / `暂无同步记录`)+ 悬停 title 给出分子分母全明细(`近 30 天 25 次同步:24 次成功 / 0 次补齐 / 1 次失败(成功率按次数计,补齐不计入成功)`)。
- **最新同步** 列升级:成功/失败/补齐/从未同步 徽标 + 时间 + 失败/补齐时**错误明细内联红字**(悬停全文)——"现在有没有问题"一眼可见。
- 新增 **内容** 列:`N 篇`(悬停含分块数)。
- 状态列(启用/禁用开关)不变;同步进行中健康数据与列表同节奏 5s 轮询。
- 健康接口失败/缺失时优雅降级为 "—",不阻塞表格。

**技术洞察 = 不再是竞争性健康仪表盘**(`Analytics.tsx`):

- 完整"数据源健康度"表格(逐源裸百分比)删除;
- 替换为一行摘要条 `数据源健康(近 30 天):正常 2 · 不稳定 1 · 严重 0 · 样本不足 2 · 已禁用 1` + 链接 `明细与操作 → 数据源管理`;无 items 时整条隐藏。

**未触碰**(按 Scope 禁令):rag.py、SourceVisibilityGuard、生成链路、引用系统、LLM Provider、tech.py 性能面、OBS-*。

---

## 3. Before / After(活体证据)

等价种子(五黄金场景源)分别灌入同一库,基线 checkout(76b2199,旧前后端,8033/5177)与本次分支(8022/5176)各截一组。证据文件:`docs/implementation/dsh-evidence-2026-09-01/`。

### 改前 — 数据源管理(datasources-before.png)

仅有 启用/禁用 + 裸时间:demo-flaky 最新一次同步**失败**但页面毫无提示;无健康、无内容量、无历史。

### 改前 — 技术洞察(analytics-before.png)

旧"数据源健康度"表:裸 `50%` 无窗口无分母;**demo-flaky 最新失败却显示"健康"**(可操作的当前态不可见);**demo-retired 已禁用却显示"降级"**(禁用≠不健康被违反);**demo-new(从未同步)整行缺失**。

### 改后 — 数据源管理(datasources-after.png)

一屏并排回答两个问题:
- **现在有没有问题**:demo-flaky → `失败` 红徽标 + `sitemap 请求超时 (ETIMEDOUT)` 红字内联;demo-new/website → `从未同步`;
- **过去稳不稳定**:demo-healthy → `正常 / 100% 成功 · 近30天 5 次`;demo-degraded → `不稳定 / 50% 成功 · 近30天 6 次`(最新`成功`与历史`不稳定`同屏共存、措辞不冲突);demo-new → `样本不足 / 暂无同步记录`;demo-retired → `已禁用`;
- 内容量:75/30/40/12/0 篇。

### 改后 — 技术洞察(analytics-after.png)

完整表格消失,仅剩摘要条 `数据源健康(近 30 天):正常 2 · 不稳定 1 · 样本不足 2 · 已禁用 1` + `明细与操作 → 数据源管理` 链接。无重复竞争仪表盘。

### API 级 before/after(同一库同一种子,只读)

| 源 | 旧 API(8033) | 新 API(8022) |
|---|---|---|
| evidence-disabled | `health=degraded`(禁用被标不健康)、无 last_sync_status | `health=disabled`,last_sync_status=success |
| evidence-no-history | **不在返回中** | 在:total=0、insufficient_data、last_sync=None |
| evidence-latest-failed | rate 0.9、无当前态 | rate 0.9 + last_sync_status=failed + error 明细 |
| 全部 | 无 window/分子/分母 | window_days=30 + success/partial/failed_syncs |

---

## 4. Golden Scenarios 覆盖

| 场景 | 后端测试 | UI 测试 | 活体截图 |
|---|---|---|---|
| G001 最新成功+历史 100% | test_thresholds_healthy_and_critical_preserved | G001 健康 | datasources-after: demo-healthy |
| G002 最新成功+历史差共存 | test_latest_sync_success_after_bad_history_coexists | G002 | datasources-after: demo-degraded(成功+不稳定同屏) |
| G003 最新失败可操作 | test_latest_sync_status_and_error_surfaced | G003 | datasources-after: demo-flaky(失败+错误内联) |
| G004 无/少历史不伪造 | test_insufficient_history_not_branded_degraded_or_zero、test_zero_history_source_still_listed | G004 | datasources-after: demo-new(样本不足,无百分比) |
| G005 禁用≠不健康 | test_disabled_source_is_disabled_not_critical | G005 | datasources-after: demo-retired(已禁用) |
| G006 主位迁移 | —(架构) | TechInsight 摘要条 2 项 | analytics-after vs analytics-before |
| G007 窗口/分母可测 | test_denominator_fields_explicit_partial_counts_in_denominator、test_response_field_set_extended_not_broken | 悬停明细 1 项 | 徽标 title 属性 |

**负向验收逐条核对**:最新成功与历史百分比已分列且措辞区分 ✓;50% 必带窗口分母 ✓;禁用≠不健康 ✓;无历史≠0% ✓;洞察页无重复主仪表盘 ✓;未引入语义复杂化(管理员看到的是更少更直的词)✓;无关联可观测性功能变更 ✓;测试全程未动生产源数据(种子仅入一次性库,证据库用后已 DROP)✓。

---

## 5. 测试与验证(TDD:先红后绿)

- **RED**:TestSourceHealthSemantics 9 项中 7 项按预期失败(缺字段/禁用被判 critical/零历史缺席);DataSources DSH 6 项失败;TechInsight 2 项对旧 Analytics.tsx 失败(git stash 验证)。
- **GREEN**:
  - backend:`tests/api/admin/` + `tests/scripts/` → **122 passed, 3 skipped**;
  - 回归:`tests/api/` + `tests/pipeline/` → **302 passed**;
  - admin:vitest **31 files / 140 passed**;`tsc -b && vite build` exit 0;
  - black 仅对两个改动文件格式化(增量)。
- 测试过程中的两个非缺陷修正:G002 种子笔误(断言 2/3 但种子 1/3,后端计算正确,修测试);T28 冻结字段集测试按超集契约更新(新增字段而非破坏)。

---

## 6. 残余风险与边界说明

1. **成功率口径本身未改**(按契约"阈值语义有效则只改呈现"):partial 仍压低成功率,但现在分子分母单列可解释。若产品日后想让 partial 不进分母,是一行口径变更+测试,当前不做静默改动。
2. **幽灵源**(sync_log 有、data_sources 无)保持可见 product=unknown,enabled 默认 True 属继承行为;真正的幽灵源清理属候选 11/另一任务。
3. **摘要条为计数级**,不逐源展开——按契约避免竞争仪表盘;逐源明细与操作一律指向数据源管理页。
4. **共享 ask_ai_test 撞车**:执行期间发现并行任务反复重建该测试库(证据行两次被清、一次 401),已按协议记录;活体证据改用一次性隔离库 ask_ai_dsh_evidence 完成后 **DROP**,未写共享 weaviate、未动 :8000 主后端、未重新下载权重。
5. `website-camthink` 生产实例的 50% 具体构成(success/failed/partial 各多少)需 T4 只读查询确认;本任务已保证升级后管理员可直接从 UI 读出该构成。

---

## 7. 变更文件(8)

```
backend/api/admin/analytics.py            # source-health 语义重写(MIN_SYNC_RUNS=3)
tests/api/admin/test_analytics.py         # +TestSourceHealthSemantics(9) +T28 冻结集超集更新
admin/src/hooks/useDataSources.ts         # +useSourceHealth()
admin/src/lib/api/techInsight.ts          # SourceHealthItem 扩展(window_days 等 5 字段)
admin/src/pages/DataSources.tsx           # 健康列/最新同步升级/内容列
admin/src/pages/Analytics.tsx             # 健康表 → 摘要条 + 跳转
admin/tests/DataSources.test.tsx          # +DSH 七项(五黄金场景)
admin/tests/TechInsight.test.tsx          # +摘要条/表格移除 两项
```

---

## 8. 交付状态

- FINAL_COMMIT = 07e53cff7d04cca4b520b4e1f8fef2684c717a95
- REMOTE_BRANCH = worktree-exec/admin-p1-data-source-health
- REMOTE_COMMIT = 07e53cff7d04cca4b520b4e1f8fef2684c717a95(本地/远程一致,已核验)
- PRODUCTION_DEPLOYED = NO(等待 T4 发布窗口;无 DB 迁移,纯增量字段)
- 报告本文件 + 证据目录均在 docs 本地仓,随本仓 commit 固化。
