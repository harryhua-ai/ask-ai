# 执行交接:sync-consistency worktree 梳理与收尾

> **给执行窗口**:2026-08-30 由产品规划窗口检查工程后定稿。执行端按本交接梳理并回报,**合并 main 的动作需待产品窗口审查 diff 后放行**。本文件为本地文档(项目文档策略:仅本地,不进 git),执行端用绝对路径读取。

## 背景(检查结论,2026-08-30)

### 发现 1:`worktree-sync-consistency` 分支有 8 个未合 commits(第二轮增强)

位置 `/.claude/worktrees/sync-consistency`,基点 `e6374b9`(文档级一致性自愈合入点),分支内容:

| Commit | 内容 | 性质 |
|---|---|---|
| `e226bab` | 一致性校验升级 **chunk 级差集 + 重灌清单** | 增强(解决原 spec"已知局限 1:部分写入盲区") |
| `f1160e9` | 自愈分支消费 `refill_source_ids`,部分 chunk 丢失自动重灌 | 增强 |
| `8cb8008` | **清理陈旧 chunk 与同 source_id 旧版本行(一致性漂移根因)** | 根因修复 |
| `48b37e4` | 删未使用导入 | 审查清理 |
| `6094545` → `61322cc` → `d2efc7f` | weaviate v4 SDK API 兼容修复链(fetch_objects 游标 → iterator filters 崩溃 → cursor/where 互斥 → iterator 全扫+客户端前缀过滤 → Filter API 正确引用) | 修复链,`d2efc7f`(08-28 20:18)为终点 |
| `5d6d0b3` | ExclusionPolicy 排除 macOS `._*` 元数据文件 | 小修 |

净代码差异(排除 docs):8 文件 +583/-113,核心 `vector_consistency.py` / `ingest.py` / `sync.py` + 3 个测试文件。

### 发现 2:main 已分叉,rebase 有冲突预期

- main 历史已重写;`4651ca8` 把文档全部转为仅本地(GitHub 只留代码)——**分支带的 docs 改动在 rebase 时应丢弃,不带回 git**
- `f24e2e7`(08-28 17:27)是分支修复链某版的重做(精确级 iterator 全扫+客户端前缀过滤),**分支 `d2efc7f`(20:18)比它晚且含 Filter API 修复,语义上更完整**——冲突时以分支版语义为准,人工比对

### 发现 3:主工作区有 admin channel 任务未提交改动

`admin/src/components/LoginChat.tsx`、`backend/api/schemas.py`、`widget/src/App.tsx`、`widget/src/types.ts`(M)+ `tests/api/test_admin_channel.py`(新增)——即 2026-08-28 交接(环境策略 + admin channel)的 Task 1/2 产物,未提交(疑被 mimosa 拦截,它拦截 tests 里的假 key 模式)。

### 发现 4:两个废弃 agent worktree 可清理

`worktree-agent-a07536ba48596bb0f` / `worktree-agent-a0e143d2707d90701`(08-11 遗留),HEAD `48b2583` **已验证包含于 main 历史**(零丢失,可清理);`feat/github-unify` 老分支同样先验证后清。

## 任务

### Task 1:梳理分支(先读后动)
逐 commit 读 diff,输出梳理报告:每个 commit 的语义、与 main `f24e2e7` 的重叠/演化关系、`d2efc7f` 相对 `f24e2e7` 的增量。

### Task 2:rebase 到 main
- 在现有 worktree 内 `git rebase main`(分支基点 `e6374b9` 在 main 祖先链内,可干净起步)
- 预期冲突:`backend/services/vector_consistency.py`(main `f24e2e7` vs 分支修复链)——以 `d2efc7f` 语义为准合并
- docs 侧差异一律丢弃(文档仅本地策略),本地文件保留在主工作区即可

### Task 3:全量测试
`TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test uv run pytest tests/ -q`(红线:不设会清开发库)。重点 `tests/services/test_vector_consistency.py`、`tests/pipeline/test_ingest.py`、`tests/scripts/test_sync_gap_heal.py`。

