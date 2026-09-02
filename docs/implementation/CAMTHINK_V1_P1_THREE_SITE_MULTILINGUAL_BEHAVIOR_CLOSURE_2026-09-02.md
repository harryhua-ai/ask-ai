# CAMTHINK V1 — P1 Three-Site Multilingual Behavior Closure 执行报告

- 日期:2026-09-02
- 执行:Engineering Executor
- 分支:`worktree-exec/multilingual-closure`
- 工作树:`/Users/harryhua/Documents/GitHub/ask-ai/.worktrees/multilingual-closure`
- 仓库:`harryhua-ai/ask-ai`
- 执行环境修正:已确认本窗口为 ASK-AI 主仓(remote = harryhua-ai/ask-ai),基线 `d9065df` 经 `git cat-file -t` 验证存在,未触碰任何 trader/hermes 路径

---

## 1. STATUS

**STATUS = PASS(Executor 验证通过;不声明 Product FINAL ACCEPTANCE,等 Planner FINAL REVIEW)**

冻结的多语言行为闭环已完整实现并实证:语言解析链(宿主显式 → `<html lang>` → 站点默认 → 浏览器 → 省略)端到端落地,UI_LANGUAGE 与 ANSWER_LANGUAGE 分离,en/zh 归一化,三站双语体验文案,site_id 与语言解耦,引用完整性/Headless 兼容零回归。ML-G001~G014 全过,后端 943+5 全绿。

## 2. 基线与提交

| 项 | 值 |
| --- | --- |
| BASELINE_COMMIT | `d9065df315e70c9c4a7a5233238f8f20e25d2832`(已验收产品变更集成门 FINAL_COMMIT) |
| FINAL_COMMIT | `f32b3f4e3a95af0b5965b35f8971019158fdfd05`(实现+门用例+契约文档更新) |
| REPORT_COMMIT | 见文末交付字段(force-add 入主仓) |
| 提交策略 | 单实现提交(线性,基于精确冻结基线) |

## 3. 冻结语义 → 实现映射

### 3.1 ANSWER_LANGUAGE(服务端,答案语言)

解析(`backend/utils/language.py::resolve_answer_language`,单点权威):

```
1. 请求 language 提示存在(经 normalize_language 归一化)
   → 提示 = 默认答案语境(G-L1 闭环:此前请求提示被管线完全忽略);
     但提问文本确定性检出 CJK(zh/ja/ko,显式用户语言表达)且与提示不同族
     → 显式用户语言覆盖宿主默认;
2. 提示缺失/无效(fail-open 归 None)
   → 文本检测,行为与基线逐字一致(detect_language 原值,含 zh-cn)。
```

接线:`AskRequest.language` 校验器归一化(zh-CN/zh_TW/zh-Hans→zh;en-US/en-GB→en;其他 BCP-47 取主子标签;非法 → None)→ routes 将 `req.language or site.language`(显式站点未带提示时回落站点默认语言)作为 `language_hint` 传入 `answer()/stream_answer()` → 管线解析后驱动生成指令(「用 {language} 回答」)、off-topic 边界话术、`RAGAnswer.language`/complete 事件、trace 新增 `stages.language = {hint, detected, resolved}`(可审查)。

诚实边界:拉丁文本间的区分(英语 vs 西语等)不在 CJK 确定性检测能力内,视为「未定」交提示裁决;无提示时按基线回落 en(与 G-L1 登记的现状一致,未新增 langdetect 依赖)。

### 3.2 UI_LANGUAGE(Widget 界面,与答案语言分离)

`widget/src/utils/language.ts` 解析链(每次发送/打开面板时读取,SPA 页内热切换生效):

```
宿主显式(data-language / AskAIConfig.language)
  → <html lang>(G-L2 闭环:此前不读取;此前 language 仅加载时读一次)
  → 站点默认语言(site-config)
  → 浏览器语言(G-L3 闭环:此前不作兜底)
  → en
```

