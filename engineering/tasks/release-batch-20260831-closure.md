# 发布批次收口记录(2026-08-31,C8B+T28+T26+T27+T29)

- **状态**:CANDIDATE READY(五分支已合入 main 并推送;等用户决定 T4 发布窗口,不部署、不碰 T4)
- **基线 → 当前**:`bbfaa6a` → `76b2199`(两次 push)

## Merge Commits(均 --no-ff,文件域互斥零冲突)

| 任务 | merge commit | 原始分支 commit |
|---|---|---|
| C8B web_crawl 表单一等公民 | `02bb1fd` | 7249ee7 |
| T28 健康度文档数前缀聚合 | `69c2a15` | cc09cce |
| T26 对话审查列表降噪 | `7ca1ad0` | 90dff34 |
| T27 换供应商三缺陷 | `3a0c766` | 37d7501 |
| T29 引用徽标数字+悬停标题 | `76b2199` | d85cb83 |

## Push 区间与 CI

- push 1:`bbfaa6a..3a0c766` → CI run **33372726537** :test ✅ / build-and-push ✅(**success**)
- push 2:`3a0c766..76b2199` → CI run **33374047900** :test ✅ / build-and-push ✅(**success**)

## 合入后验证(本地实测)

- 后端:admin 口径 97 passed(净库连跑 2 遍稳定)+ CI 确切口径 447 passed;
- admin:vitest **131/131** + tsc exit 0;
- widget:vitest **30/30** + tsc exit 0;
- T29 合入仅触 widget/ 域(3 files,+73/−12),后端/admin 零波及。

## Worktree 退役

五个 worktree 已全部移除(先查无监听进程),已合并分支同步删除;现仅剩 `ask-ai-t1a-launch`(worktree-exec/t1a-launch,非本批次,保留)。主仓工作树干净,main=origin/main=`76b2199`。

## 备注

- docs 仓:`e4b0eec`(四分支 FINAL PASS)+ `ea56076`(T29 FINAL PASS);本收口记录与五份 execution 报告为 docs 仓未跟踪文件,由 A/本地管理。
- 本地 ask_ai_test 库集成验证按防呆顺序执行(先清 lifespan-smoke 种子的 deepseek 脏行再跑 admin 口径),规避既有测试库毒化。
