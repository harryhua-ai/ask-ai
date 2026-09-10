# ISSUE #21 实施执行报告 —— 当前知识健康 vs 历史同步可靠性(呈现层语义分离)

- 日期:2026-09-10
- 分支:`fix/21-current-vs-historical-health`(自 main `b5e27a1` 切出)
- 状态:CANDIDATE READY(不合并、不部署,待 Role A 独立评审)
- 前置发现报告:issue #21 评论(RCA:两层缺陷 = analytics `health` 字段历史语义未标注 + 三处前端呈现把它读成当前严重度)

## 1. 根因回顾(一句话)

`GET /analytics/source-health` 的 `health` 字段本来就是 **30 天滚动成功率分档**(历史可靠性参考信号),
但接口无语义标注、前端三处(DataSources 列头/徽章、Analytics 摘要、SourceHealthPanel 同步维标签)
把它渲染成与当前知识健康(W2 `/sync-health` 权威)同词表的严重度红牌 ——
历史 30 天低成功率被读成「当前知识不可用」。

## 2. 冻结的产品决策(实施不越界)

- 当前知识健康权威 = W2 `GET /admin/sync-health` 五维,优先级链与词表**一字不动**;
- 历史同步可靠性 = 30 天滚动成功率,**数学/阈值/分母规则零改动**
  (healthy ≥0.9 / degraded ≥0.5 / critical <0.5;partial 计分母不计分子;MIN_SYNC_RUNS=3);
- 所有面向用户的呈现必须让「历史」不可误读:显式历史措辞 + 历史低成功率不得用当前严重度(destructive)样式;
- GPU→CPU 成功回退保持非严重:回退证据(「降级原因」)照旧呈现,不改判当前健康;
- 真实当前退化(连接失败/一致性退化/新鲜度过期)**继续可见**,本次不隐藏任何信号。

## 3. 变更清单(8 文件,+150/−17)

### 后端(增量兼容,API 旧字段原样保留)

| 文件 | 变更 |
| --- | --- |
| `backend/api/admin/analytics.py` | ① docstring:`health` 语义改述为「历史窗口可靠性参考信号,非当前知识健康(当前权威 = W2 /sync-health)」;② 每条 item 增加增量字段 `"signal": "historical_reliability"`(+`sync_success_rate` 显式回显)。30 天数学、分档阈值、字段集合(超集契约)不动。 |

### 前端(三处呈现 + 回退证据保持)

| 文件 | 变更 |
| --- | --- |
| `admin/src/pages/DataSources.tsx` | 列头 `同步健康 (近30天)` → **「历史可靠性 (近30天)」**;`HEALTH_META.critical` 徽章 `严重/destructive` → **`低成功率/outline`(中性)**,附注释说明红色 destructive 保留给当前态(启用/禁用/删除失败等)。 |
| `admin/src/pages/Analytics.tsx` | 摘要 critical 计数 `严重 N` → **「历史低成功率 N」**;degraded `不稳定 N` → **「偏低 N」**;标题 → **「数据源历史可靠性(近 30 天)」**;容器新增 `data-source-health-signal="historical_reliability"`;`SourceHealthSummary` 改为 export(供测试直呈)。 |
| `admin/src/components/dataSources/SourceHealthPanel.tsx` | W2 五维面板中同步维标签 `同步` → **「同步(历史30天)」**(该维徽章仍逐字本地化后端词表,语义由历史卡片标题限定);当前态四维(连接/覆盖/新鲜度/一致性)与 overall 徽章词表**不变**。 |
| `admin/src/lib/dataSourceObservability.ts` | 零改动 —— `fallbackLabel` 「降级原因：{reason}」原样保留(回归测试锁定)。 |

## 4. 测试(全部绿)

### 后端:`tests/api/admin/test_analytics.py`

- 新增 `TestSourceHealthHistoricalSignal`:
  - `test_items_carry_historical_reliability_signal`:播种 4 同步 1 成功 → `health == "critical"` **且** `signal == "historical_reliability"`;同时锁定窗口数学(4 总数/1 成功/成功率 0.25)不变;
  - `test_signal_present_on_all_items`:全量 item 均携带 signal 标注。