### Task 4:处理主工作区 admin channel 未提交改动(在主工作区做,worktree 看不到 untracked)
- 审查 diff 是否完整实现 channel="admin"(对照 2026-08-28 交接的 Task 1/2 验收)
- 完整则提交;注意 mimosa pre-commit 会拦截 tests 假 key(`sk-*` 模式),先把测试里的假 key 改为无 `sk-` 前缀占位符(如 `test-key-123`)再提交
- 不完整则补完再提交

### Task 5:清理废弃 worktree 与老分支(先验证零丢失)
```bash
git -C /Users/harryhua/Documents/GitHub/ask-ai merge-base --is-ancestor 48b2583 main   # 已验证过,再做一次确认
git worktree remove .claude/worktrees/agent-a07536ba48596bb0f
git worktree remove .claude/worktrees/agent-a0e143d2707d90701
git branch -D worktree-agent-a07536ba48596bb0f worktree-agent-a0e143d2707d90701
# feat/github-unify:先 merge-base --is-ancestor 验证包含于 main,是则同样删除
```

### Task 6:回报(不合 main)
梳理报告写入本文件"执行结果"节:rebase 后 commit 列表、测试结果、admin channel 提交 SHA、清理清单、roadmap 对应确认(见下)。**合并 main 待产品窗口审查 diff 后放行**;部署验收(D-11)在合并后另行安排。

## roadmap 对应(产品窗口判定,执行端在报告中确认覆盖度)

本分支 = **基线 §6.3-A1(sync-consistency)的第二轮增强**:文档级 → chunk 级一致性 + 漂移根因清理。收尾后 A1 的剩余动作 = 合并 + 部署 T4 + admin"同步全部"实测(D-11)。它同时支撑 D-9(接入健康归数据源页)的数据真实性。

## 约束(红线)

1. 绝不 `--reindex` 或任何删 Weaviate collection 的操作;本任务不触发同步、不部署
2. 测试必设 `TEST_DATABASE_URL`
3. 文档仅本地:不把 docs/ 带回 git
4. ruff/black/isort(line-length=100);中文注释与提交信息
5. rebase 主线若改写失败可 `git rebase --abort` 回退,分支原样无损失

## 执行结果(执行窗口回填,产品窗口按此审查)

> 汇报原则:**给证据,不给结论性形容词**。"全绿""没问题"不算汇报,要贴真实命令输出摘要。审查窗口将抽查 diff 后决定放行合并/打回/有条件通过。

### 1. 分支梳理(Task 1)
- commit 对照表,每行:`SHA | 语义一句话 | 与 main f24e2e7 的关系(重复/演化/独有)`
- `d2efc7f` 相对 `f24e2e7` 的净增量:一句话 + 关键代码位置

**执行前提核实(与交接表不同,先说清)**:执行时 `merge-base main worktree-sync-consistency = f24e2e7`,即分支已被先前窗口 rebase 过一次,交接表 8 commits 与现分支 5 commits 对应如下;`git log -S refill_source_ids main` 显示 chunk 级差集/重灌清单已随 main `f24e2e7` 落地(vector_consistency.py 现文即含"精确级:chunk 级差集")。

| 交接表旧 SHA | 现分支 SHA | 语义 | 与 f24e2e7 关系 |
|---|---|---|---|
| `e226bab`(chunk 级差集+重灌清单) | 无对应 | 校验器升级 | **已并入 main**(f24e2e7 内含) |
| `f1160e9`(自愈消费 refill) | `a0f1e91` | sync 缺口分支改按 refill_source_ids 过滤重灌 | 独有(main 无此消费逻辑) |
| `8cb8008`(清理陈旧 chunk+幽灵行) | `08cd2c3` | 漂移根因修复(ingest) | 独有 |
| `48b37e4`(F401) | `5689103` | 删未用导入 | 独有(随 08cd2c3 配套) |
| `6094545→61322cc`(修复链前段) | 无对应 | v4 cursor/where 修复 | **被 main f24e2e7 覆盖**(标题即"精确级改 iterator 全扫") |
| `d2efc7f`(Filter API 终点,08-28 20:18) | `a65a686` | 修 `collection.filter` 属性不存在 | 独有(净增量见下) |
| `5d6d0b3`(ExclusionPolicy) | `5259902` | 排除 macOS `._*` | 独有 |