- **页面/宿主语言恒优先于浏览器语言**(浏览器仅末级兜底);
- 界面文案 en/zh 双变体(`widget/src/i18n.ts`,G-L4 闭环):占位/发送按钮/兜底欢迎语/失败提示/上传错误/附加提示;zh 失败文案与后端 `SERVICE_UNAVAILABLE_MSG` **逐字一致**;legacy 中文推荐问题改为按 UI 语言双变体兜底;
- UI 语言与答案语言相互独立:同一解析链、两个消费方,答案语言可因用户提问文本覆盖而异于 UI 语言。

### 3.3 站点体验本地化(G-L5 闭环)

- `site_experiences` 表新增 `welcome_i18n` / `starters_i18n`(JSONB,按语言键变体);默认 `welcome`/`starters` 语义不变;
- `GET /api/widget/site-config` 增可选 `language` 参数(归一化):有该语言变体返回变体,否则回落站点默认——**响应形状不变,站点身份字段跨语言恒等**;
- Widget 按 UI 语言拉取 site-config,页内语言热切换后自动重拉;
- 内容决策(冻结要求「三站本地化体验」):三站 `config/sites.yaml` 全部具备 en(默认)+ zh 双语 welcome 与 starters(数量逐条对应);**wiki 默认文案对齐 English**(G-L5 明确指出的未对齐项),原中文文案保留为 zh 变体,零丢失;
- 迁移脚本 `scripts/migrate_site_experiences_i18n.py`:幂等补列 + YAML 回填(只补 NULL 不覆盖)。本地双路径验证:DROP 列后执行 → `[ok]` 两列创建 + 3 行回填;重跑 → `[skip]` + 0 行。**生产执行属 Production Gate 授权范围,本任务未触碰。**

### 3.4 独立性与兼容不变式

- **site_id 独立于语言**(ML-G009):语言参数不影响站点授权(Origin 门禁跨语言恒 403)与身份(site_id/display_name/language 字段跨语言恒等);
- **会话连续性**(ML-G011):history/session 贯通不变;语言逐轮独立解析(第二轮用户显式中文可覆盖 en 页面默认);
- **Headless/自定义 UI 兼容**:`/ask` 的 `language` 本就是可选字段,现在被消费;不带 language 的调用行为与基线一致(943 回归全绿含 INT-G001~G010 组合门);headless 调用方自管其 UI,服务端行为与 Widget 无关;
- **引用完整性/canonical Wiki URL 零回归**(ML-G008/ML-G014):语言提示下 sources 的 canonical + provenance 映射与无提示逐字节一致;检索调用不被语言短路。

## 4. ML-G001~G014 门用例

后端:`tests/pipeline/test_multilingual_gate.py`(20 用例)+ `tests/api/test_multilingual_gate.py`(6 用例);Widget:`widget/src/utils/__tests__/multilingualGate.test.tsx`(11 用例)。

