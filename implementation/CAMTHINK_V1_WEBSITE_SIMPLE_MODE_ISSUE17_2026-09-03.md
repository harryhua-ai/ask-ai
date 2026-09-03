# Issue #17 — Website Source Automatic Discovery(Website Simple Mode)实现报告

- **Executor**: Executor #2(PARALLEL,与 Issue #16 Executor 同基线各自分支)
- **日期**: 2026-09-03
- **STATUS**: **CANDIDATE_READY**(待 Planner FINAL REVIEW)
- **BASELINE**: ce52af421cd201fa64daf01c3f0e6fd32ac48a70(S0 Source Center 集成基线,与派发单一致)
- **FINAL_COMMIT**: 880282a(已推 origin)
- **BRANCH**: `worktree-exec/issue17-website-discovery-20260903`
- **WORKTREE**: `.worktrees/issue17-website-discovery`
- **REPORT_PATH**: `docs/implementation/CAMTHINK_V1_WEBSITE_SIMPLE_MODE_ISSUE17_2026-09-03.md`
- **PRODUCTION_MUTATIONS**: **NONE**(生产零触碰;无迁移、无 config/数据变更、无部署)

---

## 1. 交付范围(对齐 Issue #17 冻结契约)

Website 数据源从「手工填 crawler 工程参数」升级为:

```
网站地址 → 「检测站点内容」→ sitemap 自动发现(PD-3 冻结顺序)
        → Preview / Recommendation(纳入/排除/待确认 + 逐类理由)
        → 管理员确认(高级选项可微调)→ 既有 保存/同步 通道
```

主表单只保留:网站地址(required)、产品线、同步间隔、启用状态。
Sitemap 地址 / 排除路径 / 抓取间隔 全部下沉「高级选项」,普通管理员默认零接触。

## 2. DISCOVERY_FLOW(冻结顺序逐条实现)

发现组合由 S0 冻结的 `discover_sitemap_entries` 承担,本任务接线并修正:

1. **robots.txt `Sitemap:` 指令** — 同域声明全取;他域声明显式跳过(`cross_domain_skipped`,有 warning,不静默)。
2. **显式 `sitemap_url`** — Advanced override;给出时直接使用,不请求 robots(`discovery_mode=explicit`)。
3. **通用回退** — `/sitemap_index.xml` → `/sitemap.xml`(非 Yoast 站点可用);根候选「成功即停」语义保持。
4. **sitemap index 递归全部子表** — 无任何命名过滤;外域子表丢弃。
5. **Preview + Recommendation** — 逐 URL `FileAdmission`(复用 Technical Safety / Knowledge Role 词表)→ `build_discovery_result` 统一 envelope → `DiscoveryResultOut`(候选带 `reason_text` 冻结文案)。
6. **zero-discovery 显式** — 200 + 零候选 + 冻结告警「未发现任何 sitemap:请核对站点地址,或在高级选项手填 sitemap 地址」+ UI 红色显式面板;**不伪装成功**(连接器同步路径同样:零 URL + 失败证据 → `RuntimeError`,证据进消息)。

发现方式诚实记账(`entry_source`,新增 additive 字段):`explicit | robots | generic | none`——robots 声明但解析失败的候选不冒充来源。

## 3. DOMAIN_BOUNDARY(同源边界)

- `canonical_url` 同域判定 + index 子表同域过滤:跨域 URL 一律不得进入候选(实测:协议相对外域、他域子表均被丢弃);
- robots 声明的他域 sitemap 从未被抓取(测试断言 hits 不含外域);
- 预览端点无任何「跟随外域」路径;无界 crawler 不存在(max_sitemaps=25 / max_entries 上限,超限出截断 warning)。

## 4. ZERO_DISCOVERY_BEHAVIOR

| 层 | 行为 |
|---|---|
| 预览 API | 200 + `totals.files=0` + `warnings` 冻结文案 + `capability_notes`;绝不 500/伪装 |
| Admin UI | 红色面板「未发现任何可采集页面(本次不建立有效采集范围)」+ 逐条 warning + 下一步建议(核对地址 / 高级选项手填) |
| 连接器同步 | 零 URL 且有失败证据 → `RuntimeError("sitemap 自动发现失败(零 URL,证据: …)")` 同步显式失败;urlset 合法为空 → 空集照常完成(与旧语义一致) |

## 5. 实现清单(8 文件,+1092/−91)

