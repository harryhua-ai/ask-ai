# ASK-AI v1.0.1 Production Release Report(2026-09-04)

> 执行身份:Engineering Release Executor(Contract:ASK-AI v1.0.1 — Production Release Gate;
> R3 Planner Authorization + #19 Contract Amendment 授权后执行 R4/R5)。
> 本报告不构成 PRODUCTION FINAL PASS;Planner 拥有最终 Production Acceptance。

## 1. RELEASE_CANDIDATE

- 权威候选:`ba904501bd171ed318c637ae07109174d65505ef`(分支 `v1.0.1/issue23-performance`,已推 origin)
- 血统:0e6a8a3(v1.0.0)→ 3cf42da(v1.0.1 集成候选)→ ba90450(Issue#23 性能补丁)
- 执行期间零代码变更:R4/R5 全程未改动 candidate 任何文件

## 2. CI_IMAGE

- CI run:`33834723578`(workflow_dispatch @ `v1.0.1/issue23-performance`,test job 先行绿)
- 镜像:`ghcr.io/harryhua-ai/ask-ai:sha-ba90450`
- Digest:`sha256:66f71e976a9ac04c6c4d6733012d364826c3bf49d34cf4ed5bdb64f121003c92`
- Image Id:`sha256:237fdaf83dc2f5a66b6649833a28f2dd0d4fd68136e94132ff711503a9206f67`
- built_at:2026-09-04T04:03:28Z;ci_run_id=33834723578

## 3. IMAGE_IDENTITY_VERIFICATION

主机独立拉取后提取 `/app/RELEASE.json`(不信任 tag 名):

```json
{"version": "0.0.0+main.ba904501", "git_sha": "ba904501bd171ed318c637ae07109174d65505ef",
 "built_at": "2026-09-04T04:03:28Z", "image": "ghcr.io/harryhua-ai/ask-ai:sha-ba90450",
 "ci_run_id": "33834723578"}
```

断言 `git_sha == ba904501bd171ed318c637ae07109174d65505ef`(完整 40 位精确相等)✅

## 4. PRODUCTION_BEFORE_STATE

- 三服务均 `v1.0.0`(git_sha=0e6a8a3bb72932b26fcf500954aacfe109373133,ci_run_id=33778725934),backend healthy
- postgres / weaviate 基础设施未动(2 周+ uptime)
- documents 11,987 行;PK=(source_id);sync_runs/sync_requests/site_experiences 在位(v1.0.0 迁移全套)
- sync_runs 共 364(359 completed / 5 failed 历史),零 unfinished;sync_requests 全 done

## 5. CONFIG_BEFORE / CONFIG_AFTER

文件 `/home/ubuntu/ask-ai/.env`(compose `env_file: ../../.env`,43 行):

- CONFIG_BEFORE:`16:DEEPSEEK_MODEL=deepseek-v4-pro`
- 备份:`.env.bak-v101`(逐字节副本,1621 bytes)
- CONFIG_AFTER:`16:DEEPSEEK_MODEL=deepseek-v4-flash`
- diff 恰一行;`TEST_DATABASE_URL`(line 40)及其余 42 行零触碰;无任何密钥值打印
- 权威链:DB `llm_providers[deepseek].config.model=deepseek-v4-flash` + intent/query_rewrite/pruning/generation 四条 routing 链全钉 flash → RUNTIME_EFFECTIVE=flash(与 env 对齐后一致;config.py 兜底 deepseek-chat 仅在 env 缺失时生效,故不可删行)

## 6. ACTIVE_SYNC_CHECK(部署前)

- sync_runs 零 unfinished;sync_requests 20/20 done;sync-executor 10 分钟无日志
- 部署窗口内无活跃同步 ✅

## 7. DEPLOY_RESULT / RUNNING_COMMIT

- 部署时间:2026-09-04T~04:15Z(new sync-executor 启动日志 04:14:20Z)
- **部署方式说明**:`deploy/prod/update.sh` 的版本断言语法只认 `vX.Y.Z`(`EXPECTED_VERSION=${TAG#v}`),
  对 manual 构建的 version `0.0.0+main.ba904501` 必然 fail-closed 误拒。经授权范围内处理:
  手工逐步复刻 update.sh 的 #10 契约步骤,且断言更严(完整 git_sha 相等,而非仅 version 串):
  1. `docker compose pull`(ASKAI_IMAGE_TAG=sha-ba90450)
  2. RELEASE.json 身份断言(见 §3,先于任何容器变更)
  3. GPU 预检:15547 MiB used(>15G 告警线,embed 同步不在本门范围,已记录)
  4. `up -d backend` → 健康轮询(<5s 就绪)→ 运行时 `/health` version+git_sha 双断言
  5. `up -d sync-cron sync-executor` → 三服务镜像身份逐一核验
- **RUNNING_COMMIT == ba904501bd171ed318c637ae07109174d65505ef** ✅
  (`/health` = {"version":"0.0.0+main.ba904501","git_sha":"ba904501bd171ed318c637ae07109174d65505ef","app_mode":"production"})
- 遗留治理观察(未在本门修改):update.sh 无法表达 manual sha 构建,建议后续 contract 扩展其断言语法

## 8. SERVICE_HEALTH(部署后)

backend Up (healthy) / sync-cron Up / sync-executor Up / postgres Up 2 weeks (healthy) / weaviate Up 2 weeks (healthy);三服务同 tag `sha-ba90450` 逐一核验通过。

## 9. #19 MIGRATION(metADATA-ONLY,授权硬上限 52)

- PRE_APPLY(部署后镜像原生脚本复跑对账):scanned=101,candidates=52,mapping 与 R2 dry-run 逐字节一致
  (aitoolstack→ne101 17 / ne301 18 / ne503 4 / ng4500 7;commercial→ne101 3 / ne301 3),零漂移
- 回滚证据:apply 前全量快照 `store_chunks_before_apply.json`(101 行 uuid+product+title;before 分布 commercial 44 / aitoolstack 57)
- MIGRATION_ACTUAL:apply 日志 `updated=52 chunks(零 re-embed,向量未触碰)`;PRE=52 / ACTUAL=52 / 差=0
- POST_APPLY 复跑 dry-run:**candidates=0,mapping={}**(零残余候选)
- after 分布精确闭合:commercial 38 / aitoolstack 11 / ne101 20 / ne301 21 / ne503 4 / ng4500 7(总 101)
- 自然周期验证:部署后首个 sync 周期(04:17Z)`woocommerce-mall 无变更,跳过(documents 已有 40)` —— 迁移结果无漂移
- 证据:`tesla-t4:~/ask-ai/backups/v101_preflight_20260904/mig19_{dryrun_preapply,apply,dryrun_postapply}_ba90450.{json,log}` + `store_chunks_{before,after}_apply.json`
- 逆向方法:52 条 uuid→old 映射(before 快照 ∩ apply 计划),原位属性回写即可

## 10. FUNCTIONAL_SMOKE(R5,生产 18000,channel=widget)

| # | 问题 | 结果 | 关键证据 |
|---|---|---|---|
| B | NG4500 的算力是多少 TOPS?(#5 精确产品) | PASS | sources 全部 product=ng4500(wiki+store);答案仅述 NG4500 系列(20-100 TOPS 按模块),无兄弟产品污染;诚实声明"无统一固定值" |
| C | NE302 和 NE301 有什么区别?(#19 对比) | PASS | sources 双目标在位(ne302 wiki ×3 + ne301 store/wiki);答案分段各自归因(NE302: 38×38mm/STM32N657L0H3/PSRAM vs NE301: 无线/LTE Cat.1/600 GOPS NPU);无静默降级、无跨产品证据混用 |
| D | NeoRuntime 如何安装部署?(How-to 锚题) | PASS | intent= support **confidence=0.9**(空 content fail-open 异常未复现);答案落地(/opt/aipc/web/docs/、:8080/docs/)且诚实指出 README 与 installation.rst 的矛盾;sources product=neoruntime |
| E | NE900 什么时候发布?(无证据) | PASS | 不编造:"官方资料未载明 NE900 的发布时间",列出实际找到的产品,引导官方渠道;3.5s 快速拒答 |
| F | 引用完整性 | PASS | B/C/D 的 [n] 标记与 sources 事件编号一一对应;终验滤光日志:`dangling_dropped: 0 / ineligible_product_dropped: 0` |
| G | 流式 | PASS | 4 题均 token 渐进到达(n=84~692 token 事件,TTFT<E2E);零 error 事件;8 会话 DB 全 `is_answered=True` |

冒烟会话 conversation_ids:012518f9 / 1c1c1196 / b02b1e95 / 0b29506d(+4 次 perf 锚题)。

## 11. PERFORMANCE_SMOKE(有界小样本)

思考开关生产实证(三重证据):

1. 运行镜像内代码核验:`deepseek.py:70-79 _apply_thinking` 在 generate(99)/stream(158)双 payload 注入;调用点 intent.py:71、query_rewrite.py:73+125、rag.py:1124+1701 全部在位
2. 生成 TTFT(日志 RAG timing):**407-663ms**(混合思考未关时为秒级尾巴)
3. 意图空 content 异常消失(confidence=0.85-0.9 稳定输出)

锚题 `NeoRuntime 如何安装部署?` n=5:

| 样本 | TTFT(s) | E2E(s) |
|---|---|---|
| 1 | 7.29 | 10.93 |
| 2 | 7.81 | 10.54 |
| 3 | 7.31 | 10.36 |
| 4 | 6.84 | 9.51 |
| 5 | 7.32 | 10.34 |

- 中位:TTFT≈7.3s / E2E≈10.4s;阶段分解:generation TTFT 0.41-0.66s、rewrite 0.40-0.91s、rerank ~1.0s、search ~0.06s、llm_total 3.1-3.7s
- 单点参考:对比题 7.16/11.61;拒答题 2.85/3.55;首问(冷路径)10.54/11.90
- **INSUFFICIENT SAMPLE FOR DISTRIBUTION SLO**(n=5,不宣称 p90/p95,不认证 7-day SLO)
- 与 SLO 目标关系:E2E 中位 10.4s 贴近 p50≤10s 目标线,但认证归长期生产观察;对比 v1.0.0 基线(同锚题典型 ~12.5s)无性能回归信号,亦无"hidden reasoning 重尾"复现

## 12. ROLLBACK_STATE

- 全程未触发回滚(ROLLBACK_TRIGGERED=NO)
- 部署回滚:`./deploy/prod/update.sh v1.0.0`(镜像在主机本地+GHCR)
- 配置回滚:`cp .env.bak-v101 .env` + 容器重建
- 迁移回滚:52 条 uuid→old 原位属性回写(before 快照在手)

## 13. PRODUCTION_MUTATIONS(全集,无隐性变更)

1. `.env` line16 值改写(pro→flash)+ 备份文件创建
2. backend / sync-cron / sync-executor 三容器以 sha-ba90450 重建(部署必需)
3. woocommerce-mall 源 52 条 Weaviate `product` 属性原位更新(零向量/零 re-embed/零内容)

## 14. KNOWN_RISKS

1. GPU 显存 15547 MiB(>15G 部署告警线):embed 同步如遇 OOM,既有预案 EMBEDDER_BATCH_SIZE=8;本门未触碰
2. `Pruner LLM 返回格式异常,fail-open 保留全部 chunk` 每题出现:QW-1 未触碰 pruner(非本门改动面),行为 fail-open 安全,疑似既有状态 —— 建议独立 issue 排查(v1.0.0 期日志已随容器重建不可回溯)
3. update.sh 断言语式不含 manual sha 构建(本次以等效手工契约完成);建议后续 hardening
4. sync_executor_loop.py:281 SAWarning(既有小修候选)照旧出现,未处理(超范围)

## 15. OUTSTANDING_OBSERVATION

- 长期 Performance SLO(TTFT p50≤2.5/p90≤6;E2E p50≤10/p90≤20)待生产真实流量观察认证
- store 源后续真实 re-sync 时,新 ingest 走连接器设备身份派生,应与迁移结果同分布(首周期已验证无变更场景;含内容变更的场景留观察)
- `.env` line40 TEST_DATABASE_URL(卫生项,#20 守卫已代码化)保持原样未动

## 证据目录

`tesla-t4:~/ask-ai/backups/v101_preflight_20260904/`
(mig19 dry-run preapply/apply/postapply JSON+log、store_chunks before/after 快照、smoke_B/C/D/E sse.jsonl、perf_neoruntime_1-5 sse.jsonl、ask_smoke.py)
