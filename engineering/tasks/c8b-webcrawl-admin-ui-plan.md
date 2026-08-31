# C8B-WEBCRAWL-ADMIN-UI Execution Contract(web_crawl 表单一等公民)

- **Task ID**:c8b-webcrawl-admin-ui | **Parent Initiative**:C8 官网爬取数据源(UI 补全)
- **Baseline Commit**:`bbfaa6a`(main = origin/main)
- **Risk Level**:**L2**(纯 admin 前端 + 测试,后端零改动)
- **Contract Authorization**:**AUTHORIZED**(2026-08-31,Role A 签发)——用户产品指令("数据源类型应含网站爬取,不该是 github");后端类型已存在,无新产品语义。
- **来源**:用户本地自测报告(2026-08-31):为爬站信息设计的数据源在表单中类型是 github,不合理。

## 1. Objective

web_crawl 在 admin 数据源表单成为一等公民:可选、可建、可正确编辑,消除"未知类型强制 github"的编辑陷阱(现状:打开 web_crawl 源编辑显示 github,保存即改型毁配置)。

## 2. Current State / Evidence(Inspect @ bbfaa6a)

| # | 事实 | 级别 |
|---|---|---|
| E1 | `DataSources.tsx:30` `SOURCE_TYPES = ["github","filesystem","woocommerce"]`;前端零处 `web_crawl`(grep 实证) | FACT |
| E2 | `DataSources.tsx:231` 未知类型归一 `"github"`(为历史 local_git 源设计);web_crawl 源落入同一分支 → 编辑陷阱 | FACT |
| E3 | 后端 connector 配置面(`connectors/web_crawl.py` docstring):`base_url`(必填)、`sitemap_url`(可选,默认 `{base_url}/sitemap_index.xml`)、`exclude_patterns`(可选 list,提供时替换默认排清单)、`crawl_delay_ms`(可选,默认 500) | FACT |
| E4 | 生产 T4 运行 website-camthink(type=web_crawl,经 API 建);本地同型可同步 | FACT |

## 3. Scope

- 表单类型清单加 `web_crawl`(展示名建议"网站爬取");
- web_crawl 表单段:base_url(必填校验)、sitemap_url、exclude_patterns(逗号分隔)、crawl_delay_ms(数字,留空=默认),附一行说明文案(sitemap 增量爬取/默认排除清单);
- 编辑回填:web_crawl 源按本类型四字段预填;保存后类型与 config 保持(不再被 github 归一);
- 列表页类型徽标显示 `web_crawl`(如现状已透传则零改动);
- 测试:配置构建/回填 round-trip 用例 + 三旧类型回归用例。

## 4. Non-goals

connector/爬取行为/后端任何改动;新增后端类型或字段;woocommerce/github/filesystem 表单行为变更;local_git 历史源 github 归一**保留不动**(其为有意设计);URL 合法性深校验(必填+trim 即可)。

## 5. Change Boundary

**Product**:允许新增 = 表单可建/可编辑 web_crawl 源;必须不变 = 三旧类型全流程、local_git 归一、同步/列表/删除行为。
**Code EXPECTED**:`admin/src/pages/DataSources.tsx`、`admin/tests/*`(或新增测试文件)。
**CONDITIONAL**:类型徽标若在别的组件(如 Badge 映射表)则同步补一行。
**FORBIDDEN**:`backend/**`、`widget/**`、`scripts/**`、DB schema、CORS。
**System**:无后端/API/schema 变更。
**Regression**:admin vitest 全量 + tsc;三旧类型创建/编辑 round-trip;local_git 归一用例仍在。

## 6. Frozen Contract

1. `SOURCE_TYPES` 含 `web_crawl`,表单可建该类型源并通过同步验证;
2. web_crawl 源编辑:类型显示正确、四字段预填、保存后 type 与 config 保持(不被归一/不被覆盖);
3. 其余类型行为零变化(含 local_git 历史归一);
4. 后端零改动。

## 7. Acceptance Criteria

| # | 验收 | 标准 |
|---|---|---|
| AC1 | 创建 | 真实 UI 选"网站爬取"→ 填 base_url 建源成功,类型徽标 web_crawl |
| AC2 | 编辑往返 | 编辑该源:四字段预填正确 → 不改任何东西点保存 → API 复核 type=web_crawl 且 config 四键不变(陷阱关闭的直接证据) |
| AC3 | 真实同步 | 触发同步 → success 且 items>0(轻量:单次同步即可,遵守 C8 限频纪律) |
| AC4 | 回归 | admin vitest 全绿 + tsc 干净;github/filesystem/woocommerce 表单 round-trip 用例过;local_git 归一用例过 |
| AC5 | 清理 | 测试源 UI 删除,不留磁盘目录则顺手清 |

Real-World Gate:AC1-AC3 必须真实 UI 操作(协议 §10),不得以单测替代。

## 8. Required Verification

TDD(表单 round-trip 先红后绿);全量 vitest + tsc;真实 UI E2E(AC1-3);验证后环境清理。

---

## 执行提示词(复制给执行端)

```text
# 任务:C8B-WEBCRAWL-ADMIN-UI(web_crawl 表单一等公民)

先读权威契约:
- /Users/harryhua/Documents/GitHub/ask-ai/docs/engineering/tasks/c8b-webcrawl-admin-ui-plan.md

要点:
1. 独立 worktree 基于 bbfaa6a(分支 worktree-exec/c8b-webcrawl-ui),TDD 先红后绿;
2. 纯 admin 前端:SOURCE_TYPES 加 web_crawl("网站爬取"),表单段四字段
   (base_url 必填/sitemap_url/exclude_patterns 逗号分隔/crawl_delay_ms 数字),
   编辑回填按本类型,**关闭"未知类型归一 github"对 web_crawl 的误伤**
   (local_git 历史归一保留);后端零改动;
3. 验证(全部实际执行):
   a. TDD + admin vitest 全量 + tsc;
   b. AC1-3 真实 UI:本地起栈,建"网站爬取"测试源(base_url=https://www.camthink.ai)
      → 类型徽标正确 → 触发同步 success 且 items>0(限频纪律,单次即可)
      → AC2 编辑往返:打开不改点保存 → API 复核 type=web_crawl、config 四键不变
      → 测试源 UI 删除(残留磁盘目录顺手清);
   c. 三旧类型 + local_git 归一回归用例确认零波及;
4. 报告:/Users/harryhua/Documents/GitHub/ask-ai/docs/engineering/tasks/c8b-webcrawl-admin-ui-execution.md
   (v2.0 §77 字段),回复给报告路径 + commit + 状态。

红线:backend/**、widget/**、scripts/** 零改动;不 push(等 Review 放行);
docs/ 不进主仓;不碰生产 T4 与 website-camthink 生产源。
```