- 既有 `test_response_field_set_unchanged`(超集冻结契约)登记新增 `signal` 字段(增量兼容,注释标注 #21)。
- 全量后端:**2190 passed, 8 skipped**。

### 前端(admin)

- 新建 `admin/tests/issue21HistoricalHealth.test.tsx`(5 条):
  1. 同步维标签为「同步(历史30天)」,critical 徽章(「严重」=W2 词表原文)落在历史卡片内;
  2. 当前态四维标签不变且保持主位;
  3. overall/维度徽章不引入新词表(正常 ×3、evidence 原样直呈);
  4. Analytics critical 计数「历史低成功率 2」,无历史限定的「严重」不出现;偏低 1;标题 + signal 属性;
  5. `fallbackLabel("cuda_oom")` = 「降级原因：cuda_oom」回归。
- 新增 `DataSources.test.tsx` #21 describe:列头「历史可靠性 (近30天)」在、旧「同步健康 (近30天)」不在;「低成功率」在、「严重」不在;tooltip 分子/分母明细保留(登记 `sync_success_rate` 防 NaN)。
- 既有断言随冻结措辞更新(均为呈现层文案断言,不触逻辑):
  - `dataSources/SourceHealthPanel.test.tsx`、`DataSources.test.tsx`(懒加载/悬停两条):同步维 heading `同步` → `同步(历史30天)`;「严重」徽章 → 「低成功率」;
  - `TechInsight.test.tsx`:摘要标题 → 「数据源历史可靠性(近 30 天)」、`严重 1` → `历史低成功率 1` 并反向断言 `^严重` 不出现。
- 全量 admin:**296 passed(46 文件)**;`npm run build`(tsc -b && vite build)通过。

## 5. 明确确认(交付契约逐条)

1. **W2 当前健康优先级不变**:`_overall_health` 链 EXCLUDED→RECOVERING→EMPTY_*→ACTION_REQUIRED→STALE→PARTIAL→INSUFFICIENT_DATA→HEALTHY 零改动;`sync_runs.py`、`SourceHealthPanel` 徽章词表未触碰(仅同步维卡片标签加历史限定)。
2. **30 天可靠性数学不变**:`analytics.py` 的 `_health`/成功率/分母规则零 diff;测试同时锁数值与分档。
3. **成功回退保持非严重**:回退证据照旧以「降级原因：…」呈现(回归测试),未进入任何当前严重度通道。
4. **真实当前退化仍可见**:五维面板连接/一致性/新鲜度维与 DSH 表「最新同步」列原样;历史低成功率仅换措辞与样式,没有任何信号被删除或隐藏。

## 6. 越界自查(全零)

未改 30 天数学/阈值;未改健康与同步引擎;未做宽泛 Admin 重设计;未触碰生产(全部只读);
未删任何历史证据;未动 #34/#45/#26–#31;未合并;未部署。

## 7. 已知残留(供 Role A 参考)

- `/analytics/source-health` 端点本身仍是历史窗口口径 —— 本issue按冻结边界只做语义标注与呈现分离,
  端点级口径重构(如改名/迁移)不在范围内;
- 徽章样式 `variant: outline` 与「不稳定/degraded」同族中性样式,视觉上历史低成功率与偏低同级 —— 有意为之(历史信号不做当前严重度分级);
- Admin 全局 queryClient 的「操作失败」重复 toast 为 #4 评审已记录的既有化妆性问题,与本issue无关,未顺手修改。

## 8. 候选与交接

- 分支:`fix/21-current-vs-historical-health` @ `02465b4`(base = main `b5e27a1`,切出时零漂移;执行报告随分支提交)
- 看板:#21 → In review
- 交接:待 Role A 独立评审(契约/范围/工程/运行时/真实世界五门);REAL-WORLD 生产观察按 Sprint 发布门统一执行。
