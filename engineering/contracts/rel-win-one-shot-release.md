# Execution Contract: REL-WIN(T1a 前一次性发布 + 三项观察)

> **任务代号**:REL-WIN · **签发**:Planner / Reviewer Authority,2026-08-30
> **BASELINE_COMMIT**:`76d75e7`(= origin/main,CI run 33321125298 产物)
> **性质**:部署验收 + 运行时观察,**零代码改动**
> **工作流条款**:建议 superpowers 工作流(若可用);纪律以本契约要求为准。

## Objective

把 08-30 全部修复(P1 admin 检索 / D4 ingest 记账 / 校验器口径 / C10 表单与脱敏 / C9 上传文件夹 / C8 官网爬取源)一次性带上 T4 生产,并通过运行时观察验证三项生效。

## Scope

1. **前置**:CI 33321125298 = success;`ssh tesla-t4 'df -h /'` 余量 ≥20%(红线,不足即停回报)
2. **发布**:`ssh tesla-t4 'cd ~/ask-ai/deploy/prod && ./update.sh'`;健康检查(BGE 加载慢 ~45s 属预期,勿误判);**容器版本实查**:容器内存在 `backend/connectors/web_crawl.py` 且 `github.py` 含 `_sanitize`(76d75e7 特征,防运行旧版)
3. **观察三项**(发布后依次):
   - ① admin"同步全部"→ 五源(ne301/wiki/extensions/lowpower/devicetypes)+ 假阳性两源(dashboard/neomind-local)应 **partial→success**(孤儿已清 + 口径统一后直接一致);ne503-sdk 允许一轮 partial(D4 修复后假成功文档首次真实重灌)后下轮收敛
   - ② **官网源首爬**:website-camthink 首次同步(T4 需外网访问 www.camthink.ai),预期 ~126 篇入库、/store/ 零;NG4500 抽查
   - ③ admin 内嵌聊天问一个产品问题(如 "NE503 specs")→ 应出 sources + 回答(P1 生效)
4. **PAT 泄漏行删除**(独立动作,产品负责人已确认处置方式后执行;未确认则跳过并注明)

## Non-goals

不做 T1a 动作(嵌入/清洗);不动数据(除第 4 条点名行);不 reindex。

## Acceptance

| # | 验收 |
|---|---|
| A1 | 版本实查通过(两特征文件) |
| A2 | 观察三项各留证据(SyncLog 前后对照 / 首爬计数 / admin 问答 sources) |
| A3 | 磁盘前后读数;红线全程遵守 |
| A4 | 执行报告 `docs/engineering/tasks/rel-win-execution.md`,四态自评 |

## 执行提示词(Executor 入口)

你是 Engineering Executor,执行发布契约 REL-WIN(部署 + 三项观察,零代码):

必读:/Users/harryhua/Documents/GitHub/ask-ai/docs/engineering/contracts/rel-win-one-shot-release.md

- 前置:CI 33321125298 success + T4 磁盘 ≥20% 余量(不足即停)
- 发布:update.sh → 健康检查(45s 加载预期)→ 容器内验证 web_crawl.py 与 _sanitize 双特征
- 观察三项留证据:①同步全部前后 SyncLog 对照 ②website-camthink 首爬计数+/store/ 零+NG4500 抽查
  ③admin 聊天产品问答出 sources
- PAT 删除动作:仅产品负责人明确确认后执行,否则跳过注明
- 汇报:docs/engineering/tasks/rel-win-execution.md,给证据不给形容词,四态自评
- 红线:绝不 --reindex;不部署后手动全量;提交不含 docs/(本任务零提交)