**`d2efc7f` 净增量** = `a65a686`:_prune_stale_chunks 与 delete_document 两处 `self._collection.filter.by_property(...)` 改为 `weaviate.classes.query.Filter.by_property(...)`(v4.22 Collection 无 .filter 属性;原写法使 **prune 在生产全部静默失效**,提交说明原话"陈旧 chunk 未被清理")。位置:backend/pipeline/ingest.py 两处 delete_many 的 where 构造。

### 2. rebase(Task 2)
- rebase 后 `git log --oneline main..<branch>` 输出
- 冲突解决逐条:`文件 | 冲突内容 | 采用哪边 | 理由`
- 验证:`git diff main...<branch> --stat` 输出**不含 docs/**(文档仅本地策略)
- **重点必答**:`8cb8008`(清理陈旧 chunk)的删除条件是什么——什么情况下删、怎么保证不误删(这是删向量的操作,审查最高优先级)

```
$ git rebase main        # worktree 内执行
Rebasing (1/5)...(5/5)
Successfully rebased and updated refs/heads/worktree-sync-consistency.

$ git log --oneline main..worktree-sync-consistency
e7e175e fix(ingest): Filter API 用 weaviate.classes.query.Filter,修 collection.filter 属性不存在
aa41ae2 fix(connectors): ExclusionPolicy 排除 macOS ._* 元数据文件(任意层级)
0ff1a72 chore(ingest): 删除 _prune_stale_chunks 未使用的 Filter 导入(审查 F401)
be7a065 feat(ingest): 清理陈旧 chunk 与同 source_id 旧版本行,修一致性漂移根因
02dd385 feat(sync): 自愈分支消费 refill_source_ids,部分 chunk 丢失自动重灌
```

- 冲突:**零冲突**(main 在 f24e2e7 后仅 4651ca8/81bd1db/be93264,均不碰分支 6 文件;交接预期的 vector_consistency.py 冲突在先前 rebase 已消化)
- docs 检查:`git diff main...branch --name-only | grep -c '^docs/'` → `0`

**必答:be7a065(原 8cb8008)的删除条件与误删防护**

Weaviate 侧 `_prune_stale_chunks`(ingest.py):
- **触发前提**:该文档本轮**全部 chunk 写成功**(`success_count == len(chunks)`)才执行;部分失败不 prune,留待下轮(per-doc 与跨 doc 两条写入路径同款守卫)
- **删除条件**(两条件 AND,delete_many 单次):`source_id == 本文档 source_id` **且** `chunk_index >= 本次写入 chunk 数`
- **误删防护四层**:① source_id 精确等值 → 不可能碰到他文档;② `chunk_index >= N` 下界 → 本次有效 chunk(0..N-1)不可达;③ 全成守卫 → 写入状态未知(有失败)时不动向量;④ 删除失败仅 warning 不抛(最坏结果=残留照旧,校验器继续报不一致,不会多删)
- 删除对象只是"内容缩短后范围外的确定性 UUID 残留"(写入用 `uuid5(source_id, chunk_index)`,新批次永不触碰超范围旧对象——这正是漂移根因)

Postgres 侧 `_upsert_postgres` 幽灵行清理:
- 仅当**新 (content_hash, branch) 无匹配行**(内容变更)时,删除 `source_id == 本文档 且 content_hash != 新 hash` 的旧行后插入新行
- 分支安全:source_id 含分支路径(如 `r/main/f.py` vs `r/feat/f.py`),跨分支同内容行 source_id 不同,不受影响(tests/db/test_documents_pk.py 复合 PK 语义)

### 3. 测试(Task 3)
- 命令 + 真实输出末行(`N passed, M skipped, K failed` 原样贴)
- `tests/services/test_vector_consistency.py` / `tests/pipeline/test_ingest.py` / `tests/scripts/test_sync_gap_heal.py` 各自结果
- 失败/跳过逐条:原因与处置

```
$ TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test \
  uv run pytest tests/ -q --ignore=tests/embedder --ignore=tests/e2e   # worktree 内
499 passed, 3 skipped, 14 warnings in 30.90s   # EXIT=0
```

重点文件(单独跑):`50 passed, 3 warnings in 0.62s`(test_vector_consistency + test_ingest + test_sync_gap_heal + test_exclusion 四文件合计)
- `test_vector_consistency.py`:9 passed(含 test_verify_detects_partial_chunk_loss / test_refill_unions_missing_and_chunk_mismatch_sorted)
- `test_ingest.py`:passed(含新增 5 个 prune/幽灵行测试,见 §7)
- `test_sync_gap_heal.py`:passed(含 test_partial_chunk_loss_refills_via_refill_source_ids)

排除说明(与上轮执行一致):embedder 首次跑需下载 BGE 模型,本机沙箱无外网会挂起(xet 锁活跃但缓存零增长实测);e2e 需活服务。两者 CI 同跳过,与本分支改动无交集。3 skipped 为既有跳过项,非本分支引入。

格式(红线 4):black `6 files would be left unchanged` 全过;ruff 报 12 处但**与 main 完全同集合**(10 I001 + 1 BLE001 + 1 SIM103,`diff /tmp/ruff-main.txt /tmp/ruff-branch.txt` 为空),分支零新增;isort 的 test_ingest.py 提示属同批 main 既有。是否顺手修 main 既有项,请裁决(默认不扩 diff)。

### 4. admin channel 收编(Task 4)
- 核查结论:admin 内嵌聊天原 channel 值 = `widget`(LoginChat 复用 widget App,App.tsx 硬编码)
- 改动摘要 + commit SHA:**上一轮已完成并经产品窗口审查通过** —— `81bd1db`(白名单+Config 透传+LoginChat 传 admin+3 测试,详见 2026-08-28 交接执行结果节)
- 假 key 修复清单:**无需**——上轮测试文件未使用任何 `sk-*` 模式 key,mimosa 直接放行(证据:81bd1db 正常落库)
- mimosa 扫描:通过

### 5. 清理(Task 5)
- 删除清单 + 每项零丢失验证命令的输出
- 清理后 `git worktree list` / `git branch` 输出

```
$ git merge-base --is-ancestor 48b2583 main && echo 零丢失
48b2583 是 main 祖先,零丢失
```

两个 agent worktree 与分支:**执行时已不存在**(git worktree list 仅剩 main + sync-consistency;`git branch -d worktree-agent-*` 报 not found)——已被先前窗口清理,本轮复核确认无残留。

`feat/github-unify`:**未删,验证不通过** —— `git merge-base --is-ancestor feat/github-unify main` 失败;`git cherry main feat/github-unify` = 5 个补丁等价 + **1 个非等价 `768e1f4`**(refactor(local_git): 移除 @register)。语义核查:main 的 local_git.py docstring 已是"实现细节,不再 @register"(核心语义已落地),但 main 的 sync.py:54 仍残留 `import backend.connectors.local_git  # 触发 @register 装饰器` 过时注释。删否请裁决(保留零成本)。

另发现 `backup/sync-consistency-pre-rebase` 分支(pre-rebase tip `d2efc7f`),为先前 rebase 的备份,本轮保留未动。

### 6. 待产品窗口决策
- 合并放行申请:附 `git diff main...<branch> --stat` 全量输出
- 意外发现 / 遗留风险:逐条(没有写"无")

**⚠️ 意外发现 1(改变"合并放行"的性质,最高优先)**:origin/main **已含本分支全部内容**。远端多出 3 commits(作者 Harry-Milesight,08-28 当天,注明"补齐迭代 2 漏推"):

```
503435a fix(ingest): Filter API 用 weaviate.classes.query.Filter...
a044967 fix(connectors): ExclusionPolicy 排除 macOS ._* ...
b7e3ebb feat(sync): 自愈消费 refill 清单 + ingest 清理陈旧 chunk 与幽灵行...
```

树级等价证据:`git diff e7e175e(origin/main 版分支内容) origin/main -- <分支 6 文件>` **输出为空**。即:远端早已合并推送,本地分支链是等价平行链(SHA 不同、内容相同)。**"合并放行"实际剩下的是本地收敛决策**,方向二选一:
- A(推荐):本地 main rebase 到 origin/main(重放 81bd1db+be93264,与远端 3 commits 零文件交集,预计零冲突),然后退役本地 worktree-sync-consistency 分支/worktree 与 backup 备份分支
- B:忽略远端,以本地链合并推送(会与远端分叉,不推荐)
执行窗口未擅自收敛 main,等放行。

合并/收敛后 `git diff main...worktree-sync-consistency --stat`(6 文件 +376/-80)将归零,无需再审该 diff;审查建议改为抽查 origin/main `b7e3ebb..503435a` 三个提交。

**意外发现 2**:Task 0(新增修正项)已完成:`be93264` —— AskRequest.message docstring "1~2000"→"1~8000"。道溯:8cc2230 初版两处一致(2000);d73c997(07-29)提交说明明确"放宽输入限制:message 8000 字符",只改 Field 漏改 docstring → 放宽是有意行为,统一到 8000。CLAUDE.md 全文无 message 长度表述(搜 2000/8000 仅命中 localhost:8000 端口),第三处不一致不存在,无需改。

**遗留风险**:
- 本地 main 与 origin/main 分叉中(ahead 2 / behind 3),收敛前任何人从旧 clone 推送都会踩乱
- ruff 12 处 main 既有违规未修(分支零新增)
- 本地 worktree-sync-consistency(worktree+分支)与 backup/sync-consistency-pre-rebase 暂保留,收敛后可清

### 7. roadmap 覆盖确认
- chunk 级校验是否覆盖原 spec"已知局限 1(部分写入盲区)":是/否 + 证明它的测试名

**是**。链路三层证据:
1. 检测:`tests/services/test_vector_consistency.py::test_verify_detects_partial_chunk_loss`——doc 在 Weaviate 但 index 集合 {0,1} vs pg chunk_count=4(整篇差集为空的部分丢失)被识别进 refill 清单;`test_refill_unions_missing_and_chunk_mismatch_sorted` 锁定 refill = 整篇缺失 ∪ chunk 集合不一致
2. 自愈:`tests/scripts/test_sync_gap_heal.py::test_partial_chunk_loss_refills_via_refill_source_ids`——missing 空、refill 非空时按清单重灌并记 partial(原 spec 盲区正是"partial 丢失未自动补齐,需人工核查")
3. 根因:`tests/pipeline/test_ingest.py::test_prune_stale_chunks_calls_delete_many_with_chunk_filter` / `test_ingest_document_prunes_stale_chunks_when_fully_written` / `test_ingest_document_skips_prune_when_partial_failure` / `test_prune_failure_does_not_break_ingest` / `test_upsert_postgres_deletes_old_hash_rows_for_same_source_id`——多余 chunk 清理与幽灵行根因消除(部分失败不误删有专测)

### 8. 收敛执行记录(2026-08-30,产品窗口放行方案 A 后)

- rebase:`git rebase origin/main` 零冲突重放 2/2;新 SHA:`81bd1db → c8117f4`(admin channel)、`be93264 → 88a4c9f`(docstring 对齐)
- 零丢失终验:`git diff e7e175e HEAD --stat` 输出 0 行(pre-rebase 分支 tip 与收敛后 main 树完全一致)
- push:`503435a..88a4c9f main -> main` 成功;CI 触发:Build & Push GPU Image run 33304279579(https://github.com/harryhua-ai/ask-ai/actions/runs/33304279579)
- 退役:worktree-sync-consistency(e7e175e)、feat/github-unify(67e6911)本地+远端均已删;worktree 目录已移除(仅 .mimosa/.venv 工具产物,工作产物经树级 diff 证明零丢失)
- 保留:backup/sync-consistency-pre-rebase(D-11 部署验收后清理)
- 剩余动作 = roadmap §6.3-A1 收尾:D-11 部署 T4 + admin"同步全部"实测(部署另行安排,本窗口未触发)

### 9. D-11 部署验收记录(2026-08-30 执行,产品窗口按此审查)

**部署与版本**:
- 前置:磁盘 `/dev/vda2 1.3T 276G 952G(23%)` 余量 77%(红线 20%,通过);CI 33304279579 success
- `update.sh` 成功;健康检查首验失败为 BGE-m3 GPU 模型加载慢(45s 后 `{"status":"ok"}`),非故障
- 运行版本实锤(容器内直查):`schemas.py:18` 含 `1~8000`(88a4c9f)、`:30` 白名单含 `admin`(c8117f4)
- 注意:部署前 T4 旧镜像(08-28 20:28 创建)已含分支 sync 代码(503435a),故本次部署 sync 逻辑零增量,增量=admin channel+docstring

**两轮"同步全部" SyncLog 对照**(首轮 09:46 / 二轮 10:01,逐源逐字节一致):

| 源 | 两轮状态 | 关键计数 |
|---|---|---|
| aitoolstack / meta-hailo / ne503-aipc / ne503-apic / woocommerce | success ×2 | unchanged 37/27/0/0/40 |
| knowledge-support-cases | partial ×2 → **清理后单源同步 success** | 481/486 → 481/481 |
| ne503-sdk-local | partial ×2 | 需重灌 2 篇,items_updated=0(见根因③) |
| 其余 8 源(lowpower/ne301/neomind×5/wiki/dashboard) | partial ×2 | actual>expected、refill 空、orphan 2~523 |

自愈循环幂等稳定(success 不退化);10 个 partial 全部为数据侧残留,与代码无关。

**幽灵行清理(已裁决,精确点名)**:
- 盘点:pg `._*` 行仅 knowledge-support-cases 1 源 5 行 5 chunks(全 `._*.md` macOS 元数据,排除规则生效前灌入);Weaviate 侧迭代器全量核验 481 对象全部合规、幽灵对象 **0 个**
- 执行:`DELETE FROM documents WHERE source_id ~ '(^|/)\._'` → **DELETE 5**(before 5/5 → after 0/0,SQL 事务内留证)
- 效果:单源同步立即 **partial → success**(481/481,items_unchanged=179)
- 教训:Weaviate like/Equal 在 TEXT 属性按分词匹配,`*/._*` 误中全库 12.9 万对象——点名删除/盘点必须用迭代器口径或确定性 UUID,不可用过滤器

**ne503-sdk 残留根因(报告残留项,已钉死)**:
- 2 篇不一致:`python/hailo_ipc_sdk/inference.py`(pg=21,wv=[0..24],多余 5)+ `proto/camera_pb2.py`(pg=21,wv=[0..18],缺失 2)
- 13 篇孤儿(pg 无 wv 有:app/audio/config/device/events/plugin/proto×7)= orphan=13 实体;增量同步从不处理"源里消失的文档"(功能盲区)
- **为何 refill 无效**:`refill_set ∩ fetch_all = []` ——repo 已把包改名 `hailo_ipc_sdk → neoruntime_ipc_sdk`,pg/refill 还是旧路径;增量窗口(`fetch_changes(since)`)滑过了 rename → 永久 partial
- 修复选项(产品侧决策):A. 重置该源 `_last_success_at` 标记让窗口覆盖 rename,下次同步正常增量更新+prune 清多余(孤儿仍需策略);B. 孤儿 13 篇按"孤儿人工评估"逐源决策;无代码改动即可完成 A+B

**prune 生产首跑情况**:两轮+单源同步均零重灌(items_updated 全 0),prune 未被触发——其生产行为仍以测试证据为准(5 个 prune 专测),首次真实触发要等 ne503-sdk 走选项 A 重灌时观察

**⚠️ P1 新发现(本次验收最高优先产出)**:
admin 内嵌聊天(channel=admin 已部署生效,conversations 落库 3 条 channel=admin 实证)在检索层被 **channel_visibility 过滤排除**——所有源 config 未配 vis → 默认 `(widget,api)`,search.py `contains_any(["admin"])` 零命中。A/B 实证:同问题 widget 渠道正常出 sources+回答,admin 渠道拒答。**当前生产 admin 内嵌聊天检索不可用**。修复选项:(a) 数据侧为各源 channel_visibility 加 admin(可 UI 操作);(b) 代码侧改默认值(需产品窗口安排)。数据边界功能本身符合设计,是白名单配置缺位。

**产出小结**:knowledge 由幽灵行清理转绿(10→9 partial);P1 发现 1 项;ne503-sdk 根因钉死待决策;磁盘稳定 952G;红线全程遵守(未 --reindex,删除仅 `._*` 精确点名,未动 backup 分支,未改代码)
