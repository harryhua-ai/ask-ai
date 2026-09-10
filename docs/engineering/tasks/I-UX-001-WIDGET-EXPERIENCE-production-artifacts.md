# I-UX-001 v1.3.0 Production Acceptance — Evidence Artifact Manifest

- RELEASE:`v1.3.0` @ `harryhua-ai/ask-ai`
- SOURCE_SHA:`8bec1c0251d25630b5e2d461a9a5671cb2841b34`
- CI RUN:`34342510200`(Build & Push GPU Image,success)
- ARTIFACT_ROOT:`docs/engineering/tasks/artifacts/I-UX-001-v1.3.0-production/`
- 主报告:`docs/engineering/tasks/I-UX-001-WIDGET-EXPERIENCE-production-acceptance.md`(下称【报告】)
- 证据性质:全部为 2026-09-09 生产验收窗口**既有采集物**的发布(逐字节复制),
  未为本清单重新生成/补采任何证据。

图例:TYPE = PNG(浏览器截图)/ TXT(命令输出转录,逐字节复制)/ REPORT(主报告内
记录的当场捕获值)。CAPTURED_AT 为采集窗口(UTC)。

---

## A. RELEASE IDENTITY

| CLAIM | ARTIFACT_PATH | TYPE | CAPTURED_AT | NOTES |
| --- | --- | --- | --- | --- |
| 镜像 v1.3.0 由源 8bec1c0 构建(CI 34342510200) | 【报告】§1 | REPORT | 2026-09-09 | CI run 状态/时长由 `gh run` 采集;build 信息含于镜像 RELEASE.json |
| 镜像内 RELEASE.json:version=1.3.0, git_sha=8bec1c0…, ci_run_id=34342510200 | 【报告】§1(部署前目标镜像 docker cp 实测值) | REPORT | 2026-09-09 ~10:56Z(built_at) | update.sh [3/6] 同一断言机制的输入 |
| 运行时身份:/health = 1.3.0 / 8bec1c0… / production | 【报告】§1;`artifacts/I-UX-001-v1.3.0-production/observation-window-transcript.txt` 行 1-2 | REPORT + TXT | 2026-09-09 ~11:2xZ | transcript 为部署后观察窗原始输出(health JSON 含 sha) |
| 启动日志 release identity(manifest 来源) | 【报告】§1 | REPORT | 2026-09-09 | `docker logs` 当场捕获值 |

## B. MIGRATION

| CLAIM | ARTIFACT_PATH | TYPE | CAPTURED_AT | NOTES |
| --- | --- | --- | --- | --- |
| pre-migration:无 entry_mode 列;3 个既有站点 | 【报告】§3 | REPORT | 2026-09-09 ~11:0xZ | information_schema + site_experiences 行列查询当场捕获 |
| 备份身份:`pg_askai_predeploy_iux001_20260909T110548Z.dump`(8,224,318 B) | 【报告】§3/pg_dump 文件名(时间戳即文件名) | REPORT | 2026-09-09 11:05:48Z | 文件保留于生产 `~/ask-ai/backups/`(本次不触碰生产,故未入库) |
| 备份可验证:pg_restore -l TOC 121 条目 | 【报告】§3 | REPORT | 2026-09-09 | 归档头 dbname=ask_ai |
| 迁移结果输出 | 【报告】§3 | REPORT | 2026-09-09 | `✅ … 已确保存在`;幂等脚本 |
| post-migration schema:10 列(varchar)全部存在 | 【报告】§3 | REPORT | 2026-09-09 | information_schema 实测 10 行 |
| 既有三站 entry_mode=NULL(迁移后) | 【报告】§3 | REPORT | 2026-09-09 | 逐行查询输出 |
| 既有三站 NULL 经重启 reseed 后仍保持 | 【报告】§3 | REPORT | 2026-09-09 | seed 只写 YAML 字段的生产行为实证 |
| OPS-1:迁移需 PYTHONPATH=/app(脚本缺 sys.path bootstrap) | 【报告】§9 | REPORT | 2026-09-09 | 非阻塞 follow-up,本次未修 |
| OPS-2:生产 .env 含 TEST_DATABASE_URL,DSN guard fail-closed 拦截后清除重跑 | 【报告】§9 | REPORT | 2026-09-09 | 守卫按设计工作;非阻塞 |

