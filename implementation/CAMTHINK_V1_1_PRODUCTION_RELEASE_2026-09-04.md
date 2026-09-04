# CAMTHINK V1.1.0 — Main Integration & Production Release Report

- 日期:2026-09-04
- 角色:Engineering Executor
- STATUS:**PRODUCTION CANDIDATE READY**
- RECOMMENDED_PRODUCTION_VERDICT:**FINAL PRODUCTION PASS**(建议;决定权在 Planner)
- 执行边界:按 §22 已 **STOP BEFORE TAGGING** —— 未打 tag、未建 GitHub Release、未关 #22/#24、未动 Roadmap

---

## TARGET_VERSION

v1.1.0

## RELEASE_CANDIDATE

`b7a016d0d3ec91ee69a2302a519d3ce4d9e9fdbb`(IMMUTABLE;全程零改动)

## PRE_RELEASE_MAIN

`0e6a8a3bb72932b26fcf500954aacfe109373133`(origin/main;实证为候选祖先,零偏离提交)

## MAIN_SHA

**`b7a016d0d3ec91ee69a2302a519d3ce4d9e9fdbb`**(fast-forward:`git push origin b7a016d…:refs/heads/main`,`0e6a8a3..b7a016d`)

## MAIN_INTEGRATION

| 项 | 结果 |
|---|---|
| MAIN-1 origin/main 预期态 | 0e6a8a3 = final-rc-20260903,候选祖先 ✓ |
| MAIN-2 b7a016d 远程在位 | ✓ |
| MAIN-3 RC 血缘无新提交 | 0e6a8a3..b7a016d 恰 4 提交(2ba83d6→698e727→2306118→b7a016d),与已接受证据一致 ✓ |
| MAIN-4 不丢已接受提交 | FF 保留精确历史 ✓ |
| MAIN-5/6/7 | main contains 698e727 / 2306118 / b7a016d ✓ |
| MAIN-8 树内容零变化 | `git diff b7a016d MAIN_SHA` = 空 ✓ |
| MAIN-9 工作树干净 | 验证 worktree tracked 零改动 ✓ |
| MAIN-10 origin/main == MAIN_SHA | ✓ |

## POST_MERGE_CI

- Run **33853247365**(workflow_dispatch on main,headSha = MAIN_SHA):`test` **success** + `build-and-push` **success**
- CI-1..CI-4 ✓;CI-5:镜像内 RELEASE.json `git_sha=b7a016d…`、`ci_run_id=33853247365`(fail-closed 实证)
- 未复用 RC 分支镜像:部署物 = main 精确构建(避免任何同号异证歧义)

## IMAGE_TAG / IMAGE_DIGEST

- IMAGE_TAG:`ghcr.io/harryhua-ai/ask-ai:sha-b7a016d`
- RepoDigest:`sha256:8b009e8d50c247918e364a34d1908fac0b4d581fd58c2810e877172c94548135`
- ImageID:`sha256:16f7c74ec5ef81bfab2b0d956478b74052e47be8bb41c00d42c5a572167913ed`(运行容器与目标镜像逐一相等)
- RELEASE_METADATA:version `0.0.0+main.b7a016d0` / git_sha `b7a016d…` / built_at 2026-09-04T08:35:42Z / ci_run 33853247365
- DEPLOYMENT_TIME:**2026-09-04T08:54:51Z**(三服务同批切换)

## PRE_MIGRATION_STATE(DB-1..DB-5)

- 生产 schema 实证:site_experiences **11 列,零 launcher 列**(ba90450 基线态;DB-1/DB-2 → REV0+REV1 两段都需执行)
- 行数 3(camthink-website / camthink-wiki / camthink-store,全部 enabled)
- DB-4 备份:`~/ask-ai/backups/v110_release_20260904/`
  - `site_experiences_pre_v110.sql`(表级)
  - `pg_askai_pre_v1.1.0_20260904T082424Z.sql.gz`(全库,6.4MB)
- DB-5 schema 证据:上方列清单 + 备份内 CREATE TABLE

## MIGRATIONS_EXECUTED

