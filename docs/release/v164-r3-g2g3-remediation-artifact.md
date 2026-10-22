# v1.6.4-r3 G2/G3 整改证据工件(evidence artifact)

用途:`PREFLIGHT_REMEDIATION_EVIDENCE_ARTIFACT_B64` 通道的实际证据工件;
评估器对文件字节计算 SHA256 并与记录 `evidence_digest` 精确比对(双因子之
一)。本文件为纯文本、非秘密、不含客户内容;签发后字节不可变(任何改动
即 digest 失配 fail-closed)。

- recorded_at: 2026-10-22T04:00:00Z
- recorded_by: agent-b (B 采集与执行;A 终审)
- gate: upload-source-acl-verified-issue-121
- release: v1.6.4-r3(部署前 A 将 target_tag/release_sha 绑入审批记录)

## 1. 证据包(宿主归档 ~/ask-ai-backups/,SHA256 独立回算)

| 包 | SHA256 | 内容 |
|---|---|---|
| r3-upload-cleanup-apply-prep5-20261021.zip | `e61baa0cf3c030d0cd608e2ac0360e0f74d001f9d2e8b79b04da6217b82f54eb` | Batch 2/3 清理程序冻结件(7/7) |
| r3-batch3-final-review-20261021.zip | `53153ddb48a452d6ea643eed4ed1727ebac834f385d01957f7b68ac6f936cbc2` | A 终审前复核记录 |
| r3-batch3-execution-evidence-20261021.zip | `3c3c90e21a50924433ccd744649c3323a4eff5cd6e89437798b84a2ae2b99039` | Batch 3 生产执行回执(5/5) |
| r3-g3-filesystem-cleanup-evidence-20261021.zip | `10d2305afa7ecea3f81c4f2bae3ea381958f6d3f808fd6e65d88713d95400245` | G3 隔离副本清理+恢复双分支(8/8) |
| r3-g3-ingress-gate-enforcement-20261021.zip | `b310f798025defcf403218e755c3778297f8da575fc30033dcf8bf639a5fca7b` | G3 门禁强制接线候选(6/6) |

## 2. 上传源退出生产(三批清零,冻结计数零偏差)

- Batch 1 宿主 knowledge-support 181 文件删除(逐文件哈希 181-181;after=0;
  7 子目录保留);Batch 2 uploads 卷 520 文件删除(执行日志
  `86b39dc6573c028d8f92e3f32176133cd266f6c750f3b2dfb2aba2fca7901531`,回执
  `5e90063082edf3f0e3fc4eb52617547db99d9fefffb021a3ed77fdb4aa5edcd3`;剩余
  =10 UNKNOWN 守卫,哈希逐项一致);Batch 3 PG ksc 439/1,598/2 + kc
  247/1,097/1(脚本冻结字节
  `d590a1921f47c1dfe2faca352d8dfc53dbde490bca35bbb03f56cf4f1bade54a`,回滚点
  `6fee38e5f4fa2480e99a8784e18c546773edf433839b9150f1887e66f05e1464`;ksc 日志
  `afa3d673…`/kc 日志 `e68e096f…`,验收 `f32f4ff8…`)。
- 清零后验收:PG 两来源 docs/versions/chunks/gens 全零、注册=0、非终态
  sync_requests=0、`*legacy*`=1、其他来源基线不变;Weaviate filesystem=0;
  `/health` ok、restarts=0。

## 3. G3 恢复门禁(强制恢复路径)

- 候选:PR #187,分支 candidate/g3-restore-ingress-gate-20261021,
  代码提交 `1e7414db`(基线 origin/main `057dd1d3`);官方 Linux CI
  run 39720412200(见 PR 评论;代码提交级 success 后并入最终 HEAD)。
- 测试:tests/scripts/test_g3_restore_gate.py 11 用例(真实 postgres:16
  + weaviate 1.28.0 docker fixture;缺失参数/不可达/身份不符/探针失败/两源
  残留/专属 generations/外部引用/注册/reindex/WV filesystem/legacy 缺失/
  uploads 守卫/pg_restore 失败/attempt 重放/数据目录绑定/启动失败关闭/
  完整生命周期开放/stage-status 只读),本地 11/11 + CI。
- 语义:恢复演练实证脏实例 DENY_INGRESS → 清理 → ALLOW_INGRESS 双分支;
  端点绑定(--weaviate-url 属于 --weaviate-container)、uploads root 与
  实际恢复目录绑定、stage-open 先关入口再裁决。

## 4. G2 锚与漂移(细节见 v164-r3-g2-anchor-drift-analysis.md)

- 2026-10-22T02:48:51Z 单窗口四锚实测一致:SID `7670132346517975075` /
  CLUSTER_HOSTNAME `7adc06acc397` / image `sha256:b06b9711…` / 卷
  `tesla-t4_weaviate_data`;R5 官方扫描器 `eb8d940b…`/637。
- 卷清单为活性指纹(R5 后 277 个 LSM 段文件自然写入);固定锚须停写窗口
  双扫描一致后采集(A 职权)。

## 5. 部署通道与迁移(R4 核验)

- production Environment 存在;`PROD_DEPLOY_SSH_KEY`+`PROD_SSH_*` 三变量在;
  缺(待 A 写):`PREFLIGHT_TRUST_ANCHOR_B64`、`PREFLIGHT_REMEDIATION_EVIDENCE_B64`、
  `PREFLIGHT_REMEDIATION_EVIDENCE_ARTIFACT_B64`、`PREFLIGHT_REMEDIATION_APPROVAL_PUBKEY_B64`。
- 迁移:ledger 16 条;生产(r2 预态)仅 delta 2 条(sales_leads 纯加列,
  catalog 探测幂等 no-op);contaminated-chunks 预态 residual=0 ⇒ 重跑 no-op。
- 备份可恢复性:G3 隔离演练实证原备份重放可复现全部已删内容(179/481/179
  +注册)且门禁 DENY 拦截;Batch 3 三表回滚点 `6fee38e5…` 在案。
