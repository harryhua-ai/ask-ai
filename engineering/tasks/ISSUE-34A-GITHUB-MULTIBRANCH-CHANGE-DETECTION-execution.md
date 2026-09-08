# ISSUE-34A — Multi-Branch GitHub Change Detection Correctness — 执行报告

- 日期:2026-09-08
- 角色:Engineering Executor(IMPLEMENT / TEST / VERIFY)
- 状态:**CANDIDATE READY**(待 Planner 验收)
- 生产触碰:无(零部署/零重启/零 DB 变更/零配置变更)

## 1. Baseline

| 锚 | SHA |
|---|---|
| 分支基(origin/main,含 I-001 集成与 docs) | `203eec5` |
| 生产/缺陷基线(v1.1.2,2026-09-07 事故运行版本) | `cdbcad3` |
| 同步路径漂移证明 | `cdbcad3..203eec5` 对 `backend/connectors/**` + `tests/connectors/**` diff 为空 → 本报告代码阅读即生产权威 |

## 2. RCA 确认(工程根因)

`backend/connectors/github.py` 旧 `_remote_has_updates(branch)` 以 **`git rev-parse HEAD`(单一移动 HEAD)** 为本地比较基准:

1. `fetch_changes` 按配置顺序逐分支处理,每次真实同步执行 `reset --hard origin/<branch>` 推进 HEAD;
2. 处理完分支 A 后 HEAD 停在 A 的 tip;
3. 分支 B 拿远端 SHA 与 HEAD(=A)比较 → 只要 A、B tip 不同即恒判"有更新";
4. **未变更分支因此每轮执行真实 `git fetch` + `git reset`**;
5. 二阶效应:误 fetch+reset 后 `_read_local_changes(B)` 在被改写的 HEAD 上跑 `git log --since`,把共享历史文件以 B 分支标签**每轮虚假再摄入**(RED 证据中实证:全未变更源产出 `branch='release'` 标签的 `main.md`)。

生产印证(2026-09-07 只读取证):3 个多分支源(meta-hailo-os [main,v1.12.1] / ne301 [main,halow,ir-ver] / lowpower_camera [hw-v1.2,hw-v2.0])吸收了当日**全部 21 次** github.com:443 连接失败;8 个单分支源零失败(其短路有效,平时零触网);clone reflog 证实每小时每分支真实 fetch+reset。网络层直接原因(间歇 TCP SYN 黑洞)不在本任务范围;本缺陷是其**暴露放大器**。

## 3. 实现摘要(最小变更)

比较基准从移动 HEAD 改为 **`refs/remotes/origin/<branch>`(该分支自己的远端跟踪 ref)** —— 只随该分支自身的 fetch 推进,天然分支特定、顺序无关、HEAD 无关,完全复用既有 git 元数据,零新增状态:

- 新增 `_local_branch_sha(branch)`:`git rev-parse --verify --quiet refs/remotes/origin/<branch>`,缺失返回 None;
- 重写 `_remote_has_updates(branch)`:API SHA vs 跟踪 ref;**None → True**(首同步安全);**API 异常 → True**(既有降级,warning 文案不变);
- 删除死代码 `_git_local_sha`;
- **不变**:`_git_sync_branch`(fetch+reset)、`fetch_all` 全量路径、`recovery_replay`(F16)旁路、token/鉴权、错误脱敏。

## 4. 变更文件

| 文件 | 变更 |
|---|---|
| `backend/connectors/github.py` | 修复(上述 §3) |
| `tests/connectors/test_github.py` | 3 个单测重指新比较基准(patch `_local_branch_sha`)+ 新增缺失跟踪 ref 用例(合同驱动的基准重指,语义矩阵保持:diff→True / same→False / API fail→True) |
| `tests/connectors/test_github_multibranch_change_detection.py` | **新增** 8 场景验收(真实本地 git 仓 + fetch 计数 spy,零外网) |

## 5. BEFORE / AFTER 网络行为(实证)

**BEFORE**(未修复代码上执行新测试:6 failed / 2 passed):
- 全未变更多分支源每轮真实 `git fetch origin release` + reset(A 失败证据),并产出错误分支标签的虚假再摄取文档;
- 单分支变更时,未变更分支同样被 fetch(D 顺序测试在旧代码下 clone_a=[main,release] 两条都 fetch);
- HEAD 停在其它分支时,未变更分支被误 fetch(E 直接复现)。