| 门 | 冻结要求 | 承载测试(全 PASS) |
| --- | --- | --- |
| ML-G001 | 宿主语言作为默认答案语境传播(G-L1) | pipeline `test_ml_g001_*`(hint=es → 「用 es 回答」+ trace 三元组;无提示逐字基线)+ API `test_ml_g001_ask_consumes_language_hint_end_to_end`(es-MX→es 端到端) |
| ML-G002 | 显式用户语言请求覆盖宿主默认 | pipeline `test_ml_g002_*`(en 页面中文提问→zh;zh 页面日语→ja;同族 zh-CN→zh;无效提示 fail-open) |
| ML-G003 | 页面/宿主语言优先于浏览器语言 | widget `resolveAskLanguage` 优先级组(htmlLang=en + browser=zh-CN → en;config 最高;仅浏览器→浏览器;全空省略) |
| ML-G004 | en/zh 归一化 | backend `normalize_language` 参数化 13 例 + widget `normalizeLanguage` 组 |
| ML-G005 | Widget UI 本地化(G-L4) | widget i18n 组 + ChatPanel renderToString en/zh 双渲染断言(zh 失败文案与后端常量逐字一致) |
| ML-G006 | 本地化欢迎语 | API `test_ml_g006_site_config_localized_welcome_with_fallback`(zh 变体命中;fr 回落默认) |
| ML-G007 | 本地化推荐问题 | API `test_ml_g007_site_config_localized_starters_with_fallback` |
| ML-G008 | 三站本地化体验 + 证据链不变 | API `test_ml_g008_three_sites_localized_content_present`(三站×en 默认×zh 变体×数量对齐)+ pipeline `test_ml_g008_hint_does_not_alter_retrieval_or_citation`(canonical+provenance 与提示无关) |
| ML-G009 | site_id 独立于语言 | API `test_ml_g009_site_identity_independent_of_language`(身份字段跨语言恒等;授权失败跨语言恒 403) |
| ML-G010 | 宿主语言端到端传播 + 站点默认兜底 | API `test_ml_g010_*`(站点 en 兜底;legacy 无站点 hint=None 基线)+ widget 解析链 |
| ML-G011 | 会话连续性 | pipeline `test_ml_g011_conversation_continuity_per_turn_resolution`(history 贯通 4 消息;逐轮解析) |
| ML-G012 | 本地化 smalltalk / off-topic | pipeline `test_ml_g012_*`(你好→中文回应与提示无关;hello→英文;off-topic 边界跟随答案语言:zh 提示→中文边界,es→英文边界) |
| ML-G013 | 本地化 Sales Lead 行为 | pipeline `test_ml_g013_*`(qualified+zh → 邀请指令+「用 zh 回答」共存;捕获轮 ack+zh;**PII 原文不落任何消息**;无提示英文邀请照旧) |
| ML-G014 | 引用完整性/canonical Wiki URL/Headless 兼容保持 | pipeline `test_ml_g008`(引用面)+ `test_ml_g001_answer_path_parity`(answer/stream 双路径带提示)+ 无提示路径基线一致性断言 + 全量回归(含 INT-G001~G010 组合门、canonical/social/citation 套件)全绿 |

## 5. AC-01~AC-21 验收判据

说明:任务书冻结了 15 条需求要点与 AC-01~AC-21 的数量,验收判据文本按要点逐条枚举如下(每条均落到具体测试):

| AC | 判据 | 实证 |
| --- | --- | --- |
| AC-01 | UI_LANGUAGE 与 ANSWER_LANGUAGE 为独立轴,互不决定 | widget vitest 语言组 + i18n 组;管线语言独立消费 |
| AC-02 | 页面/宿主语言优先于浏览器语言 | ML-G003 |
| AC-03 | 后端语言归一化(zh/en 族 + 主子标签 + fail-open) | ML-G004(后端 13 例) |
| AC-04 | Widget 语言归一化同语义 | ML-G004(widget 组) |
| AC-05 | 占位/按钮文案随 UI 语言切换 | ML-G005 渲染断言 |
| AC-06 | 失败兜底文案随 UI 语言切换且 zh 与后端逐字一致 | ML-G005 i18n 断言 |
| AC-07 | 兜底欢迎语与兜底推荐问题随 UI 语言切换 | ML-G005 渲染 + DEFAULT_STARTERS 双变体 |
| AC-08 | 站点欢迎语本地化,无变体回落默认 | ML-G006 |
| AC-09 | 站点推荐问题本地化,无变体回落默认 | ML-G007 |
| AC-10 | 三站双语文案齐备且数量逐条对应 | ML-G008(内容) |
| AC-11 | wiki 默认文案对齐 English,原中文零丢失(变体保留) | ML-G008(wiki 断言)+ sites.yaml diff |
| AC-12 | site_id 独立于语言(授权/身份跨语言恒等) | ML-G009 |
| AC-13 | 宿主语言作为默认答案语境被服务端消费 | ML-G001(管线+API 两层) |
| AC-14 | 显式用户语言覆盖宿主默认 | ML-G002 |
| AC-15 | 非法/缺省提示 fail-open,基线行为逐字保留 | ML-G002 参数 + ML-G010 legacy 分支 |
| AC-16 | 会话连续性:history 贯通 + 逐轮语言解析 | ML-G011 |
| AC-17 | smalltalk 按文本语言回应(与提示无关) | ML-G012 |
| AC-18 | off-topic 边界话术跟随答案语言语境 | ML-G012 |
| AC-19 | Sales Lead 邀请/确认跟随答案语言;PII HARD 不回归 | ML-G013 |
| AC-20 | 语言提示下引用完整性/canonical+provenance 零变化 | ML-G008(证据面)+ 全量引用套件绿 |
| AC-21 | Headless/legacy 兼容:language 可选;无提示与基线一致 | ML-G010 legacy + 943 回归(含 INT 组合门 11/11) |

