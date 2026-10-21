# 使用历史备份的受控恢复流程(G3 恢复入口门禁)

本 runbook 定义把历史备份恢复为可服务实例的**唯一正式路径**。核心不变量:
**恢复出的实例在 `restore_ingress_gate.sh` 判定 ALLOW 之前,Widget/API 入口必须保持
关闭;任何 DENY、失败、超时、身份不符、证据缺失都保持关闭。**

## 正式入口

```bash
# 隔离副本恢复(默认;目标 SID ≠ 生产)
scripts/controlled_restore.sh \
  --pg-container <pg 容器> --dump <backup.dump> \
  --weaviate-url <隔离 weaviate url> \
  --app-service <应用容器名> --app-compose-file <compose 文件> \
  --drop-schema --expect-sid <预期隔离 SID> \
  --health-url <入口 /health> \
  --receipt <持久回执路径>

# DR:恢复到生产集群(显式声明;SID=生产钉值)
#   追加 --target-is-production-dr --expect-sid 7670132346517975075

# 仅在门禁 ALLOW 后开放入口(追加):
#   --start-app-cmd "<环境正确的启动命令>"
```

流程语义(脚本为权威实现):
1. 目标身份核验:目标是生产集群 SID 而未显式 `--target-is-production-dr` → DENY。
2. dump 原件先记录 sha256,只读使用,不写回原路径。
3. 恢复后立即运行 `restore_ingress_gate.sh`:PG 可达性/Weaviate 可达性/期望 SID/
   两注销来源(knowledge-support-cases、knowledge-cb70f5ae)documents+versions+chunks
   严格字面前缀残留=0/Weaviate filesystem 对象=0/无 enabled 未退役注册行/
   `*legacy*` generation 存在。任一失败 → **DENY:主动停止应用容器,退出非零**。
4. `--start-app-cmd` 存在时,启动前**重跑门禁**(防 TOCTOU),仍 ALLOW 才启动,
   随后探测 `/health`,未就绪则回滚关闭。
5. 残留清理是**独立授权程序**(见 source-deletion-orphan-remediation.md 与
   G3 取证工具;不得在本流程内顺带删除),清理后重跑门禁再进入第 4 步。

## 验证矩阵(2026-10-21 于隔离演练栈实测,证据随 G3 包归档)

| 场景 | 结果 |
|---|---|
| 原件直恢复含 481 chunks/179 docs/活跃注册 | DENY(residue-pg+registration),入口容器被 stop,对外端口无监听 |
| 授权清理+核验全零 | ALLOW;`--start-app-cmd` 后 /health 200 |
| 清理中断(仅删部分层) | DENY(residue),入口保持/被置于关闭 |
| PostgreSQL 不可达 | DENY(unreachable-pg) |
| Weaviate 不可达 | DENY(unreachable-weaviate) |
| 目标=生产 SID 且未显式 DR 声明 | DENY(identity-target) |
| 门禁重复运行 | 结果可重复,回执逐条落盘 |
| 其他来源(meta-hailo 等)与 `*legacy*` | 清理前后计数不变;legacy=0 时 DENY(误删防护) |

## 手工旁路清单(诚实披露,当前机制不可控)

1. **绕过流程手工启动应用**:操作者不经本流程直接 `docker start/compose up` 应用容器。
   容器一旦存在即可被手工拉起,本机制只能在门禁 DENY 时主动 stop,无法阻止后续手工
   start。彻底消除需基础设施级约束(如恢复期网络隔离/端口不发布),属独立改造。
2. **绕过流程手工 pg_restore/weaviate 恢复**:不经 `controlled_restore.sh` 直接恢复
   数据层。数据层恢复本身不可被门禁阻止;门禁保护的是"开放服务"这一步。
3. **生产 compose 直接改发布端口**:同 1,属基础设施层旁路。

以上旁路的共同前提是操作者主动绕过正式流程;正式路径内门禁为强制步骤且不可跳过
(脚本实现,非文档约定)。