目标镜像一次性容器(compose 网络内,凭据从运行中后端容器透传、零回显):
1. `scripts/migrate_add_site_launcher_appearance.py`(REV0:launcher_style/launcher_theme)
2. `scripts/migrate_add_site_launcher_icon_shape.py`(REV1:launcher_icon/launcher_shape)
3. 两脚本幂等重跑各一次(DB-15:与隔离彩排一致)

> 执行注记:首次尝试因镜像内缺 `PYTHONPATH=/app` 失败(ModuleNotFoundError),加 `-w /app -e PYTHONPATH=/app` 后成功——纯执行环境修正,未改任何代码。

## POST_MIGRATION_STATE(DB-6..DB-15)

- DB-6:launcher_style/theme/icon/shape 四列齐备 ✓
- DB-7:行数 3 保持 ✓;DB-8 site_id ✓;DB-9 allowed_origins ✓;DB-10 enabled ✓;DB-11 welcome/starters ✓
- DB-12:生产无遗留 launcher_style 数据(基线无此列)——空集成立,如实记录
- DB-13/14:四列全 NULL,零图稿 opt-in ✓
- DB-15:幂等重跑一致 ✓

## DEPLOYMENT

- DEPLOY-1 健康 PASS(部署后 ~25s 内 ok;GPU 预检 14,599/16,384 MiB)
- DEPLOY-2 `/health` → `git_sha=b7a016d…`(运行时身份 = 镜像身份 = MAIN_SHA)✓
- DEPLOY-3 运行容器 ImageID == 目标镜像 ImageID(16f7c74e…)✓
- DEPLOY-4 无迁移/schema mismatch 启动异常 ✓
- DEPLOY-5 Admin 加载(登录 200 + 数据面 API 200)✓
- DEPLOY-6 Widget 产物加载(widget.js/css 200)✓

## CORE_PRODUCTION_SMOKE

