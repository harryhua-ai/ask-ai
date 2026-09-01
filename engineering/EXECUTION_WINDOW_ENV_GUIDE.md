# 执行窗环境引导(执行窗交接,双窗共用)

> 依据:用户 2026-09-01 指示(并入 P0_KNOWLEDGE_TRUST_BOUNDARY 与 P1_GENERATION_RELIABILITY 两执行窗交接提示词)。
> 执行端必须在执行报告中**逐条确认**以下 8 项,并附文末三行自证。

1) **代码隔离**:各自独立 worktree + 分支,基于冻结基线 `76b2199`;两窗不共享工作目录。
2) **权重共享(只读)**:worktree 内执行 `ln -s /Users/harryhua/Documents/GitHub/ask-ai/models models`;BGE-m3 + bge-reranker-v2-m3 权重复用 main 仓,只读使用,**禁止重新下载/联网拉取**。(注意:.env 的 `MODEL_CACHE_DIR=models` 是相对路径,须覆盖为绝对路径或建软链,二选一。)
3) **配置**:`cp /Users/harryhua/Documents/GitHub/ask-ai/.env .`(gitignored,worktree 不会自带)。
4) **起后端必须 `HF_HUB_OFFLINE=1`**(不加会联网校验/重新下载权重):
   `HF_HUB_OFFLINE=1 nohup .venv/bin/python -m backend.main`
5) **端口**:main 仓 8000 后端是用户 admin 5174 正在用的,**禁止 kill/pkill backend.main**;两执行窗后端各换端口(建议 P0=8010、P1=8011),健康检查打各自端口。
6) **venv 坑**:main 的 `.venv` 若为 editable 安装,worktree 内跑 pytest 必须 `export PYTHONPATH=<worktree 绝对路径>`,否则测到 main 的代码,违反冻结基线。
7) ⚠️ **共享 weaviate(localhost:8080)是验收基线 + 主后端正在用的共享知识库**:P0 的 AC-07 迁移/重索引验证**禁止直接写该实例**——用临时容器换端口(或先 dump 备份),防止污染共享库;只读查询允许。
8) **Postgres**:pytest 用 `TEST_DATABASE_URL` 指 5432 的 `ask_ai_test` 库,**禁止指向主库跑写测试**。
   DSN 由 `.env` 离散变量组装(`POSTGRES_USER/PASSWORD/HOST/PORT` + `/ask_ai_test`),`.env` 里没有 `DATABASE_URL` 这个键。

## 执行端自证(三行,附于报告)

```text
WORKTREE: <绝对路径> / 分支 <branch>
BACKEND_PORT: <端口>(health 实测 200)
未重新下载权重 / 未动 8000 主后端 / 未写共享 weaviate(仅只读)
```

## P0 窗 conformity 备案(2026-09-01,如实记录)

- 第 1/2/3/4/5/6/8 条:全部符合(P0=ask-ai-p0-trust-boundary / worktree-exec/p0-trust-boundary;:8010;MODEL_CACHE_DIR 指向 main 仓 models 绝对路径;HF_HUB_OFFLINE=1;PYTHONPATH 指本 worktree;TEST_DATABASE_URL 指 ask_ai_test)。
- **第 7 条:本引导到达之前,P0 窗已按"临时改写+还原"方式在共享 weaviate 上完成迁移验证**(引导到达时 E2E 已收尾)。写入范围 = knowledge-*/local-* 四个前缀共 1663 对象的 channel_visibility 属性;每次写入后均**验证还原**(终态全部 `("widget","api")`,与初始一致,证据见 P0 报告 §还原)。影响窗口内主后端(:8000)的案例类答案会短暂降级为拒答。此为时序偏差而非方法选择,已如实上报;后续任何索引级验证一律走隔离 weaviate 实例。