| 文件 | 变更 |
|---|---|
| `backend/services/website_discovery.py` | `build_website_preview`(纯函数,fetch 注入):发现→逐 URL 分类→统一 envelope;`BINARY_ASSET_SUFFIXES` 技术排除(pdf/zip/…→ `binary_content`);`url_group_key` 首层路径分组;`recommended_config` 编译(见 §6);能力边界 4 条冻结文案 |
| `backend/services/website_discovery.py`(原语修正 ①) | 回退层 stop-on-entries 只作用于**根候选**;已解析 index 的**子表**不再被静默抛弃(原实现中「index 经通用回退解析 + 后续根候选出条目」会丢弃全部子表——恰好打在本任务验收「index 展开 × 通用回退」交集上) |
| `backend/services/website_discovery.py`(原语修正 ②) | 合法空 urlset 不再误记 `not_sitemap`(证据准确性;`_URLSET_ROOT_RE` 根标签识别,零 entries 无错误) |
| `backend/connectors/web_crawl.py` | **Yoast 三子表正则退役**(S0 冻结方向),`_sitemap_entries` 统一走 `discover_sitemap_entries`(惰性导入防解析原语互相依赖成环);`sitemap_url` 缺省=None=自动发现(不再硬钉 `{base}/sitemap_index.xml`),显式=override;`_discovery_fetch` 每次抓取后限速(`crawl_delay_ms` 语义保持) |
| `backend/api/admin/data_sources.py` | `POST /data-sources/preview-website`(EditorDep):URL 校验 400/422;**抓取走 `run_in_threadpool`**(09-02 生产 504 事故回归防线:事件循环内零网络等待);UA 与 connector 同身份 |
| `admin/src/hooks/useDataSources.ts` | `fetchWebsiteDiscovery` + 三个 wire 类型 |
| `admin/src/pages/DataSources.tsx` | Simple Mode UI(见 §7);`buildConfig` 注释更新(sitemap 缺省=自动发现) |
| `tests/…`(3 文件) | 新增/更新见 §9 |

## 6. 推荐策略与 Technical Safety / Knowledge Filtering

- 单候选 = 既有 `FileAdmission`(阶段1 冻结结构),分类复用 `classify_url` 与 `RECOMMENDED_INCLUDE/EXCLUDE_ROLES` 冻结映射,**不建第二套判定**;
- 低价值路径(login/search/cart/tag/category/… )→ exclude;产品/文档/API/FAQ → include;未知路径 → **review**(宁可多看,不静默纳入);
- 二进制/下载资产 → `technical_safe=False`(`binary_content`,「二进制内容,不可作为文本知识」);
- **预览=同步视野对齐**:`URL_EXCLUDE_PATTERNS` 补 `/store/`(C8 商城分离契约),`recommended_config.exclude_patterns` = 连接器默认 ∪ 预览排除(22 项),杜绝「预览说排除、同步却抓入」;
- `recommended_config` 只含既有 web_crawl config 词表(`base_url` + `exclude_patterns`),PD-2 不建第二套 sync semantics;**sitemap 地址不钉死**——缺省自动发现,站点迁移 sitemap 下轮自动跟随。

## 7. Admin UI(Simple Mode)

- 网站地址输入 + 「检测站点内容」按钮;
- 成功面板:发现方式(`已自动检测 Sitemap(robots.txt 声明)` 等)+ `发现 N 页 · 建议纳入 N · 自动排除 N · 待确认 N` + 解析到的 sitemap 列表 + 告警 + 按目录分组明细(前 10 组,组=推荐结论+页数+样本 URL)+ 4 条能力边界说明;
- **零发现红色显式面板**(「本次不建立有效采集范围」)+ 逐条 warning + 建议;
- 推荐排除清单自动回填高级选项(仅当该字段为空;已有自定义清单不覆盖,明示「未覆盖」);
- Sitemap 地址 / 排除路径 / 抓取间隔全部下沉折叠「高级选项」;确认 = 既有「创建/保存」按钮,写入既有 config 词表,同步通道零新语义。

## 8. TESTS / BUILD / REGRESSIONS