## 6. TESTS

环境:主仓 venv(PYTHONPATH 指向工作树);一次性隔离库 `ask_ai_intgate`;models 软链 + `HF_HUB_OFFLINE=1`(全程零网络下载)。

| 套件 | 结果 |
| --- | --- |
| 后端全量 `tests/` | **943 passed, 5 skipped**(基线 906 → +37:26 个 ML 门 + 站点 i18n 相关既有用例在新列下全绿) |
| ML 门(后端) | 26/26(pipeline 20 + API 6) |
| ML 门(widget) | 11/11 |
| Widget vitest 全量 | **68 passed**(57 基线 + 11 新增) |
| Widget tsc / vite build | exit 0 / 构建成功(dist 253KB) |
| Admin tsc -b --force / vitest | exit 0 / **172 passed**(本任务未改 admin,零回归) |
| 迁移 `migrate_site_experiences_i18n.py` | DROP 后创建 `[ok]`+回填 3 行;重跑 `[skip]`+0 行(幂等双路径) |
| 迁移 `migrate_llm_chain_format`(守卫要求 ask_ai_test 库) | 4 passed |

已知非集成失败(与上一集成门相同,基线既有):embedder 4 失败 = `test_bge.py` 文件内测试隔离缺陷(单跑通过;未改动基线 f874ee4 上同样复现),非本任务引入。

## 7. 生产边界

- PRODUCTION_ACCESS = **NO**:未 SSH、未读写生产 DB/Weaviate、未触发同步、未部署、未改 CORS/DNS/反向代理/公共流量;
- PRODUCTION_MUTATION = **NO**:所有验证在本地隔离库;`migrate_site_experiences_i18n.py` 仅本地验证,**生产站点 i18n 迁移留给 Production Gate**;
- 克隆/使用 GitHub 开发仓不构成生产访问(任务书明示)。

## 8. UNRESOLVED_RISKS

1. **拉丁语系检测边界**(诚实声明):无提示时非 CJK 文本仍按基线回落 en;西语/法语等页面的正确语言依赖宿主传 `language`(解析链已保证)。未引入 langdetect 类新依赖(风险>收益,离线环境+概率误判)。
2. **生产迁移未执行**:`site_experiences` 新列 + 回填需在生产 Gate 显式跑 `scripts/migrate_site_experiences_i18n.py`(本地已验证幂等);未跑前生产 site-config 的 language 参数只会返回默认文案(无变体回落,行为安全)。
3. **UI 热切换的边界**:每次发送/打开面板时重读 `<html lang>`(SPA 场景已覆盖);未挂 MutationObserver,同一面板打开期间宿主动态改 `<html lang>` 不会即时重渲染(下一次交互生效)——契约文档未承诺更强语义。
4. **conversations.language 值域**:带提示路径落规范形(zh/en/…),无提示历史路径保留 detect 原值(zh-cn)——分析口径如按 language 分组需知悉混合值域(文档已注明)。
5. embedder 4 个基线既有测试隔离失败仍未修(建议另立微任务,与本任务无关)。

## 9. 交付物

- 分支(2 提交,线性,基于精确冻结基线 d9065df):`worktree-exec/multilingual-closure`
- 实现 + 门用例 + 契约文档更新:`f32b3f4e3a95af0b5965b35f8971019158fdfd05`
- 本报告:`docs/implementation/CAMTHINK_V1_P1_THREE_SITE_MULTILINGUAL_BEHAVIOR_CLOSURE_2026-09-02.md`
- 宿主契约文档 §3.3/§3.4 已同步闭环后行为(G-L1~L5 全部标记 CLOSED)
