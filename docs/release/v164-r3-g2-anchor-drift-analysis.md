# v1.6.4-r3｜G2 卷清单锚漂移语义分析 + 停写窗口固定方案(Role B,2026-10-22)

任务来源:A「最终发布阻塞清除任务」R2。全部数据来自生产只读探针,零写操作。

## 1. 结论

`weaviate_volume_manifest_sha256` 是**活性指纹,不是稳定锚**:活跃同步持续向
weaviate 卷写入 LSM 段文件(新对象 flush 与 LSM compaction),清单哈希必然随时间
漂移。固定锚必须配一个**停写窗口**(A 授权),在窗口内以"双扫描一致"证明冻结后
采集,并在同窗口内完成部署预检。

## 2. 漂移实证

| 时点(UTC) | 采集方 | FILES | MANIFEST_SHA256 |
|---|---|---|---|
| 2026-10-21T02:46Z(R5 时点) | B(只读扫描) | 581 | `61675d79a2f17e37984ebccdc5424f2c5004c6eec22d472d4a71c99da9dbdcb5` |
| 2026-10-22T02:48:51Z | B(终验单窗口) | 637 | `eb8d940b17a31e6c81b0992dc1108ad4d8fb1c969efed54dddde3b2d8ce30c4c` |
| 2026-10-22T04:00Z 前后(元数据枚举) | B(只读枚举) | 637 | (逐文件清单见证据日志,计数与上一致) |

对 2026-10-22 只读元数据枚举(637 文件,`<路径>|<大小>|<mtime>`)按 mtime 分桶:

- **R5 时点(2026-10-21T02:46Z)之后新写入:277 个文件,全部位于
  `document/<shard>/lsm/...`**(weaviate LSM 段:.db 97 / .bloom 103 / .wal 71 等);
  最新写入 2026-10-21T20:31Z(活跃源同步轮触发的 flush/compaction)。
- R5 前 7 天内:167 个;更早:193 个(含 2026-08-04 建库期文件)。

⇒ 漂移来源 = 活跃摄取(weaviate 正常工作),非异常写入、非数据丢失;
两时点间 Weaviate 对象分布(github 540,098 / web_crawl 529 / woo 318 /
filesystem 0)无 filesystem 类变化,残留清零状态未被漂移破坏。

## 3. 停写窗口固定方案(交 A 执行;B 无授权动作)

锚的其余字段(`pg_system_id`/`weaviate_cluster_hostname`/`weaviate_image_digest`/
`weaviate_volume_name`)不随时间漂移(2026-10-22 已四锚实核一致);唯一时间敏感
字段是 `weaviate_volume_manifest_sha256`。固定程序(A 职权,建议与部署同窗口):

1. **授权停写**:stop 生产 `tesla-t4-sync-cron-1` 与 `tesla-t4-sync-executor-1`
   (与 Batch 3 清理同款维护窗口语义;生产 /ask 不受影响,仅暂停后台摄取)。
2. **冻结证明**:窗口内用 R5 官方扫描脚本
   (`scripts/weaviate_volume_manifest_scan.sh`,stdin `sh -s /var/lib/weaviate`
   送入 weaviate 容器)连续扫描两次,间隔 ≥10 分钟;两次 `MANIFEST_SHA256` 与
   `FILES` 完全一致 ⇒ 冻结成立(任一不一致 ⇒ 有未停止写入面,中止并排查)。
3. **锚采集**:以一致的那次扫描值填入 v2 锚候选(字段模式见
   `.github/workflows/deploy-production.yml` R5 注释;参考采样:
   2026-10-22T02:48:51Z 单窗口,B 已交四锚一致记录)。
4. **写 secret**:A 将锚 JSON base64 后写入 production Environment secret
   `PREFLIGHT_TRUST_ANCHOR_B64`(部署预检 fail-closed 必需项,当前未配置)。
5. **同窗口内部署**:dispatch v1.6.4-r3 部署;预检在活卷上重扫并要求与锚
   精确一致。**若部署前窗口被打破(任何写入)⇒ 预检 DENY(fail-closed),
   须重走 2–4。**
6. **窗口收尾**:/health PASS + 验收探针完成后,重启 sync-cron/executor
   (此后卷恢复漂移属预期,锚已完成使命)。

备选(不推荐):放宽预检对 manifest 字段的精确等值(仅比对其余锚)——
削弱 G2 控制面断言,需要 A 显式裁决并修订冻结契约;本文不预设该选项。

## 4. 职责归属

- B 已交:漂移实证、逐文件元数据清单证据、v2 锚候选(2026-10-22 采样)、本程序。
- REQUIRES_A_ACTION:停写窗口授权与执行、锚最终采集、secret 写入、部署 dispatch 时机。
