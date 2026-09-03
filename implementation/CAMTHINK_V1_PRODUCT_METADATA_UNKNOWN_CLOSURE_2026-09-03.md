# CamThink V1 — Issue #5 Product Metadata Unknown Closure 报告

- **日期**: 2026-09-03
- **模式**: PRODUCTION READ-ONLY + LOCAL ANALYSIS ONLY
- **权威基线**: 已验收 #5 候选 `7123f73`(taxonomy/resolver/迁移工具原版)
- **规则增补分支**: `worktree-exec/issue5-unknown-closure-20260903`(自 7123f73 派生)
- **FINAL_COMMIT**: `bc16eeb`
- **状态**: **CANDIDATE_READY(待 Planner FINAL REVIEW)**
- **PRODUCTION_MUTATIONS**: **NONE**(只读 iterator + GraphQL Get,零写入/零配置/零 sync/零部署)

---

## 1. 目标与结论

关闭 #5 Production Dry Run 剩余 2,560 unknown chunks:在生产只读取证之上,
逐组给出确定性归账,必要时做**确定性 taxonomy 规则增补**(仅隔离分支),
重算全量 dry-run 形成可授权的完整分类结果。

**结论**:
- 2,560 unknown **全部归账,零沉默剩余,零猜测归属**;
- 2 条确定性规则增补(C 类)→ **1,308 chunks 归位**(翻译版产品文档 1,307 + AI ToolStack 官方页 1);
- 剩余 **1,252 unknown 全部为 B 类契约性 unknown**(生成物/站点自身内容/官网非产品页——它们本就不该获得产品归属);
- **必需的产品决策:0 项**;可选增强项 4 组已列出(见 §7)。

## 2. 取证方法(生产只读,零写入)

1. **导出**:`ssh tesla-t4` → 生产 backend 容器(tesla-t4-backend-1, sha-c83d214)stdin 注入只读脚本,
   `collection.iterator(include_vector=False, return_properties=[source_id, product, url, title])`
   客户端聚合为 (prefix, source_id, product, url, title) distinct + chunk 计数,经 SSH stdout 流回本地
   (生产容器零文件落盘)。
2. **校准**:导出 = **208,009 chunks / 11,940 doc 组**,与既有只读验收报告 §7 完全同口径;
   用 7123f73 原版 taxonomy+derive_product 复算全量 dry-run →
   **scanned=208,009 / changed=67,251 / unchanged=140,758 / unknown=2,560,逐项严格吻合**。
3. **分类**:对 unknown 全量(374 doc 组)按 source_id 路径/URL 族分组 → 计数 →
   生产只读取样内容证据(GraphQL Get 精确 source_id + 客户端二次精确过滤)→ ABCD 判定。
4. **完备性验证**:程序化断言「unknown 中存在既有规则本可命中的文档」= **0**(规则未漏,标签无错配)。

## 3. unknown 种群分组与证据(规则增补前,2,560 chunks / 374 docs)

### wiki-documents-local(2,295 chunks / 276 docs)
| 组 | chunks/docs | 内容证据 | 判定 |
|---|---|---|---|
| i18n 镜像树**翻译版产品文档** `i18n/en/docusaurus-plugin-content-docs/current/<系列>/…` | 1,307 / ~247 | 与主树 `docs/<系列>` 同构的英文翻译镜像(0-neomind/1-ng4500/2-ne101/3-hardware/4-ai/5-ne301/6-ne503/7-release-notes/8-ne302) | **C**(系列 token 同主树,确定性同产品) |
| `.image-upload/**`(scripts/test/lib/docs) | 116 / 33 | 实证 = wiki 站内部图片上传工具(含开发者本机路径) | **B**(站点工具,非产品事实) |
| `CHANGELOG.md`+`CHANGELOG_CN.md` | 34 / 2 | 实证 = **站务编辑日志**(混 NE301 文档/首页 UI/国际化条目),非产品发布说明 | **B**(内容抽样防"文件名误判 release-notes") |
| `package-lock.json` | 783 / 1 | 实证 = npm 依赖锁(algolia 等) | **B**(生成物) |
| `src/**`+`docusaurus.config.js`+`sidebars.js`+`package.json`+`README.md` | 29+2+1 / 15 | wiki 站自身源码/配置 | **B** |
| `i18n` 站点 chrome(`code.json`/`current.json`/`navbar.json`/`footer.json`/镜像 `index.md`/`sidebars.js`) | 20 / 8 | 实证 = Docusaurus UI 翻译串("This page crashed" 等) | **B** |
| `docs/index.md` | 6 / 1 | 跨产品文档首页 | **B**(归属任一产品=污染;契约性 unknown) |

