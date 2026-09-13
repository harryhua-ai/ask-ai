# v1.6.3 Design Acceptance 终局 AFTER 证据集 — candidate 2f0bc06

- 捕获日期:2026-09-13
- 候选:`2f0bc064c2d54c783b667609dc4c7eeb921cd6ce`(remediation/v163-design-20260913)
- 捕获方式:Playwright(Chromium),真实登录(admin@camthink.ai),冻结视口 1536×1024 @1x;`07-admin-fullpage-chrome.png` 为 fullPage 截图,`07b-floating-fab.png` 为视口右下角 480×360 裁剪特写。
- 本地库含审计 fixture(6 数据源 / 1,204 千分位知识数量 / 98.7% 同步可靠性 / gap 原因×状态矩阵 / 第 2 页)。
- 每张截图的 DOM 断言记录见本地证据目录 `logs/dom-assertions.log`(不随分支提交)。

## 参考图说明

- `docs/product/design/admin-knowledge-ops/references/data-source-operations-original.png`
- `docs/product/design/admin-knowledge-ops/references/technical-insights-answer-gaps-original.png`

两张参考图原件在 **docs branch**(本 remediation 分支不含这两个文件);本地核对用副本位于 `/tmp/v163-refs/` 与 `/Users/harryhua/Documents/GitHub/ask-ai-acceptance/v163-design-audit-20260913/refs-crops/`(14 张裁剪:P1~P7 对应数据源运营图,B2 对应技术洞察图)。

## reference ↔ candidate 映射清单

| 截图 | 参考图区域(repo 路径 + 面板) | 候选路由 / 状态 | 备注 |
|---|---|---|---|
| `01-data-sources-list.png` | data-source-operations-original.png 面板1:数据源列表(筛选行 + 表格列 名称/类型/状态/知识数量/需处理/最后同步/⋯操作) | `/admin/data-sources` 完整列表态(fixture 六源,含徽章/待分类/需处理列) | 运行时数据不同(fixture 驱动);行高见 Role A 待裁项 1;右下 FAB 见 Role A 待裁项 2 |
| `02-data-source-detail.png` | data-source-operations-original.png 面板2:数据源详情工作面顶部(身份区 / 红色 attention banner / 知识内容工作区) | `/admin/data-sources/store-woo` 详情顶部态 | 身份区(WooCommerce · store-woo)、banner「有 3 项知识需要处理」、needs-attention 徽章行(当前在服 5 / 需要关注 3 / 已退役 0)可见 |
| `03-expanded-document-diagnosis.png` | data-source-operations-original.png 面板3:需处理文档行行下原地展开的诊断/真相态 | 同详情页「需要关注」bucket 内 Deprecated API 行展开态 | 行头 chevron(`[data-testid="doc-row-toggle"]`)触发展开;展开区含 问题/源内容状态/当前服务/URL/当前有效版本/生成真相 |
| `04-sync-activity.png` | data-source-operations-original.png 面板4:同步状态(四行)+ 最近活动时间线 | 同详情页「同步状态与活动」区(`#sync-activity`)滚动到位 | 结构对应关系与可见差异点见 Role A 待裁项 3 |
| `05-answer-gaps-queue.png` | technical-insights-answer-gaps-original.png 左侧队列:筛选行 + 多行队列 + 分页控件 | `/admin/analytics` 回答缺口 Tab 队列态 | 运行时数据不同(fixture 驱动);分页「‹ 1 2 ›」+「10 条/页」+「已选择 0 项」可见 |
| `06-gap-selected-diagnosis.png` | technical-insights-answer-gaps-original.png 右侧诊断侧板(概览 Tab) | 同 Tab 选中第一行(NE101 是否支持 PoE)后的侧板完整态 | 侧板五 Tab(概览/典型问题/相关对话/诊断详情/历史记录),概览含 问题描述/诊断结论/典型问题示例/推荐操作 |
| `07-admin-fullpage-chrome.png` | technical-insights-answer-gaps-original.png / data-source-operations-original.png 共享 chrome:顶栏身份区、侧栏、页头 | `/admin/data-sources` fullPage 截图 | 应用为内部滚动容器,文档高度=视口;顶栏/侧栏/页头/右下 FAB 均在画面内且未裁切;FAB 见 Role A 待裁项 2 |
| `07b-floating-fab.png` | 参考图中不存在该元素 | `/admin/data-sources` 视口右下角 480×360 裁剪特写 | LoginChat 浮动 FAB 特写,见 Role A 待裁项 2 |

## Role A 待裁三项(原样保留,不作结论)

1. **行高**:候选表格行高 = 渲染 DOM 实测(Playwright `boundingBox()`:数据源列表表格行 41.00px;回答缺口队列为双行内容行,实测 75.00px,出处 `logs/dom-assertions.log` MEASURE 记录);参考行高 ≈ 36–40px(参考图像素目测)。两侧数值出处不同(候选=渲染 DOM 实测,参考=参考图像素目测),差异留待 Role A 裁决。
2. **LoginChat 浮动 FAB**:候选右下角存在 "ai" 圆形浮动按钮(`.ask-ai-fab`,DOM 实测 bounding box x=1460, y=948, 52×52,视口 1536×1024 内未裁切),该元素在参考图中**不存在**。此处仅如实记录其存在与位置,分类留待 Role A。
3. **同步/活动区结构呈现**:候选实现 = 同步状态四项(最近成功/最近结果/同步可靠性/同步周期)+「最近活动」时间线(异常条目优先置顶,每条目带「技术证据」展开器);参考面板4 = 同步状态四行 + 时间线。可见差异点:候选含「同步可靠性」百分比项(98.7%),时间线条目附「技术证据」展开器与触发方式标注。此处仅记录结构对应关系与可见差异点,分类留待 Role A。

## 其他备注(中性)

- 各截图中的具体数值(提问数/影响回答/时间戳/知识数量等)为本地 fixture 运行时数据,与参考图中的示例数据不同;原因与状态徽章种类以本地 fixture 矩阵为准(知识缺失/服务知识不完整/低相关/拒答/未分类 × 需要处理/已解决)。
- `05` 在冻结视口下因候选队列行高较高,截图时将滚动容器下移使分页控件入画;筛选行仍在画面内(`retake05.mjs` 中 MEASURE 记录:滚动后 toolbar top=128、分页 bottom=1012,均在 1024 视口内)。