| 项 | 结果 |
|---|---|
| PA-CORE-1 health | ✓ |
| PA-CORE-2 Admin 认证 | ✓(登录签发 token) |
| PA-CORE-3 知识/源视图 | ✓(data-sources 200) |
| PA-CORE-4 Widget 加载 | ✓(同源产物 200) |
| PA-CORE-5 打开/关闭 | ✓(生产工件真实浏览器:launcher→ChatPanel→✕→launcher) |
| PA-CORE-6/7 ask + SSE | **先挫后复**:`**NE503…` 240 content token 流式 + done(详见 KNOWN_LIMITATIONS #1 的 GPU OOM 瞬态) |
| PA-CORE-8 引用/来源 | ✓(sources 事件随流返回) |
| PA-CORE-9/10 | ✓ 非预期错误为零(仅 2 次 OOM 瞬态已归因);无迁移异常循环 |

## ISSUE_22_PRODUCTION_ACCEPTANCE

- PA22-1 ✓ Source Center 数据面 API 200;PA22-3 ✓ 治理持久位(config JSONB `discovery_rules`)可读(当前空态=预采用预期);PA22-6 ✓ 持久化路径健康
- PA22-2/4/5:**NOT MUTATED IN RELEASE ACCEPTANCE** —— 依赖已接受的组合验收证据(RC 门 D22-1..10 全过,含 neomind-dashboard/components 具体案例);生产零发现策略改写、零同步
- 未为验收发起任何生产同步

## ISSUE_24_PRODUCTION_ACCEPTANCE

受控可逆变更 site:**camthink-wiki**(未实嵌 Widget,三站中影响面最小);变更前先验证兼容性。

- PA24-1 ✓ 未配置站 = current(兼容默认)
- PA24-2 ✓ 既有嵌入零改动(生产 widget.js 同路径同产物;本地页加载生产工件渲染正常)
- PA24-3/4 ✓ Admin 外观页数据面:3 站列表与持久值正确
- 受控变更:wiki NULL 素态 → `bot-sparkle / round / auto`(PA24-5 Save ✓;PA24-6 重读恢复 ✓;PA24-7 site-config(允许 Origin)即时反映 ✓)
- PA24-8 ✓ 客户嵌入零改动;PA24-9 ✓ 授权仍强制(变更期间错 Origin 仍 403)
- PA24-10 ✓ launcher 打开未变的真实 ChatPanel(生产工件活体)
- PA24-11 ✓ ask 恢复后同管道正常(全站同 ask 管道,PA-CORE-6 证据)
- **恢复**:SQL 将 wiki 四列复位 NULL(精确还原素态),Admin 呈现回到 current/rounded-square/auto,`restored_to_pristine = t` 复验 ✓

## SECURITY_SMOKE

- SEC-1 ✓ 允许 Origin → 200;SEC-2 ✓ 错 Origin → 403;SEC-3 ✓ 外观已设置 + 错 Origin 仍 403(外观不授予访问);SEC-4 ✓ 仅 site_id 无 Origin → 403(标识非凭证);SEC-5 ✓ Admin 外观 API 未认证 → 401
- 授权链代码在 ba90450→b7a016d 零改动(scope audit)

## OBSERVATION

- OBS-1 健康 8/8 稳定(1 分钟间隔 × 8 分钟,恢复后窗口)✓
- OBS-2 零迁移错误 ✓;OBS-3 恢复后近 8 分钟 ERROR=0 ✓
- OBS-4/5 Widget/Admin 产物与服务健康 ✓;OBS-6 ask 流恢复后健康 ✓
- OBS-7 Source Center 无回归迹象(数据面 200、同步面正常启动)✓
- OBS-8 生产数据零意外变更(3 站素态保持;变更台账仅含授权项)✓
- sync-executor 启动正常(独立执行面已启动;既存 SAWarning 为已知小修候选,与本发布无关)

## ROLLBACK_READINESS

- 备份:表级 + 全库 dump(见 PRE_MIGRATION);应用回滚 = `ASKAI_IMAGE_TAG=sha-ba90450` 同批三服务切换(上一不可变 tag)
- 回滚语义:launcher 四列为 additive nullable,旧镜像忽略之,launcher_style 在生产为空集 → 回滚行为确定
- 破坏性 schema 回滚(DROP COLUMN)未测试、不声称

## PRODUCTION_MUTATIONS(台账)

1. v1.1 DB 迁移执行(REV0+REV1,加列幂等 ×2 轮)
2. 三服务部署 MAIN_SHA 精确工件(sha-b7a016d)
3. camthink-wiki 受控外观变更 + 复位恢复(发布验收专用)
4. 最小 ask 冒烟流量(4 次;其中 2 次 OOM 瞬态产生 2 条失败会话记录,属正常冒烟数据)
5. 主机 /tmp 认证 token 临时文件用后删除

未授权项均未发生:无相关数据修复、无广域同步、无发现策略清理、无凭证/origin 策略变更、无生产测试数据污染、无无关配置编辑。

## KNOWN_LIMITATIONS

1. **GPU 显存争用瞬态(已恢复)**:部署后初始两次 ask 因宿主 CUDA OOM 失败(第三方共享服务 ~11.5G + 已知孤儿 root sync/backend 进程 ~3.7G 占满 15.56G;DeepSeek API 本身 200)。第三方进程释放显存后第三次 ask 起完全恢复并保持。归因:宿主环境既有状况(09-03 已有同类事故记录;ba90450..b7a016d 的 ask/embed 管道代码零改动);孤儿 root 进程清理须用户单独授权(不在本契约内);#14 embedder CPU 回退缺位为已知产品缺口,W2 契约已冻结待实现。
2. wiki/store 站当前未实嵌真实页面 → PA24-7 以 API 级 site-config 证据 + RC 门浏览器级渲染证据组合覆盖。
3. PA22-2/4/5 依赖 RC 门组合证据 + 生产只读健康(生产未做发现策略变异)。
4. 破坏性回滚未测(契约明示不要求)。
5. 主机孤儿 root sync.py/backend 进程(~3.7G VRAM)建议尽快单独授权清理,可显著缓解 OOM 复发风险。

## RECOMMENDED_PRODUCTION_VERDICT

**FINAL PRODUCTION PASS**(建议)—— MAIN 集成/CI/迁移/部署/验收/观察全链通过;唯一次生事件(GPU OOM)为宿主环境既有状况、已自愈并经 8 分钟稳定窗复验,不影响发布物正确性。Planner 拍板后进入 §16 正式化(v1.1.0 tag → GitHub Release → #22/#24 closure → Roadmap)。
