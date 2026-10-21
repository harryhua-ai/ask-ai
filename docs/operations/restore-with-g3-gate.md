# 使用历史备份的受控恢复流程(G3 恢复入口门禁)

本 runbook 定义把历史备份恢复为可服务实例的**唯一正式路径**。核心不变量:
**恢复实例在 `controlled_restore.sh stage-open` 判定 ALLOW(健康+真实端口)之前,
Widget/API 入口必须保持关闭;恢复前、任何 DENY、失败、超时、身份不符、中断都保持关闭。**

## 正式入口(分阶段;状态文件=强制屏障)

```bash
# 注意:阶段子命令必须是第一个参数;公共参数跟在其后。
S="--state-file <持久路径> --pg-container <pg容器> --expect-sid <实例SID> \
   --weaviate-url <url> --weaviate-container <wv容器> \
   --weaviate-expect-hostname <CLUSTER_HOSTNAME> --app-service <应用容器名> \
   [--app-compose-file <f>] [--app-compose-service <svc>] [--receipt <f>]"

# 阶段 1:恢复 PostgreSQL(dump 原件只读;入口在 mutation 前强制关闭)
scripts/controlled_restore.sh stage-restore-pg $S \
  --dump <backup.dump> [--drop-schema]

# 阶段 2:恢复 Weaviate(清空数据目录属破坏性操作,需显式确认旗标;
#         --weaviate-data-dir 必须等于该容器 /var/lib/weaviate 的实际挂载源)
scripts/controlled_restore.sh stage-restore-weaviate $S \
  --weaviate-backup <wv.tgz> --weaviate-data-dir </host/path/to/wvdata> \
  --i-know-this-wipes-weaviate-volume

# 阶段 3:恢复已确认归属的 uploads 文件副本(目录须已存在)
scripts/controlled_restore.sh stage-restore-uploads $S \
  --uploads-root </host/path/to/uploads-data-sources> --uploads-src <已确认副本目录>

# 阶段 4:核验并(仅 ALLOW 后)开放入口。
#         stage-open 会先关闭入口;--uploads-root 必须与阶段 3 恢复的目录完全一致
#         (绑定校验,不允许以其他目录充当受检对象)。
scripts/controlled_restore.sh stage-open $S \
  --start-cmd "<启动命令>" --health-url <入口 /health> \
  --uploads-root </host/path/to/uploads-data-sources> \
  --uploads-guard <UNKNOWN.tsv>

scripts/controlled_restore.sh stage-status $S   # 只读观察;不停任何服务
```

门禁(`restore_ingress_gate.sh`,由 stage-open 自动调用,亦可独立运行)逐项核验:
PG/Weaviate 可达与实例身份(SID、CLUSTER_HOSTNAME)、两注销来源
(knowledge-support-cases、knowledge-cb70f5ae)documents/versions/chunks 严格字面前缀
残留=0、两来源专属 generations=0、外部引用=0、无 enabled 未退役注册行、无未终态
reindex 请求、Weaviate filesystem 对象=0、`*legacy*` generation 存在、uploads 目录
内文件全部属于 UNKNOWN 守卫清单(提供守卫时)。**每次探针失败都 DENY,不吞错。**

残留清理是**独立授权程序**(见 source-deletion-orphan-remediation.md;隔离取证工具
不在本仓库交付面),不得在本流程内顺带执行;清理后重跑 stage-open。

## 阶段身份与状态屏障

- 每阶段开始重读存活 `system_identifier` 与 `CLUSTER_HOSTNAME`,与 `--expect-*` 不符即停。
- 每阶段成功才追加状态记录;`stage-open` 要求三阶段记录齐全且 SID/hostname 与状态文件
  一致,并再次与存活实例比对——恢复未完成(缺阶段)时开放请求一律 DENY。
- 目标是生产集群(SID=7670132346517975075)而未显式 `--target-is-production-dr` → DENY。

## 验证矩阵(2026-10-21 于隔离演练栈实测;随 G3 包归档)

| 场景 | 结果 |
|---|---|
| 损坏 dump → pg_restore 失败 | FATAL 退出,状态无 restore-pg,入口关闭 |
| 原件直恢复(179docs/179vers/481chunks/活跃注册) | 门禁 DENY(residue-pg);入口关闭 |
| 仅完成部分阶段即 stage-open | DENY stage-incomplete;入口关闭 |
| 注册/重入探针出错(表不可用) | DENY probe-failed;入口关闭 |
| 期望 SID 不符 | DENY identity-mismatch / ABORT SID 漂移 |
| Weaviate/PG 不可达 | DENY unreachable-* |
| 清理+三阶段齐+门禁 ALLOW | 入口开放,/health 200,docker port 真实发布端口 |
| 开放后 Weaviate 注入 filesystem 对象再门禁 | DENY residue-weaviate;stage-open 重跑关闭入口 |
| --start-cmd 失败 / --health-url 不就绪 | FATAL → 入口关闭 |
| 流程中断(INT/TERM/异常) | trap 强制入口关闭 |
| 门禁重复运行 | 结果可重复,回执逐条追加 |
| meta-hailo 等其他来源与 `*legacy*` | 清理前后计数不变 |

## 手工旁路清单(诚实披露,当前机制不可控)

1. 绕过本流程手工 `docker start/compose up` 应用容器(容器存在即可被手工拉起;
   本机制在 DENY 时主动 stop,但无法阻止后续手工拉起)。
2. 绕过本流程手工 pg_restore/weaviate 数据卷恢复(数据层恢复无法被入口门禁阻止;
   门禁守住的是"开放服务"这一步,且 stage-open 前门禁会暴露任何残留)。
3. 直接修改 compose 发布端口/网络。

以上均需操作者主动绕开正式流程;正式路径内门禁为脚本强制,非文档约定。
彻底消除需基础设施级约束(恢复期网络隔离/端口不发布),属独立改造。
