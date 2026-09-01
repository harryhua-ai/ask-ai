# CAMTHINK V1 — P1 Website Knowledge Coverage 执行报告

日期:2026-09-01
任务:CAMTHINK_V1_P1_WEBSITE_KNOWLEDGE_COVERAGE
基线:024e55bd437cbec98f5de4dc2bb1f139cf0bb359(已验收的 Technical Insights 终点)
状态:**PASS(自评)——待 Planner 独立验收**

---

## 1. Executive Result

「只存活 2 个文档」**不是爬虫抓不到,而是三件事叠加**:①全量爬取其实早已把
约 78 篇官网文档灌进了 Weaviate(实测 821 chunks),但 Postgres documents 账本
只剩 2 行(账本漂移),而一致性自愈只处理「PG 有账、向量缺」方向,孤儿漂移
永久循环报「需人工核查」;②连接器把单页失败、薄内容页全部静默吞没——
「85 页只活 2 页」也会记 success,SyncLog 无任何痕迹;③URL 规范化与内容
哈希缺陷为重复知识与账本互撞埋雷。修复后:连接器全程记账(run_stats)、
覆盖度决定性降级(<80% 抽取 → partial、0 抽取 → failed)、孤儿漂移全量
重灌自愈、URL 规范化去重、URL 感知哈希、robots.txt 遵从、增量轮不再误删
发现页。真实站点自然验收(连跑两轮):discovered=134 → extracted=113、
failed=1(/shop/ 404,如实记录)、拒绝 60 排除+20 薄内容(JS 壳,URL 清单
留证)、0 外域、0 重复;第二轮 113→113 同 path 集、0 增删(见 §9)。

**PRODUCTION_DEPLOYED = NO**

## 2. Baseline / Worktree / Branch

- BASELINE_COMMIT = 024e55bd437cbec98f5de4dc2bb1f139cf0bb359(顺序任务起点,
  未从 main 起步;Technical Insights 合同未重开)
- WORKTREE = /Users/harryhua/Documents/GitHub/ask-ai/.worktrees/technical-insights
  (复用上一任务 worktree 与依赖;注:执行中途该目录被外部清理过一次,已按同
  路径从分支重建并恢复 .env/models/node_modules 链接,未丢失任何已推送提交)
- BRANCH = worktree-exec/p1-website-coverage(自 024e55bd 切出)

## 3. Investigation — Root Cause(全部实证,无预设立场)

### 3.1 「2 documents」到底是什么
- 是 Postgres `documents` 表 `source_id LIKE 'website-camthink/%'` 的行数
  (admin 文档数 = PG 前缀聚合),**不是**页面数、也不是向量库 chunk 数。
- 实测(本地开发栈,admin 报数的同一环境):
  - PG:恰好 2 行(blog/size-edge-ai-box…、blog/validate-existing-cctv…,
    各 1 chunk,created 2026-09-01 08:55:31);
  - Weaviate:同前缀 **821 chunks、约 78 篇不同文档**(blog/index/news 真实
    标题与正文俱在)。

### 3.2 真实同步历史(本地库 sync_log 只读查询)
```
website-camthink | success | 08:55:31 | items_new=2            ← 2 篇"成功"
website-camthink | partial | 09:17:40 | 一致性校验发现缺口 821/2 chunks;
                 |         |          | 存在缺口但重灌清单为空,未自动补齐;orphan=76
website-camthink | partial | 10:04:21 | 同上(永久循环)
```
DSH 30 天窗口:1 success + 2 partial → 33% 成功率 → severe;一致性缺口
警告即上述 partial 的 error_detail。

