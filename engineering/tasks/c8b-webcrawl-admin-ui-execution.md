# C8B-WEBCRAWL-ADMIN-UI Execution Report

- **Task / Initiative**:c8b-webcrawl-admin-ui / C8 官网爬取数据源(UI 补全)
- **Worktree / Branch**:`/Users/harryhua/Documents/GitHub/ask-ai-c8b-webcrawl` / `worktree-exec/c8b-webcrawl-ui`
- **Baseline → Final Commit**:`bbfaa6a` → `7249ee7`
- **Status**:**CANDIDATE READY**(不 push,等 A Review)

## Files Changed

| 文件 | 变更 |
|---|---|
| `admin/src/pages/DataSources.tsx` | SOURCE_TYPES + web_crawl;zod schema 四字段 + base_url 必填 superRefine;TYPE_LABELS + 网站爬取;sourceLocation/buildConfig/dsToForm 三处 web_crawl 分支;表单 web_crawl 段(四字段+说明文案);类型下拉 option 改用 TYPE_LABELS 中文可读名(值不变) |
| `admin/tests/DataSources.test.tsx` | 新增 C8B 用例组(6)+ 三旧类型 round-trip 回归组(4);mock 工厂 mutateAsync 提升 hoisted 共享 + 补 usePreviewDirs mock;4 处既有选择器随中文可读名更新 |

后端零改动(契约 Frozen #4 满足)。

## Implementation

1. **表单可建**:`SOURCE_TYPES` 增 `web_crawl`,下拉 option 展示 `TYPE_LABELS` 中文(代码仓库/文件目录/商城/网站爬取),`value` 保持原始 key。
2. **四字段段**:`type === "web_crawl"` 渲染 站点地址 base_url(必填,zod superRefine「站点地址必填」)/ Sitemap 地址(可选)/ 排除路径(逗号分隔)/ 抓取间隔毫秒(数字)+ muted 说明文案(按 sitemap 增量爬取;留空用默认值/默认排清单)。
3. **buildConfig(与 connectors/web_crawl.py 约定对齐)**:`base_url` 恒写(trim);sitemap_url/exclude_patterns/crawl_delay_ms 留空时**不写键**(connec­tor 默认 `{base_url}/sitemap_index.xml`、默认排清单、500ms)。⇒ 最简 config round-trip 后仍只有 base_url(用例锁定)。
4. **编辑回填 + 陷阱关闭**:`dsToForm` 的 `known` 判定因 web_crawl ∈ SOURCE_TYPES 不再落入 github 归一;四字段按本类型预填;local_git 历史归一分支保留原样。
5. **列表**:`TYPE_LABELS.web_crawl="网站爬取"`(徽标);`sourceLocation` 补 web_crawl → base_url(http 渲染为可点击链接)。

## Supporting Changes(非契约 EXPECTED 的伴随面)

| 变更 | Why / Blast Radius / 回归证据 |
|---|---|
| 类型下拉 option 从裸 key 改中文可读名 | 契约 §3「展示名建议"网站爬取"」的落地点;仅展示层,select value 与提交 payload 不变;AC4 三旧类型 round-trip 用例全过;既有 4 处测试选择器同步更新(getByDisplayValue 断言改为「中文可读名 + toHaveValue(原始key)」,#1 local_git 归一用例断言反而更强:值级校验) |
| 测试 mock 工厂改造(hoisted mutateAsync + usePreviewDirs) | 纯测试基建,为 payload 断言与 DirPicker 渲染所需;不影响产品代码 |

## Verification actually executed

1. **TDD 先红后绿**:新增 6 用例先行运行 → 6 failed(红,587/596/617/641/652/662 行)/既有 24 passed → 实现后同文件 31/31 passed(绿)。
2. **全量 vitest**:30 files / **123 passed**。
3. **tsc**:`npx tsc -b` exit 0(worktree widget 需 `npm ci` 后通过——纯环境依赖,非代码问题)。
4. **AC1(真实 UI,worktree admin dev :5175 → 本地后端 :8000 @ bbfaa6a)**:类型下拉四选项含「网站爬取」;选型后四字段段出现;填 product=c8b-e2e + base_url=https://www.camthink.ai 创建成功,列表行徽标「网站爬取」+ 副标题 https://www.camthink.ai。截图:`/tmp/c8b-e2e/ac1-create-form.png`、`/tmp/c8b-e2e/ac1-list-badge.png`。
5. **AC2(编辑往返)**:编辑该源 → 类型显示「网站爬取」(option selected)、base_url 预填、说明文案在;不改任何东西点保存 → API 复核(附 curl 实测响应):`type: "web_crawl"`,`config: {"base_url": "https://www.camthink.ai"}` 与创建时逐字节一致 → **github 归一陷阱关闭的直接证据**。截图:`/tmp/c8b-e2e/ac2-edit-prefilled.png`。
6. **AC3(真实同步,单次)**:UI 触发同步 → sync_log 实测:`status=success, items_new=130, items_updated=368, duration_ms=165932`;documents 表 c8b-e2e 前缀 115 行(>0)。UI 行「最新同步 08-31 14:48」。截图:`/tmp/c8b-e2e/ac3-sync-triggered.png`、`/tmp/c8b-e2e/ac3-sync-done.png`。
7. **AC4 回归**:三旧类型(github/filesystem/woocommerce)编辑不改点保存 round-trip 用例过(type 保持、config 关键键不丢);local_git 归一用例过。

## Runtime / Real-World Self-Check 与环境清理(AC5)

- 测试源 UI 删除(confirm 弹窗 dialog-accept)→ 列表 innerText 无 c8b-e2e、API 列表剩余 0;
- 磁盘:`data/uploads/data-sources/` 无 c8b-e2e 目录(web_crawl 无上传物,预期);
- 后端删除源**不级联**清 documents/sync_log/weaviate 向量(全类型既有行为,见 Deviations)——本次测试自身残留已精确清场:weaviate 删 143 向量、documents 删 115 行、sync_log 删 1 行,复查全部归 0;本地 website/local/ne101 等既有源零触碰。

## Deviations / Risks

1. **[观察,上报 A,不属本契约]** 后端删除数据源不级联清理 documents/sync_log/weaviate 向量(本次 c8b-e2e 删除后实测三者残留)。属既有行为、backend/** 在 FORBIDDEN 内,未动;建议后续立项(与 sync-consistency 孤儿向量治理同族)。
2. 下拉中文可读名为展示层 HOW 落地(见 Supporting Changes),payload 零变化,三旧类型回归过。
3. crawl_delay_ms 表单值非法(非数字)时不写键(connector 默认 500)——Input type=number 已约束,未做深度 URL/数字校验(契约 Non-goal:URL 深校验不做)。

## Parallel/依赖状态

T25A(健康度 UI 迁移)前置已就绪;与 T28/T26/T27 文件域互斥。