## C. TRUSTED ACTION LIFECYCLE

| CLAIM | ARTIFACT_PATH | TYPE | CAPTURED_AT | NOTES |
| --- | --- | --- | --- | --- |
| DRAFT 创建(Specifications / Find docs) | 【报告】§7 | REPORT | 2026-09-09 | Admin API 实测,id 留档于会话 |
| TEST(真实 ASK-AI 管道;规格类回答 + 3 sources) | 【报告】§7 | REPORT | 2026-09-09 | last_test_result 落库 |
| VERIFIED(依赖 test 结果) | 【报告】§7 | REPORT | 2026-09-09 | |
| PUBLISHED(仅 verified 可发布) | 【报告】§7 | REPORT | 2026-09-09 | |
| 发布边界:public site-config 仅返回 published | 【报告】§6 行 8a + §7 | REPORT | 2026-09-09 | curl 实测:actions=[Specifications] |
| VERIFIED-not-PUBLISHED 隐藏 | `artifacts/…/prod-desktop-ctx-mini.png` + 【报告】§6 行 8a | PNG + REPORT | 2026-09-09 | 截图中 mini 恰 1 个 chip(Specifications);Find docs 未渲染 |

## D. DESKTOP C

| CLAIM | ARTIFACT_PATH | TYPE | CAPTURED_AT | NOTES |
| --- | --- | --- | --- | --- |
| 上下文问候(产品专名,HIGH) | `artifacts/…/prod-desktop-ctx-mini.png` + 【报告】§6 行 6-8 | PNG + REPORT | 2026-09-09 ~11:1xZ | "Questions about NE503?" |
| ≈6 秒自动展开(balanced) | 同上 | PNG + REPORT | 2026-09-09 | 加载后 9s 检查点 mini=1 |
| published 动作渲染且恰 1 个 | 同上 | PNG + REPORT | 2026-09-09 | chips=1 |
| 动作点击 → 浮动窗 + 恰 1 个真实 /api/ask | `artifacts/…/prod-desktop-chat-request.png` + 【报告】§6 行 7 | PNG + REPORT | 2026-09-09 | 网络层捕获请求体=message=绑定问句,channel=widget,site_id=iux001-acceptance |
| 流式回答(生产语料) | `artifacts/…/prod-desktop-chat-answer.png` | PNG | 2026-09-09 | NE503 规格回答已渲染完成 |
| 行内引用(refs=2) | 同上 | PNG | 2026-09-09 | 截图内 2 个引用徽标清晰可见 |
| 无重复 Sources 段(sourcesList=0) | 【报告】§6 行 7/10 + 同上截图 | REPORT + PNG | 2026-09-09 | DOM 计数;截图视觉一致(无 Sources 清单) |

## E. FAIL-CLOSED

| CLAIM | ARTIFACT_PATH | TYPE | CAPTURED_AT | NOTES |
| --- | --- | --- | --- | --- |
| 无/不受信上下文 | `artifacts/…/prod-desktop-nofailclosed-ctx.png` + 【报告】§6 行 8d | PNG + REPORT | 2026-09-09 | acceptance.html(无 pageContext) |
| 通用问候(无专名伪造) | 同上 | PNG + REPORT | 2026-09-09 | "How can I help?" |
| 0 个 Trusted Action chip | 同上 | PNG + REPORT | 2026-09-09 | {product} 模板不可绑定 → 不渲染 |
| 无自动 ASK-AI 请求(ask=0) | 【报告】§6 行 8d | REPORT | 2026-09-09 | 网络监听计数 |

## F. MOBILE(390×844)

| CLAIM | ARTIFACT_PATH | TYPE | CAPTURED_AT | NOTES |
| --- | --- | --- | --- | --- |
| 不自动展开完整 mini(=0) | `artifacts/…/prod-mobile-nudge.png` + 【报告】§6 行 9 | PNG + REPORT | 2026-09-09 | |
| B-style nudge(上下文问候 + dismiss) | 同上 | PNG + REPORT | 2026-09-09 | "Questions about NE503? ✕" |
| nudge 点击 → 聊天(显式单交互) | `artifacts/…/prod-mobile-chat.png` | PNG | 2026-09-09 | panel=1 |

## G. ADMIN