- **后端全量**: `1233 passed / 6 skipped / 0 failed`(隔离库 `ask_ai_test`,`HF_HUB_OFFLINE=1`,35s;基线 ce52af4 1213 → +21 新测,零失败);
- 新增测试:端点 6(happy/零发现显式/显式 override/非法 URL/未登录 401/跨域原因)、preview 组装 10(计数/冻结文案/资产排除/推荐配置∪清单/零发现/回退模式/跨域/分组/分组键/显式模式)、连接器 5(robots 指令/通用回退/显式 override/零发现响亮失败/合法空集)+ Yoast 语义测试按 S0 冻结方向重写(全子表,无命名过滤);
- **admin build**: `tsc -b && vite build` PASS;**admin vitest**: 36 files / **190 passed**(零前端回归);
- **offline load verify**: 全量测试在 `HF_HUB_OFFLINE=1` 下绿(模型 cache 物理复制生效,零下载);
- `git diff --check` PASS;black/isort 已过增量文件。

## 9. 真实站点只读冒烟(www.camthink.ai,只 GET 公开资源,零生产触碰)

```
discovery_mode: robots
robots_declared: ['https://www.camthink.ai/sitemap_index.xml']
resolved: sitemap_index.xml → post/page/product-sitemap.xml(三子表全展开)
totals: 128 页   include=18  exclude=44  review=66
warnings: []   cross_domain_skipped: []
recommended_config: {base_url, exclude_patterns×22}
```

## 10. KNOWN_LIMITATIONS(诚实边界,非缺陷)

1. **V1 无 JS rendering**:SPA/需要渲染的页面无法发现(能力边界已随结果呈现);
2. **预览仅 sitemap 视野**:同步阶段连接器还会做同域受控 BFS 扩展(有 `max_pages` 上限),预览数字 ≤ 实际同步覆盖——已作为第 3 条能力边界明示;
3. **review 档较大**:未知路径(如 `/blog/*`)保守给「待确认」,管理员按站点角色确认(契约原文允许);
4. **分组 UI 前 10 组**:其余组同规则处理并有明示;逐候选完整理由在 API 响应中(UI V1 未做逐 URL 长表);
5. **Yoast 过滤退役的语义变化**:既有源的同步范围从「post/page/product 三子表」扩为「index 全部同域子表」——这是 S0 冻结方向(去 Yoast 锁定),非回归;camthink 实测 index 本就只有这三张子表,生产行为不变;
6. **`/16 报告` 的 admin 测试数 203 vs 本报告 190**:两分支各自增量不同,本分支基线自洽零失败。

## 11. 并行协同备注

- 与 Issue #16(Executor #1,bfb5547)同基线 ce52af4 平行执行;本分支只动 web 侧文件,与 #16 的 `source_center_schemas.py`(零改动,纯 import 消费)无冲突面;
- S0 原语两处修正(子表抛弃 / 空 urlset 证据)是 additive 行为修正,既有 S0 测试全绿背书,#16 分支如已合入也不受影响(修正在共享模块,合并时后到者 rebase 即可)。

---

## Deliverable 摘要(与派发单字段一一对应)

```
STATUS: CANDIDATE_READY(待 Planner FINAL REVIEW)
BASELINE: ce52af421cd201fa64daf01c3f0e6fd32ac48a70
FINAL_COMMIT: 880282a
BRANCH: worktree-exec/issue17-website-discovery-20260903(已推 origin)
WORKTREE: .worktrees/issue17-website-discovery
DISCOVERY_FLOW: URL → robots Sitemap 指令 → 显式 sitemap_url → 通用回退
  → index 全子表展开 → FileAdmission 分类推荐 → DiscoveryResultOut 预览
  → 管理员确认 → 既有 web_crawl config 词表保存/同步
DOMAIN_BOUNDARY: canonical_url 同域 + index 子表同域过滤 + robots 外域显式跳过
  + max_sitemaps/max_entries 有界;跨域 URL 永不入候选,原因进 warnings
ZERO_DISCOVERY_BEHAVIOR: 预览=200+零候选+冻结告警+UI 红色显式面板;
  连接器=零 URL+失败证据 RuntimeError(不伪装成功)
TESTS: 后端 1233/6/0(隔离库+离线,+21 新测);admin vitest 190 passed
BUILD: admin tsc+vite PASS;git diff --check PASS
REGRESSIONS: 零(既有测试仅 Yoast 语义 1 例按 S0 冻结方向重写,夹具补齐子表)
KNOWN_LIMITATIONS: §10 六项(均为诚实边界)
REPORT_PATH: docs/implementation/CAMTHINK_V1_WEBSITE_SIMPLE_MODE_ISSUE17_2026-09-03.md
PRODUCTION_MUTATIONS: NONE
```
