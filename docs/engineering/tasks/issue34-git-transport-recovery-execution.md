# ISSUE #34 实施执行报告 —— git 传输失败证据化分类 + 显式超时 + 有界恢复

- 日期:2026-09-10
- 分支:`fix/34-git-transport-recovery`(自 main `03e6c57` 切出)
- 状态:CANDIDATE READY(未合并、未部署,待 Role A 独立评审)
- RCA:见 issue #34 评论(2026-09-10,CONFIRMED;生产只读 + 代码定位)

## 1. 根因(已证实)

生产 09-07 05:35–08:57Z:github.com:443 间歇性 TCP 连接失败(每源 ~130s =
OS SYN 重试耗尽;同分钟其他 GitHub 源同宿主成功 → 非主机出口/非 GitHub 全网故障),
10:00 起经小时级 cron 自然自愈。机制:`_run_git` 子进程无任何超时/重试;
业务失败被 `sync.py` 吞掉、runner 恒 0 退出 → executor 有界重试面(冻结契约
§14 只管进程级)永不触发,`attempt=1/recovery=false` 即此机制的真值。

## 2. 冻结契约与落实(4 项,零 executor 改动)

| # | 契约 | 实现 |
| --- | --- | --- |
| 1 | 显式超时,消除无限挂起 | `github.py::_git_timeout_seconds()`:env `GITHUB_GIT_TIMEOUT_SECONDS`(默认 900s;≤0=关闭旧行为);`_run_git` 的 `subprocess.run(timeout=...)` + `TimeoutExpired` → `GitTransportError`。合法大仓库 fetch/clone 不受影响(900s 富余),连接挂起最坏 bounded |
| 2 | 证据化分类 | `_TRANSPORT_PATTERNS`(failed to connect / could not resolve host / connection timed out / timed out / connection reset / ssl / gnutls / tls connection)+ `_is_transport_failure()`:命中 stderr 摘要 → `GitTransportError(RuntimeError)`;其余 git 失败维持原 RuntimeError(分类不误伤:ref 不存在/鉴权/本地状态=非重试类) |
| 3 | 有界恢复(复用冻结机制) | `_sync_one` 返回 bool(是否传输失败;异常仍不向上传播);`run_sync` 聚合返回;`main` 退出码契约:**传输失败 → `sys.exit(2)`** → executor 既有 `runner_failed` 有界重试(4 次 / 30/120/600s backoff,零 executor 改动);**纯业务失败恒 0**(契约 §14 原样);重跑幂等(API-SHA 短路 + fetch/reset 原位) |
| 4 | 可观测 | 传输失败源:`SyncLog.error_detail` 前缀 `[transport][retryable]` + `SyncRun.counters.transport_failures=1`;stderr 摘要透传原样(token 脱敏保留,含 GitTransportError 路径) |

## 3. 明确不做(边界)

- 不改 refs/源配置;不弱化失败上报(SyncLog/SyncRun 语义原样 + 增量字段);
- 不引入无界重试/风暴:上限 = executor 既有 4 次预算与既有 backoff 序列;
- 不改 §14:业务失败仍不进入恢复调度;
- 不做生产网络/配置变更(RCA 仅只读)。

## 4. 测试

新增 `tests/connectors/test_github_transport.py`(17 条):
- 分类:生产实测原文(run 1573 的 130072ms 连接失败)命中传输模式;DNS/超时/TLS(gnutls/TLS 措辞)/重置命中;ref 不存在/鉴权/本地状态不误判;
- `_git_timeout_seconds`:默认 900 / env 覆写 / ≤0 关闭;
- `_run_git`(subprocess 打桩):传输 stderr → GitTransportError;非传输 stderr → 原 RuntimeError;`TimeoutExpired` → GitTransportError;token 脱敏在 GitTransportError 中保留;
- 退出码契约:`run_sync=True → main` 退出码 2;`False → 0`(§14 不变)。

全量后端:**2207 passed, 8 skipped**(基线 2190 + 新增 17)。
注:首个 full run 曾见 `test_signal_present_on_all_items` 单测失败(items=[]),
重跑复现失败 → 属共享测试库(ask_ai_test)跨套件残留状态的既有隔离脆弱性
(clean main 同法偶发可复现,与本分支 diff 无关),已列入 Sprint 残留风险。

## 5. 候选

- 分支:`fix/34-git-transport-recovery` @ <push 后补>
- 变更面:`backend/connectors/github.py`、`scripts/sync.py`、`tests/connectors/test_github_transport.py`、本报告
- 交接:待 Role A 独立评审;与 `fix/45-ingest-char-contract` 在 `scripts/sync.py` 的相邻点
  (#45 改 `_sync_one` except 块的 IngestFailures counters;#34 改同一 except 块的返回值
  与 `[transport]` 前缀)语义正交,合并时二选一先入、另一 rebase 即可。