### website-camthink(265 chunks / 98 docs)
| 组 | chunks/docs | 判定 |
|---|---|---|
| `/tools/ai-tool-stack/`(AI ToolStack 官方页) | 1 / 1 | **C**(平台身份显式:URL 路径 + taxonomy 别名;与冻结 `/product/neomind→neomind` 同类) |
| `blog/*` | 196 / ~65 | **B**(#5 冻结立场:营销/教育内容非产品事实来源;且多篇跨产品如"NE101 & NE301 Guide",单一归属必违污染边界) |
| `developer-center/models/*`(AI Model Zoo) | 33 / 32 | **B 留守 + PD-可选**(设备无关模型目录,可作共享桶增强) |
| `news/*`、`campaign/*`、`solutions/*`、`company/*`、policy/商务页、home、`/product`、`tools`(battery-calculator 等)、`feed`/`comments/feed` | 32 / ~32 | **B**(公司/营销/政策/联合投稿杂质) |

**判定汇总**:A 类(既有规则即可)= **0**(完备性已证);C 类 = 2 组 1,308 chunks;B 类 = 1,252 chunks;D 类(必需 PD)= **0**。

## 4. 规则增补(C 类;隔离分支 bc16eeb,纯追加零修改)

1. **website ai-tool-stack**:`{url_any: ["/tools/ai-tool-stack"], product: aitoolstack}`
   —— 负例锁定:`/tools/battery-calculator`、`/tools` 保持 unknown。
2. **wiki i18n 镜像树**:9 条既有规则的 `path_any` **各追加**一个镜像 token
   `i18n/en/docusaurus-plugin-content-docs/current/<系列>`(与主树 token 并列,**既有冻结 token 一字不动**)。
   —— 负例锁定:`code.json`/`navbar.json`/`current.json`/镜像 `index.md`/`sidebars.js` 保持 unknown。
   —— 归位分布(程序化实证):neomind 561、ne301 194、ne503 168、ng4500 137、ne101 95、hardware-common 74、ai-common 41、ne302 22、release-notes 15(镜像树合计 1,307);另 aitoolstack 1。**合计 1,308。**

设计红线自查:非兄弟页推断(路径 token = 主树同款系列身份);不放宽 Technical Safety;
不引入产品 hardcode(纯 YAML 数据);不加新 slug/新桶。

## 5. 最终迁移预览(bc16eeb taxonomy × 生产只读事实,全量精确复算)

```
scanned=208,009 | changed=67,251 | unchanged=140,758 | unknown=1,252
```
| 源 | scanned | changed | unchanged | unknown |
|---|---|---|---|---|
| wiki-documents-local | 3,891 | 3,891 | 0 | **988** |
| website-camthink | 366 | 366 | 0 | **264** |
| neoruntime-apps-1eea74dd | 60,675 | 60,675 | 0 | 0 |
| ne301-local | 67,413 | 0 | 67,413 | 0 |
| lowpower-camera-local | 36,841 | 0 | 36,841 | 0 |
| ne503-apic-69d3594b | 20,198 | 0 | 20,198 | 0 |
| neomind-local/extensions/devicetypes/dashboard | 15,675 | 0 | 15,675 | 0 |
| neoruntime-sdks-67cbac8f | 1,320 | 1,320 | 0 | 0 |
| aitoolstack-local | 955 | 955 | 0 | 0 |
| knowledge-support-cases | 481 | 0 | 481 | 0 |
| meta-hailo-os-local | 93 | 0 | 93 | 0 |
| woocommerce-mall | 101 | 44 | 57 | 0 |

说明:`changed` 总数与增补前一致(67,251)——因为原 2,560 unknown 本就计入 changed
(old label "wiki"/"website" ≠ unknown);增补的语义价值是其中 **1,308 chunks 从
不可归属的 unknown 升级为正确 canonical 产品/共享桶**,直接改善产品边界检索与 CIT-03 资格面。

## 6. 剩余 1,252 unknown 明细(全部 B 类,零沉默)

| 组 | chunks/docs | B 类理由(契约) |
|---|---|---|
| wiki package-lock.json | 783 / 1 | 生成物,非知识 |
| website blog | 196 / 65 | 非产品事实来源(#5 冻结);跨产品混排 |
| wiki .image-upload 工具 | 116 / 36 | 站点工具 |
| wiki CHANGELOG×2 | 34 / 2 | 站务编辑日志(内容实证) |
| website developer-center(models 等) | 33 / 32 | 设备无关模型目录 |
| wiki 站点源码/配置 | 29 / 14 | 站点自身 |
| wiki i18n chrome(UI 串/目录标签/镜像索引) | 20 / 8 | 站点 chrome |
| wiki docs/index.md | 6 / 1 | 跨产品索引页 |
| website news/campaign/solutions/company/policy/商务/feed 等 | 68 / ~50 | 公司/营销/政策/联合内容杂质 |

## 7. 可选产品决策(非必需;列出供拍板,当前全部合法留守 unknown)

| PD-可选 | 对象 | 若拍板"分类"的影响 |
|---|---|---|
| PD-A | website `developer-center/models/*`(33) | 新增/映射共享桶(如 ai-common)→ 成为产品问题背景证据;改变证据资格面 |
| PD-B | wiki CHANGELOG×2(34) | 映射 release-notes → 站务编辑日志进入发布说明证据面(内容含产品文档变更,亦含站点 UI 变更,**不建议**) |
| PD-C | 单产品命名 blog(如 NE301 Outdoor Guide) | 逐页归属需逐篇人工审(违"不因兄弟页推断"),默认不做 |
| PD-D | wiki docs/index.md + 镜像 index(6+5) | 无合适桶;保持 unknown 即契约意图 |

## 8. 测试与验证

| 门 | 结果 |
|---|---|
| taxonomy focused(test_product_taxonomy.py,含 3 个新测试类/10 断言组) | **59 passed** |
| #5 确定性 eval A–K + resolver/derivation/CIT-03/检索/迁移 dry-run focused | **60 passed**(eval 23 全绿) |
| 后端全量(隔离库 + HF_HUB_OFFLINE + 权重物理副本 offline 预验) | **1255 passed / 6 skipped / 0 failed**(7123f73 基线 1252 + 新增 3,严格吻合) |
| `git diff --check` | PASS |
| 改动面 | 仅 `config/product_taxonomy.yaml`(纯追加)+ 测试文件;**零业务代码变更** |

## 9. 边界声明

- 生产交互 = 两次只读取证(iterator 聚合导出、GraphQL Get 取样),无任何写动词;
  无 metadata apply、无 Weaviate 属性更新、无语料/向量变更、无源配置变更、
  无 sync 触发、无部署/重启/迁移、无生产文件/配置变更;
- 规则增补仅在隔离 worktree(7123f73 派生)实现+测试;
- 已验收候选分支 `worktree-exec/answer-correctness-20260903`(7123f73)零触碰。

## 10. 结构化结果

```
STATUS: CANDIDATE_READY(待 Planner FINAL REVIEW)
BASELINE: 7123f73(已验收 #5 候选;#5 Discovery/实现报告 + 生产只读验收报告 §7)
FINAL_COMMIT: bc16eeb(@origin/worktree-exec/issue5-unknown-closure-20260903)
UNKNOWN_TOTAL_BEFORE: 2,560(wiki 2,295 / website 265)
GROUPS: wiki 7 族 + website 9 族(§3 两表;374 doc 组全量入账)
DETERMINISTICALLY_CLASSIFIED: 1,308(i18n 镜像树 1,307 + ai-tool-stack 1)
LEGITIMATE_SHARED_OR_UNKNOWN: 1,252(B 类契约性 unknown,构成见 §6)
RULE_CHANGES: 2 条(website ai-tool-stack;wiki 9 规则追加 i18n 镜像 token;纯追加)
TRULY_AMBIGUOUS: 0(必需 PD 为零;4 组可选 PD 见 §7)
UNKNOWN_TOTAL_AFTER: 1,252(wiki 988 / website 264)
FINAL_MIGRATION_PREVIEW: scanned=208,009 changed=67,251 unchanged=140,758
  unknown=1,252(逐源表见 §5)
TESTS: taxonomy 59 绿(+3);eval A–K 绿;全量 1255/6/0;diff-check 绿
REGRESSIONS: 零(基线严格吻合;零业务代码变更)
PRODUCT_DECISIONS_REQUIRED: 0 必需(4 项可选:PD-A models 共享桶 / PD-B CHANGELOG
  不建议 / PD-C 单产品 blog 逐页审 / PD-D index 页保持)
REPORT_PATH: docs/implementation/CAMTHINK_V1_PRODUCT_METADATA_UNKNOWN_CLOSURE_2026-09-03.md
REPORT_COMMIT: 见 docs 仓 log(本文件)
PRODUCTION_MUTATIONS: NONE
```