**AFTER**(修复后全绿):
- 全未变更 → **零 fetch、零文档产出**(两轮验证);
- 仅真实变更分支 fetch(B/C);顺序反转判定不变(D);HEAD 归属无关(E);
- 缺失跟踪 ref → 安全 fetch 一次,随后恢复短路(F);
- API 故障 → 每分支降级 fetch(G,既有语义);fetch 失败 → RuntimeError 传播不变(H)。

## 6. 实际执行的测试

| 层级 | 命令/范围 | 结果 |
|---|---|---|
| RED 复现(修复前) | 新测试文件 8 场景 @ 未修复代码 | 6 failed / 2 passed(缺陷实证) |
| 聚焦(修复后,black 后复跑) | 新文件 + test_github + recovery_replay | **27 passed** |
| connectors 全目录 | `tests/connectors/` | 195 passed,2 errors(web_crawl_w6_snapshot:本地无 `ask_ai` 库的环境依赖,全量套件带 TEST_DATABASE_URL 时通过,非本变更) |
| sync 相关 | `tests/pipeline/test_sync.py` + `tests/scripts/` + `tests/test_evidence_meta.py` | 238 passed,3 skipped |
| **全量离线** | `PYTHONPATH=<wt> HF_HUB_OFFLINE=1 TEST_DATABASE_URL=...ask_ai_test pytest tests/ -q` | **1859 passed / 5 skipped / 1 failed + 4 errors** |
| 基线对照 | `git stash -u` 后同环境跑同 5 个失败用例 | **完全相同的 1 failed + 4 errors** → 零回归,失败为基线环境既有(worktree 无 models 软链 → embedder HF 离线 ×4;lifespan smoke 已知环境敏感) |
| 格式 | black(仅 3 个改动文件) | reformatted,复跑 27 绿 |

未削弱/未删除任何既有测试以获取 PASS;唯一改动是把 3 个编码**旧比较基准**的单测重指到新基准(合同变更本体),并新增一个基准边界用例。

## 7. 验收矩阵

| # | 场景 | 结果 |
|---|---|---|
| A | 全分支未变更 → 无跨分支误判 | ✅ `test_a_all_branches_unchanged_no_fetch`(两轮零 fetch) |
| B | 单分支变更 → 只有它同步 | ✅ `test_b_only_changed_branch_fetches` |
| C | 多分支变更 → 全部检出 | ✅ `test_c_multiple_changed_branches_all_detected` |
| D | 分支顺序无关 | ✅ `test_d_branch_order_independence` |
| E | HEAD 归属无关(缺陷直接复现) | ✅ `test_e_checkout_state_independence` |
| F | 首同步/缺失本地分支状态 → 安全同步 | ✅ `test_f_missing_tracking_ref_safe_sync` |
| G | 远端检视失败 → 既有降级 | ✅ `test_g_api_failure_degrades_to_fetch_per_branch` |
| H | 认证/仓库错误语义不回归 | ✅ `test_h_fetch_failure_raises_runtime_error` + 既有 C10 脱敏/recovery_replay 全绿 |
| 网络操作验证 | fetch 计数 spy(BEFORE 有误 fetch → AFTER 零),真实本地 git 仓,不依赖外网 | ✅ |

## 8. 遗留风险

1. 短路正确性依赖 api.github.com 的新鲜度/可用性 —— 与修复前同一 API 信任级别;API 不可用时降级为 fetch(fail-safe 方向)。
2. 远端分支被删除:API 404 → 降级 True → fetch 失败 → 源 failed(与修复前行为一致,未改变;如需优化属后续关注点)。
3. `_read_local_changes` 依赖"读之前刚 reset 过该分支"的隐式不变量(本修复保持且只在该分支 fetch 后读取);未来重构须保持。
4. 网络层根因(间歇 SYN 黑洞)未在本任务处理(按范围归属 #34-B/C/D);本修复仅消除暴露放大器 —— 未变更的多分支源在网络事故中将如单分支源一样免疫。
5. 多分支 reset 会改写当前分支指针的既有 quirk 未触碰(文件读取正确性不变量保持)。

## 9. Final Candidate

- **`cf929740fa630e33d8daa408b1e0cd20dda3de99`** @ `origin/worktree-exec/issue34a-multibranch`
- worktree:`.worktrees/issue34a-multibranch`(留存活证)