| CLAIM | ARTIFACT_PATH | TYPE | CAPTURED_AT | NOTES |
| --- | --- | --- | --- | --- |
| 生产 Admin Widget 体验页真实可访问 | `artifacts/…/prod-admin-widget-experience.png` | PNG | 2026-09-09 | NOTE:截图含登录会话的管理员账号邮箱(会话身份),不含任何凭证/token |
| 既有站点显示"保持现状(未配置)" | 同上 | PNG | 2026-09-09 | 三正式站 legacy NULL 语义的 Admin 呈现 |
| fixture 站点 C 配置呈现 | 同上 | PNG | 2026-09-09 | iux001-acceptance = C · Mini Conversation Entry |

## H. OBSERVATION WINDOW

| CLAIM | ARTIFACT_PATH | TYPE | CAPTURED_AT | NOTES |
| --- | --- | --- | --- | --- |
| ≈10 分钟观察窗(3 检查点) | `artifacts/…/observation-window-transcript.txt` | TXT | 2026-09-09 ~11:2x-11:3xZ | 逐字节原始输出;checkpoint 3 的 SSH 瞬断(本机网络)如实保留 |
| restarts=0 / status=running | 同上 行 2/5 | TXT | 2026-09-09 | docker inspect |
| traceback/OOM/fatal = 0 | 同上 行 3/6 | TXT | 2026-09-09 | 3 分钟滚动日志 grep 计数 |
| console error = 0 / requestfailed = 0(浏览器面) | 【报告】§6 行 11 | REPORT | 2026-09-09 | 各场景监听计数;初次 CORS 4xx 为测试配置问题,修正后复测干净(如实记录) |

## I. CLEANUP(最终态)

| CLAIM | ARTIFACT_PATH | TYPE | CAPTURED_AT | NOTES |
| --- | --- | --- | --- | --- |
| fixture 站点已删(delete returning iux001-acceptance) | 【报告】§5 + §12 cleanup 实测 | REPORT | 2026-09-09 | 级联删除其 Trusted Actions |
| 临时 Trusted Actions 已删 | 【报告】§5 | REPORT | 2026-09-09 | |
| 临时 CORS origin 已还原(grep=0) | 【报告】§5 | REPORT | 2026-09-09 | .env 从 .env.bak_iux001_acceptance 还原 |
| 最终站点数 = 原始 3 | 【报告】§5 | REPORT | 2026-09-09 | 清理后 count 实测 |
| site_trusted_actions = 0 行 | 【报告】§5 | REPORT | 2026-09-09 | |
| 最终运行时健康(1.3.0/8bec1c0) | 【报告】§5(还原重启后 /health) | REPORT | 2026-09-09 | |

## FINAL-STATE 四类证据判定(Role A 指定)

| 类别 | 判定 | 支撑 |
| --- | --- | --- |
| FINAL RUNTIME IDENTITY | READY | A 组(§1 报告记录值 + observation transcript 行 1-2 health JSON) |
| FINAL DB / CLEANUP STATE | READY | I 组 + B 组(清理后 3 站/0 动作/entry_mode NULL/健康) |
| BROWSER ACCEPTANCE | READY | C/D/E/F/G 组截图 + 报告 §6 |
| OBSERVATION WINDOW | READY | H 组 transcript + 报告 §6 行 12 |

## EVIDENCE GAP(如实声明,不以补采填充)

- **RESIDUAL GAP:New-site default C 未在生产直接行使**(未创建永久性生产 YAML
  站点);证据链 = 迁移契约 + `seed_default_sites` 单测 + 既有行 NULL 的生产实证
  (【报告】§3、§10)。
- 截图不证明其画面之外的状态:例如 admin 截图证明页面渲染与配置呈现,不证明
  API 层 RBAC;此类 API 级断言以【报告】文字记录的当场捕获值(CURL/DOM 计数)为准。
- WITHHELD_SENSITIVE:无(全部既有证据均无敏感物,secret 扫描见提交前自检;
  admin 截图含会话邮箱身份已标注)。

## NON-BLOCKING FINDINGS(保留为 follow-up,非本发布阻塞)

- OPS-1:迁移脚本未自带 sys.path bootstrap,一次性容器运行需 `PYTHONPATH=/app`。
- OPS-2:生产 .env 携带 `TEST_DATABASE_URL`,迁移 DSN guard 正确 fail-closed,
  一次性运行时清除该覆盖后执行。
- 两项均未在本发布中修复(证据发布 only)。
