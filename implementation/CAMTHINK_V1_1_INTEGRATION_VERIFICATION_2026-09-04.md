# ASK-AI v1.1 — Integration Verification / Release Candidate Gate Report

- 日期:2026-09-04
- 角色:Engineering Executor
- STATUS:**CANDIDATE VERIFIED**
- RECOMMENDED_RC_VERDICT:**PROMOTE TO RELEASE CANDIDATE**(晋升决定权在 Planner)
- **PRODUCTION_MUTATIONS = NONE**

---

## INTEGRATION_CANDIDATE

`b7a016d0d3ec91ee69a2302a519d3ce4d9e9fdbb`(IMMUTABLE;本门全程零代码改动,零为通过测试而做的修改)

## LINEAGE(L1-L6)

| 项 | 命令/方法 | 结果 |
|---|---|---|
| L1 | `git cat-file -t b7a016d…` | commit,存在 ✓ |
| L2 | `git merge-base --is-ancestor 698e727 b7a016d`(#22 accepted) | true ✓ |
| L3 | `git merge-base --is-ancestor 2306118 b7a016d`(#24 REV0) | true ✓ |
| L4 | `git merge-base --is-ancestor ba90450 b7a016d`(生产基线) | true ✓ |
| L5 | `git log --first-parent ba90450..b7a016d` | 恰 4 提交线性单亲链:`2ba83d6 → 698e727 → 2306118 → b7a016d`,零 merge commit;2ba83d6 为被接受 #22 血缘(698e727)的实现底座,非意外谱系 ✓ |
| L6 | 验证 worktree `git status --porcelain`(tracked) | 空 = 干净 ✓ |

验证环境:detached worktree `.worktrees/rc-verify-b7a016d` pinned 到 b7a016d(models 软链为环境约定,非 tracked 改动)。

## PRODUCTION_BASELINE

`ba904501bd171ed318c637ae07109174d65505ef`(v1.0.1,当前生产运行版本)

## INCLUDED_TRACKS

- Track A — Issue #22 统一发现治理 @ 698e727(含 2ba83d6 底座)
- Track B — Issue #24 REV1 Widget Launcher Appearance @ b7a016d(含 2306118 REV0 底座)

## MIGRATION_REHEARSAL(M1-M11)

方法:**不是**对已升级开发库测试——从 ba90450 worktree 代码 `Base.metadata.create_all` 构造 v1.0.1 生产基线 schema(实证:`launcher_style`/`launcher_icon` 列均不存在),灌入 3 行生产形态站点数据(identity/origins/welcome/starters/language/enabled),再从候选树执行真实迁移路径。隔离库 `ask_ai_rcgate`(本地隔离 Postgres;零生产接触)。

| 项 | 验证 | 结果 |
|---|---|---|
| M1 | 基线 schema 前向迁移 | ba90450 schema → REV0 迁移 → REV1 迁移全部成功 ✓ |
| M2 | REV0 迁移(launcher_style/theme) | `migrate_add_site_launcher_appearance.py` 成功,两列出现 ✓ |
| M3 | REV1 迁移(launcher_icon/shape) | `migrate_add_site_launcher_icon_shape.py` 成功,两列出现 ✓ |
| M4 | 幂等重跑 | 两脚本各自二次执行全过(IF NOT EXISTS)✓ |
| M5 | 行不被静默改写新图稿 | 全部行 launcher_icon/launcher_shape 保持 NULL ✓ |
| M6 | 身份/origins/welcome/starters/language/enabled 存活 | 3 站点逐字段断言全等 ✓ |
| M7 | REV0 launcher_style 兼容数据存活 REV1 迁移 | wiki 行 chat-bubble/dark 原值保留 ✓ |
| M8 | NULL 新列 → 兼容默认 | 候选代码 resolve_site:current / rounded-square / auto ✓;遗留 chat-bubble → 有效 icon=current + 回显保留 ✓ |
| M9 | seed 不覆写 Admin 外观 | `seed_default_sites`(3 站)后外观值原样 ✓ |
| M10 | schema == 候选 ORM | `SiteExperience.__table__.columns` ⊆ DB 列,无缺失 ✓ |
| M11 | 前向/回滚含义 | 见下 |

**回滚语义(诚实声明)**:前向 = 两nullable 加列,零回填零改行。回滚到 ba90450/REV0 旧应用:旧代码只读 `launcher_style`(冻结未触碰)→ 按遗留值渲染,行为确定;新列被旧代码忽略,无破坏。**破坏性 schema 回滚(DROP COLUMN)未测试、也未声称安全**;满足契约要求的保证:旧数据完好 + 新应用正确启动(候选应用在此迁移库上实际启动,`/health` git_sha=b7a016d)+ 回滚行为已被理解。

## ISSUE_22_ACCEPTANCE(D22-1..D22-10)

对最终组合候选(非历史 698e727)重跑 `tests/services/test_issue22_governance.py`(含 neomind-dashboard/components 具体案例、REV2 L3 组界门控、member_review 可见性、Admin 裁决持久化)及 `tests/api/admin/test_data_sources_discovery.py`、`tests/api/test_repo_discovery.py`:

| 项 | 映射测试证据 | 结果 |
|---|---|---|
| D22-1 components 13 文件进推荐 | components 具体案例测试(compile 组界门控) | ✓ |
| D22-2 安全推荐免冗余审批 | safe=decision 语义测试(L1/L2 即决策) | ✓ |
| D22-3 Apply 只消费已决/安全 | apply 组界门控(group decided include ∧ member rec include ∧ technical_safe) | ✓ |
| D22-4 未决 L3 保持可见 | member_review 呈现测试 | ✓ |
| D22-5 未决 L3 不因多数进策略 | REV2 partial-consumption 防护测试 | ✓ |
| D22-6 未决 L3 不因多数离策略 | 同上(编译排除) | ✓ |
| D22-7 Admin Include 持久化+编译 | decision_origins/discovery_rules 持久化测试 | ✓ |
| D22-8 Admin Exclude 持久化+编译 | 同上 | ✓ |
| D22-9 高置信排除保持安全 | unsafe/binary L1 生产者 stamp 测试 | ✓ |
| D22-10 后续评估消费持久治理不再重复问 | rules_matching/apply 幂等测试 | ✓ |

Focused 结果:**44 passed**(issue22 governance + 两套 #24 appearance 文件,单命令)。

## ISSUE_24_REV1_ACCEPTANCE(D24-1..D24-10)

活栈(候选后端 :8810,`/health` 实证 git_sha=b7a016d)真实浏览器 DOM 断言:

| 项 | 活体证据 | 结果 |
|---|---|---|
| D24-1 current 保留遗留外观 | img glyph + radius 12px + bg rgb(0,0,0) | ✓ |
| D24-2 四个 PO 供给 SVG 渲染 | 四 case 均 svg.ask-ai-fab-glyph + aria-hidden | ✓ |
| D24-3 四图标 × round | bubble-sparkle-fill round:radius 50% | ✓(其余组合见矩阵/单测) |
| D24-4 四图标 × rounded-square | robot-smile rounded-square:radius 14px | ✓ |
| D24-5 icon×shape 独立 | 组合遍历(活体+vitest S1-S8) | ✓ |
| D24-6 CamThink 橙识别 | bg rgb(242, 74, 0)(= #f24a00) | ✓ |
| D24-7 零外部视觉资产请求 | `externalResources: 0`(performance resource 同源过滤) | ✓ |
| D24-8 非法 icon → current | `icon=not-an-icon` → icon=current/img/黑底 | ✓ |
| D24-9 非法 shape 失败安全 | `shape=hexagon` → rounded-square/14px | ✓ |
| D24-10 非法 theme 失败安全 | `theme=sepia` → light | ✓ |

## THEME_RUNTIME(T1-T8)

matchMedia 受控桩(真 widget.js、真浏览器;唯一被桩化的输入,resolve/subscribe/setState 全部真实执行):

| 项 | case | 结果 |
|---|---|---|
| T1 显式 light | theme=light + 系统 dark 信号 | light ✓(忽略) |
| T2 显式 dark | theme=dark + 系统 light 信号 | dark ✓(忽略) |
| T3 auto+系统 light | mm=light | light ✓ |
| T4 auto+系统 dark | mm=dark | dark ✓ |
| T5 auto 运行时跟随 | mm=flip:t=0 light → t=1.2s 派发 change → 重查 dark | ✓ |
| T6 matchMedia 不可用 | mm=none(delete matchMedia) | light ✓ |
| T7/T8 显式值忽略系统变化 | useResolvedTheme 显式分支不订阅(单测 T7 断言订阅器不被调用)+ T1/T2 活体 | ✓ |

无宿主主题推断(无 DOM/CSS/背景启发;代码审计 + 契约测试)。

## PER_SITE_ACCEPTANCE(P1-P9)

隔离库 4 站点(3 基线站 + rc-gate-site;其中 wiki 带遗留 REV0 数据):

| 项 | 证据 | 结果 |
|---|---|---|
| P1 站点 A/B 外观不同 | Admin 列表:官网=机器人笑脸·圆形·深色 vs Wiki=经典·圆角方·深色 | ✓ |
| P2 保存持久 icon+shape+theme | UI 保存 → API 直读 ('bot-sparkle','round','dark') | ✓ |
| P3 重读恢复 | 页面重载后列表同值 | ✓ |
| P4 未保存不持久 | 草稿点选后 API 直读仍为旧值 | ✓ |
| P5 切站不泄漏草稿 | 脏草稿切站 → 徽章回「已保存」 | ✓ |
| P6 seed/重启不覆写 | M9(隔离库)+ P7 pytest | ✓ |
| P7 遗留/未配置站 current 兼容 | wiki=经典(默认)+ 退役提示文案活体呈现 | ✓ |
| P8 非法枚举 422 | 活体 PUT assistant-spark/hexagon → 422 | ✓ |
| P9 未知站 404 | 活体 PUT no-such → 404 | ✓ |

## WIDGET_RUNTIME(W1-W12)

| 项 | 证据 | 结果 |
|---|---|---|
| W1-W3 预览随 icon/shape/theme 更新 | Admin 草稿即时联动(vitest A4 srcDoc 断言)+ 活体未保存徽章/卡片联动 | ✓ |
| W4 预览背景独立 | UI 独立控件(vitest A5 + 活体页面) | ✓ |
| W5 预览零 /ask 流量 | iframe sandbox=allow-scripts + pointer-events:none;会话计数不变 | ✓ |
| W6 零会话创建 | 全程前后 `conversations` 计数 = 0(隔离库直查) | ✓ |
| W7 不绕过站点授权 | 预览通道无授权面;G 组全过 | ✓ |
| W8 正常集成无需外观属性 | 全部 D24 活体 case 即裸嵌入(api-url+site 或更少) | ✓ |
| W9 Admin 改外观→客户页零改动生效 | 嵌入页不变,仅 Admin PUT → 重载即 robot-smile/round/dark | ✓ |
| W10 高级覆盖 data-launcher-icon/shape/theme | 活体 W11-override case | ✓ |
| W11 优先级 explicit > site > default | site-only / +override / +invalid override 三 case 活体 | ✓ |
| W12 legacy data-launcher-style 兼容性/弃用位 | legacy=chat-bubble → icon=current(退役,非映射);文档标 deprecated | ✓ |

## AUTHORIZATION_REGRESSION(G1-G9)

| 项 | 证据 | 结果 |
|---|---|---|
| G1 合法站+允许 Origin | 活体 site-config 200(完整体验+外观体) | ✓ |
| G2 错误 Origin | 活体 403 | ✓ |
| G3 未知站 | 活体 403 | ✓ |
| G4 禁用站 | 进程内 resolve_site SiteDenied(注:首测误报系 M9 种子按 YAML 重启用站点所致,非授权缺陷;干净状态复测拒绝) | ✓ |
| G5 缺失/不可解析 Origin | SiteDenied | ✓ |
| G6 外观覆写不能授予访问 | launcher_icon/shape/theme 全设置 + 错 Origin → SiteDenied | ✓ |
| G7 外观字段不影响授权链 | 同上 + 授权路径代码零改动(diff 审计) | ✓ |
| G8 预览架构无新旁路 | 预览 iframe 沙箱不能携凭证/不能持久化;Admin API 照常 role 门禁 | ✓ |
| G9 legacy 无 siteId 行为不放宽 | 裸嵌入(无 site)活体正常渲染且零站点调用;#6/#8 契约未动 | ✓ |

## FULL_REGRESSION

`pytest tests/ -q`(隔离测试库,HF_HUB_OFFLINE=1):**1613 passed / 0 failed / 6 skipped**(44.03s)。
含聚焦 #22(governance 606 行)+ #24(widget-appearance 241 行 + site-config 114 行)全部用例。零回归、零环境失败掩盖(过程中 worktree 缺 models 软链的环境问题已按约定以软链修正后重跑,未改候选代码)。

## BUILDS

- Widget 生产构建:vite ✓(dist 仅 widget.js + ask-ai-widget.css 两文件)
- Admin 生产构建:tsc -b + vite ✓
- 构建产物字节与 REV1 执行报告完全一致(见 BUNDLE)

## HOSTED_CI

- 机制:`Build & Push GPU Image` workflow 具备 `workflow_dispatch`(仓库普通流程),以 `--ref v1.1/issue24-launcher-design-rev1` 派发,headSha 实证 = b7a016d(精确候选,非本地测试冒充 CI)。
- Run:**33850591883**(https://github.com/harryhua-ai/ask-ai/actions/runs/33850591883)
- 结论:见本文末尾「HOSTED_CI 结果回填」;test job 先行,fail 则不出镜像。
- LOCAL VERIFICATION 与 HOSTED CI 分开记录,本地测试未称 CI。

## BUNDLE

从 immutable 候选重新构建重测(detached worktree,与候选树字节一致):

| 项 | 基线 2306118(#24 REV0) | 候选 b7a016d | delta |
|---|---|---|---|
| JS raw | 257,243 B | 258,916 B | **+1,673 B(+0.65%)** |
| JS gzip | 90.45 kB(vite) | 90,573 B 实测 / 91.21 kB(vite) | ≈+0.76 kB |
| CSS raw | 5,756 B | 6,349 B | +593 B |
| CSS gzip | 1.73 kB | 1,860 B | +~0.11 kB |

- 对 v1.0.1 生产基线的累计增量 = REV0(+3.8KB)+ REV1(+1.7KB),全部有界;
- 无阻塞外部 launcher 视觉请求(四图标内联 SVG;`externalResources: 0` 活体断言);
- 无异常大依赖、无 REV1 引起的 bootstrap 退化(加载即渲染,零新增网络请求)。

## INTEGRATION_DOCUMENTATION_AUDIT(DOC1-14)

对 `docs/integration/WIDGET_INTEGRATION.md`(Contract 1.1)逐项对照 b7a016d runtime:

| 项 | 结论 |
|---|---|
| DOC1 Quick Start 可执行 | ✓ 与活体 harness 同构(css+js 成对,data-api-url+data-site-id) |
| DOC2 required/optional | ✓ data-api-url required(默认 localhost:8000 如实标注),其余 optional |
| DOC3 siteId 语义 | ✓ 标识非凭证;公开源码安全;禁止放密钥 |
| DOC4 Origin 语义 | ✓ 归一化+精确命中+403 不泄因;与 resolve_site 实现一致 |
| DOC5 icon 枚举 | ✓ 与 LAUNCHER_ICONS 逐一相符 |
| DOC6 shape 枚举 | ✓ 与 LAUNCHER_SHAPES 相符 |
| DOC7 theme 枚举 | ✓ |
| DOC8 Auto 语义 | ✓ matchMedia 唯一信号/不可用回 light/运行时跟随/显式忽略(与 T 组一致) |
| DOC9 覆盖属性 | ✓ 三通道(script/preset/global)+ camelCase 键名与 bootstrap 一致 |
| DOC10 优先级 | ✓ 逐键 script→preset→global→默认;跨源 explicit>site>default 与 App 一致 |
| DOC11 升级指引 | ✓ v1.0.x 零改动持续工作(M 迁移门实证);采纳外观无需改嵌入 |
| DOC12 遗留/弃用区分 | ✓ 表格化 deprecated/retired/canonical;legacy 值退役为 current 与 W12 一致 |
| DOC13 未暴露内部 DB 实现 | ✓ 仅描述 API 面(site-config 字段)与行为,无列名/表名 |
| DOC14 示例不声称未支持行为 | ✓ 单实例防双浮窗、SPA 挂载语义、多站示例均与实现核对 |

**结论:无 material integration error;无需在不可变门内改文档。**

## SCOPE_AUDIT(ba90450 → b7a016d)

`git diff --stat ba90450..b7a016d`:**35 文件,+3613/−87**。分类:

- **#22 expected(14)**:source_discovery.py、repo_discovery.py、website_discovery.py、admin/data_sources.py、source_center_schemas.py、RepoDiscoveryPanel.tsx、DataSources.tsx、useDataSources.ts、types/api.ts(+8,REV2 member_review,冻结接口内 additive——被接受改动)、test_issue22_governance.py、test_data_sources_discovery.py、test_repo_discovery.py(3 行)、RepoDiscoveryPanel.test.tsx
- **#24 expected(19)**:widget 全部(App/bootstrap/i18n/launcher×3/styles/types/launcher.test)、backend widget_appearance.py、routes.py(+13 site-config 字段)、models.py(+4 launcher 列)、site_experiences.py(+77 枚举/解析)、两迁移脚本、admin router.py(+2 注册)、admin App.tsx(+2 路由)、Sidebar.tsx(+2 导航)、WidgetAppearance.tsx/.test.tsx、两套 #24 后端测试
- **required supporting**:models/site_experiences/routes/router 为两 track 的公共加法面(全部 additive)
- **unexpected:无**

禁触面 grep(rag/llm/retriev/rerank/citation/conversation/sync/connector/pipeline/security/cors/auth):**零命中**。LLM 行为、RAG 语义、检索、重排、引用、会话持久化、sync 运行时、生产配置、secrets、基础设施:零改动。

## KNOWN_LIMITATIONS

1. 主题作用域 = launcher(V1 契约边界;ChatPanel 主题化不在轨道);
2. 形状对 `current` 不生效(遗留渲染器拥有形状,契约明示);
3. 开启态 X 图标/旋转动画未采用(panel 归属不重设计;契约明示非必需);
4. SSE 问答端到端未在隔离栈演练(无 LLM 配置)——由候选全量回归中既有 SSE/生成链路测试覆盖,本门未重复;
5. T7/T8 的「显式主题忽略运行时变化」由单测订阅断言 + T1/T2 反向信号活体共同证明,未单独做运行时翻转;
6. 破坏性 schema 回滚未测试(见 M11,契约明确不要求声称安全);
7. hosted CI 的镜像 job(若 test 绿)会产出 sha-b7a016d 镜像,属普通流程产物,非部署行为。

## PRODUCTION_MUTATIONS

**NONE**——零生产部署、零生产迁移、零生产配置/Weaviate/数据触碰、零 release tag。隔离设施(一次性 weaviate 容器、隔离库、:8810 临时进程)已全部拆除;隔离库 `ask_ai_rcgate` 保留至报告提交后销毁。

## HOSTED_CI 结果回填

- Run **33850591883** 已完成,结论 **success**:`test` job **success**、`build-and-push` job **success**(sha-b7a016d 镜像按普通流程产出并存入 GHCR,属工作流正常产物,非部署行为)。
- 即:候选 b7a016d 通过仓库标准 hosted CI(test 先行 + 镜像构建),LOCAL 与 HOSTED 结论一致。

## RECOMMENDED_RC_VERDICT

**PROMOTE TO RELEASE CANDIDATE** —— 候选 b7a016d 通过全部本门验证:血缘纯净、迁移路径真实可走、两轨道语义共存无冲突、授权零弱化、文档与 runtime 一致、零意外改动面。
