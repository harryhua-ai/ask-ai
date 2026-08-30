# Review Report: web-data-win(C10+C9+C8)

> **Reviewer**:Planner / Reviewer Authority · 2026-08-30
> **契约**:`docs/engineering/contracts/c8-c9-c10-web-data-win.md` · **Baseline**:`fe98ca2` · **Final**:`76d75e7`(5 commits,未 push)
> **执行报告**:`docs/engineering/tasks/web-data-win-execution.md`(侧聊会话主笔 + 主执行窗独立交叉验证)

## 独立重查

| 要素 | 核验 | 结论 |
|---|---|---|
| Frozen Contract | 三契约要素齐全;执行链线性 5 commits(C10→C9→C8 依序 + 2 增补);执行端内部双会话协作,产物统一于单链,报告合并双视角 | ✅ |
| Baseline → Final Diff | +1888/-50,18 文件;C8 `web_crawl.py` 485 行 + 264 测试;C9 端点 +237 + 前端上传;C10 `github.py` +63 | ✅ |
| 安全关键点(Reviewer 重点) | **C10 脱敏**:双层(token 字面替换 + `x-access-token:***@` 正则兜底)+ `_run_git` 统一 RuntimeError 带 stderr 摘要——超出契约要求;**C9 穿越**:`_safe_upload_path` 双重防护(`..` 段拒绝 + resolve 前缀校验兜底 symlink),测试覆盖绝对/`..`/混合嵌套四变体且断言不落盘 | ✅ |
| Tests | 全量 **532 passed, 3 skipped**(主执行窗在最终 HEAD 独立复跑);ruff worktree 77 vs main 78(净 -1,顺手修既有项);admin build ✓ | ✅ |
| Runtime Evidence | C8 A2:126 篇官网文档入库、`/store/` SQL 直查 **0 行**;A3:NG4500 本地 BM25 命中 + 侧聊经真实 `/api/ask` 验证 sources=5(NG4500 产品页 rank 2) | ✅ |
| Acceptance | 三契约 A1-A4 全过 | ✅ |

## 附注

1. **执行模式观察**:本束由执行端"主窗 + 侧聊"协作完成——与早前"幽灵并发"(D-11 时期的上轮窗口漏推)不同,本次产物统一于一条线性链、报告交叉署名,可接受;但此类协作应在报告头部声明(已做)。
2. **lint 净 -1**:增补提交顺手修复 main 既有 lint 项,方向正确,接受。

## 最终判定:**PASS**——三契约全过,放行 push

遗留(非本契约范围):**PAT 泄漏落库事件**(C10 修复前 12:03 的 sync_log 错误行含明文 PAT)——处置待产品负责人:①轮换该 PAT(必须);②删除该行 sync_log(建议,等确认后执行)。

*下一里程碑:T1a 前一次性发布(`5ca3dfe`+`fe98ca2`+本束)→ 发布后观察三项 → wiki 灰度。*