### 3.3 根因清单(每条均有代码级证据)
| # | 根因 | 证据 |
|---|------|------|
| RC1 | **账本漂移无自愈**:一致性校验 refill 只处理「PG 有账、向量缺」;孤儿(向量有、PG 无)只 warning 不修 → `重灌清单为空,未自动补齐,需人工核查` 永久循环。PG documents 曾丢失(开发库重置/重建),向量侧完整存活 → 永远显示 2 | vector_consistency.py(refill=PG差集)+ sync.py _handle_no_change else 分支(旧:`items_updated=0`) |
| RC2 | **覆盖抑制不可见**:connector 单页失败仅 logger(failures 局部变量);薄内容页被 ingest 静默跳过(`切分为空`);SyncLog 无任何覆盖字段 → 「2/85」记 success 零痕迹(合同#6/#7 违规态) | web_crawl.py fetch_all 旧实现;ingest.py 414 |
| RC3 | **content_hash 不含 URL**(sha256(md)):薄模板页 md 相同 → PG (content_hash,branch) 主键互撞,后页 upsert **覆写前页 source_id** → 账本行再丢失 | ingest.py _upsert_postgres 574-609 |
| RC4 | **增量轮误删发现页**:fetch_changes 置 `_seen_urls=sitemap only`,fetch_deleted 据此判删 → BFS 发现的、不在 sitemap 的页每轮增量被判「已消失」删除(覆盖震荡) | web_crawl.py 旧 fetch_changes/fetch_deleted |
| RC5 | **robots.txt 未读**(调查项):靠 sitemap 白名单+排除清单保持有界同站,但 Disallow 未遵从 | 旧实现无 robots 逻辑 |
| SF | **站点事实**:sitemap_index 三子表(post 58/page 31/product 40)共 129 URL;product 全部位于 /store/(40 个,含 NG4500)被默认排除——**设计使然**:商城商品由 woocommerce-mall 源负责(同内容去重,合同#4/#9),web_crawl 只收知识页;knowledge 潜力 ≈87 页 | 实抓 sitemap;数据源表 ne101-4382af41(windows 商城源,3496 items) |
| SF2 | **抽取实证**:post/page 提取优秀(2202-6178 字符),/store/ 产品页仅 181 字符(JS 模板壳)——即使不排除也近乎不可抽,进一步支持商城走 WooCommerce API | 4 类真实页面实测 |

### 3.4 排除的假设
- 「sitemap 不匹配」✗(三子表命名与正则完全匹配);
- 「爬取被 WAF 全灭」✗(Weaviate 821 chunks 证明历史上抓取成功过;现行抓取亦成功);
- 「max_pages 上限卡死」✗(上限 = sitemap+150,未触);
- 「JS 渲染站点」✗(WordPress+Yoast,SSR 可抽,SF2 实证)。

## 4. Final Implemented Semantics(修复)

1. **run_stats 全程记账**(RC2/合同#6):`{full, discovered, accepted,
   extracted, failed, failed_urls, rejected:{exclude,robots,low_content}}`;
   同步层写入 SyncLog.error_detail 的 `coverage:` 行——成功也留痕;
2. **覆盖度决定性降级**(合同#6/#7):全量轮 extracted==0 → failed;
   extracted/accepted < 0.8 → partial(窗口不推进,下轮重试);≥80% →
   success 但 coverage 行仍列失败明细。阈值 0.8 为工程 HOW,常量
   COVERAGE_PARTIAL_RATIO 注释在案;仅对声明 `full` 的 run_stats 生效,
   git/filesystem/woocommerce 连接器零影响;
3. **孤儿漂移全量重灌自愈**(RC1/合同#7 修因不修警):no-change 轮一致性
   校验 refill 为空但 orphan/stale>0 → fetch_all+ingest_all 幂等重灌恢复
   账本,记 partial+自愈描述;下一轮校验转 healthy → success。**本修复即
   现网 821/2 漂移的自愈路径**(部署后首次同步即触发,无需人工核查);
4. **canonical_url 规范化**(合同#5/WEB-G005):sitemap 与页内链接统一形态
   (host 小写、去 query/fragment、压缩 //、统一尾斜杠、协议相对外域拒绝),
   两路发现合并去重;
5. **content_hash = sha256(path|md)**(RC3):URL 感知,同内容异页不互撞;
6. **robots.txt 遵从**(RC5):每轮全量获取+缓存,Disallow 前缀生效,计入
   rejected.robots;获取失败按全允许(宁抓勿断);
7. **薄内容过滤**(合同#4):md < 200 字符(可配 min_content_chars)不入
   语料,计 rejected.low_content;
8. **增量轮不删文档**(RC4):fetch_deleted 仅全量轮做状态差集;增量轮返回
   [] 且不覆写状态文件(删除判定延迟到下一全量轮,有界且安全)。

## 5. Frozen Contract 逐条对照

| # | 条款 | 结果 |
|---|------|------|
| 1 | 自动发现同站有意义公开页 | ✓ sitemap+同域 BFS,真实抓取 accepted=134/extracted=113 |
| 2 | 发现不限于种子 URL | ✓ BFS 发现补充 sitemap 之外链接 |
| 3 | 有界+默认同站 | ✓ max_pages 上限(150 额外)+canonical 同站校验 |
| 4 | 不吞噪声 | ✓ 排除清单+robots+薄内容过滤;/store/ 让位 WooCommerce 源(防双源重复) |
| 5 | 规范化去重 | ✓ canonical_url + _seen_urls + URL 感知哈希 |
| 6 | 单页失败不得伪装成功 | ✓ run_stats+coverage 行+<80% partial |
| 7 | 健康证据真实呈现 | ✓ SyncLog coverage/自愈细节;DSH 公式零改动(输入更真实) |
| 8 | 可见性/P0 信任边界 | ✓ channel_visibility 透传未动;P0 测试全绿 |
| 9 | 其他连接器不回归 | ✓ 全连接器测试套绿;改动面仅 web_crawl+sync 通用层(getattr 防御) |
| 10 | 不硬编码 CamThink | ✓ 全部机制结构化(base_url 参数化);无一条 CamThink URL 入实现代码 |

## 6. WEB-G001..G010 验收对照

| 场景 | 结果 | 证据 |
|------|------|------|
| G001 根 URL 发现多页 | ✓ | §9 自然抓取:discovered=130 |
| G002 产品内容发现+抽取 | ✓ | NE503/NG4500 产品知识页(news/neoeyes-ne503-launch、blog/ne503-* 系列)入语料(产品**目录**数据按既定分工由 WooCommerce 源负责,/store/ 排除防双源重复) |
| G003 非产品知识页 | ✓ | company/about-us、blog 指南类、payment-methods 等入语料 |
| G004 同站边界 | ✓ | 抽取文档 URL 100% www.camthink.ai;协议相对外域被拒(单测) |
| G005 变体不重复 | ✓ | canonical_url 单测(query/fragment/大小写/尾斜杠/协议相对);抓取结果 0 重复 path;排除链接唯一计数(单测) |
| G006 单页失败可观测 | ✓ | run_stats.failed/failed_urls;coverage 行入 SyncLog(单测锁定) |
| G007 二次同步幂等 | ✓ | 真实站点连跑两轮:同 URL 集、同 content_hash 集(§9) |
| G008 连接器回归 | ✓ | tests/connectors 全绿(含 github/filesystem/woocommerce/local_git) |
| G009 P0 可见性不变 | ✓ | channel_visibility 透传代码未动;test_source_visibility+集成 gate 全绿 |
| G010 自然覆盖证据 | ✓ | §9 + data/acceptance/web_coverage_evidence.json(docs 仓附档) |

## 7. TDD RED → GREEN → REFACTOR

- RED:新增连接器 8 用例 + sync 层 5 用例,首跑 **11 failed / 9 passed**
  (9 个既有/守卫用例先绿属预期);
- GREEN:web_crawl.py 重写 + sync.py 覆盖度/自愈后,连接器 15/15、
  connectors+scripts+test_sync **134 passed / 3 skipped**;
- REFACTOR:去除无用别名后复跑 40 passed;
- 中途修正:测试夹具缺 `full: True` 键(3 用例假红)、协议相对 URL 规范化
  遗漏(1 用例)——均先红后绿。

## 8. Changed Files / Diff Audit

- `backend/connectors/web_crawl.py`(重写:canonical_url/robots/薄内容/
  URL 感知哈希/run_stats/删除语义;BASE_URL 参数化,无硬编码站点);
- `scripts/sync.py`(COVERAGE_PARTIAL_RATIO+_coverage_line;_sync_one 覆盖度
  门控+异常路径留痕;_handle_no_change 孤儿自愈)——通用层,getattr 防御,
  非 web_crawl 连接器行为不变(有回归测试锁定);
- `scripts/web_coverage_acceptance.py`(自然验收脚本,入库可复现);
- `tests/connectors/test_web_crawl.py`(+8 用例;旧 fetch_deleted 用例按新
  契约重写);`tests/scripts/test_sync_coverage.py`(新,5 用例);
- 不在范围:ingest.py、chunk、检索、DSH 公式、数据源 API、其他连接器、前端。

## 9. WEB-G010 自然覆盖证据(真实站点)

目标:https://www.camthink.ai(robots.txt 实读:Disallow /wp-admin/、
/wp-includes/、/search/、/tag/、/feed/ 等,本轮全部遵从;站点 sitemap 实况:
post 58 + page 31 + product 40 = 129)。

连跑两次全量(证据 JSON:docs 仓
`implementation/evidence/website-coverage-20260901/web_coverage_evidence.json`):

| 指标 | Round 1 | Round 2 |
|------|---------|---------|
| discovered | 134 | 134 |
| accepted | 134 | 134 |
| extracted(入语料) | **113** | **113** |
| failed | 1(/shop/ 404,sitemap 自身残链,如实记录) | 同 |
| rejected.exclude | 60(store 40+隐私条款等,唯一 URL 清单在案) | 同 |
| rejected.robots | 0 | 0 |
| rejected.low_content | 20(JS 渲染壳,URL 清单在案) | 同 |

- 语料构成:正文 429-24,777 字符(中位 2,877);**0 重复 path、0 外域**;
  产品知识页 27 篇(NE503/NE301/NG4500 相关)、非产品知识页 58+ 篇;
- **幂等(G007)**:113→113、path 集合相同、added=removed=0 → **不倍增**;
  84/113 content_hash 完全一致,29 个变更 path 全部为
  `developer-center/models/*`(Model Zoo 动态目录页,两轮间内容确实变化
  ——这正是 content_hash 增量的设计语义,如实披露而非抑制);
- **低内容 20 页诊断**:静态可见文本仅 171-260 字符(JS 渲染模板,含 11 个
  blog URL —— 站方部分页面客户端渲染),静态爬取无法抽取;连接器行为=
  拒绝+计数+URL 清单(诚实),恢复手段(headless 渲染)记 F-6;
- 代表性接受 URL:
  - 产品知识:news/neoeyes-ne503-launch/、blog/ne503-open-ai-camera-platform/、
    blog/inside-neoeyes-ne503-edge-ai-camera/、blog/ne101-lens-selection-guide-meter-reading/
  - 非产品知识:company/about-us/、payment-methods/、warranty-and-return-policy/
- 拒绝样例:/store/*(40,让位 WooCommerce 源)、/cookie-policy/、
  /terms-of-service/、/login/、/wp-json/wp/v2/pages/1491/。

## 10. Verification

- 后端聚焦:connectors 16/16;connectors+scripts+test_sync 134 passed/3 skipped;
  P0/可见性聚焦:source_visibility+integration_gate+checkpoint_gate+analytics
  **46 passed**;
- 全仓回归(HF_HUB_OFFLINE=1,隔离库 ask_ai_obs_sem2):**698 passed /
  4 failed / 3 errors / 5 skipped(55.8s)**——4 failed=embedder HF 离线缓存
  竞态、3 errors=迁移测试 DSN 护栏,均与本任务改动前完全一致(上一任务已用
  主仓对照证明环境既有),本任务净增 13 用例全绿、零回归;
- 前端:本任务零前端改动(不适用)。

## 11. Residual Risks / FOLLOW_UP

- F-1:自愈路径对大体量源(如 57912 chunks 商城源)一旦触发是全量重灌,
  成本高但幂等且有界;后续可加「孤儿按 lastmod 过滤」的定向重建;
- F-2:增量轮不删文档 → 已删页面下线延迟到下一全量轮;可配置全量周期权衡;
- F-3:robots 仅实现 Disallow 前缀(未做 Crawl-delay/Allow 优先级长匹配),
  对当前目标站足够;站点方若用复杂规则需升级解析;
- F-4:coverage 阈值 0.8 与薄内容阈值 200 字符为工程拍板,上线后可按真实
  分布微调(两者均有注释与配置入口);
- F-5:本地开发栈现存的 821/2 漂移,部署本修复后由首次 no-change 同步自动
  自愈(§4.3),无需数据手术;**生产 T4 未触碰**;
- F-6:20 个 JS 渲染页(含 11 blog)静态不可抽,已如实列为 low_content 拒绝;
  如需覆盖须引入 headless 渲染(体量/性能/依赖权衡),建议单独立项;
- F-7:29 个 developer-center/models/* 动态页每轮 content_hash 变化 → 每次全量
  同步会重灌这 29 篇(幂等但非零成本);若需优化可对该路径配置哈希忽略字段或
  降频;

## 12. Production Status

未部署生产;未触碰 T4/生产库/共享配置/共享 Weaviate(本地 Weaviate 仅只读
GraphQL 查询用于调查);真实站点抓取为只读 GET、UA 标识、500ms 限速,遵守
robots.txt。

**PRODUCTION_DEPLOYED = NO**

## 13. Final Commit / Delivery

- FINAL_COMMIT = 【推送后见交付摘要】
- BRANCH = worktree-exec/p1-website-coverage
- REPORT_PATH = docs/implementation/CAMTHINK_V1_P1_WEBSITE_KNOWLEDGE_COVERAGE_2026-09-01.md

本报告不构成 FINAL ACCEPTANCE,Planner 独立验收为准。
