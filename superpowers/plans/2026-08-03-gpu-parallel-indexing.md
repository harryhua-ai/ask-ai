# GPU 并行索引(Plan 2)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 sync worker 部署到 tesla-t4(NVIDIA T4 16GB),通过 GPU cuda + 大 batch embedding 把全量索引(25 万 chunk)从 mac mps 的 ~8 小时降到 ~50 分钟。

**Architecture:** sync worker 跑在 tesla-t4(BGE-m3 `device=cuda` + `batch_size=64`),通过 Tailscale 内网连接 mac 上共享的 Postgres + Weaviate(写索引);backend 仍留 mac 提供问答。串行 + 大 batch 即可达标(无需跨源并行重构),并行作为可选优化。

**Tech Stack:** BGE-m3(`device=cuda`、`use_fp16=True`)、FlagEmbedding、Tailscale(共享 DB/Weaviate)、ssh tesla-t4、psycopg2(同步 PG)。

**范围:** spec §13 步骤 4(GPU 并行)+ §4.3.5 部署。**不含 SCIP 符号层(§13 步骤 5/P4)**——后置为独立 Plan(端到端测试已证 rerank 对 support/文档召回足够,SCIP 降为可选)。

## Global Constraints

- T4 16GB,`device=cuda`,`use_fp16=True`(bge.py 已按 device!=cpu 开 fp16)
- batch_size 按需配置:`max_length=1024`(代码 chunk ~600 token 够)→ `batch_size=64`;长文本场景 `max_length=8192` → `batch_size=8-16`(防 OOM)
- tesla-t4 通过 Tailscale 连 mac 的 Postgres(5432)/Weaviate(8080);mac 的 docker 端口需对 Tailscale 可达
- corpus(10 repos,~2GB)在 tesla-t4 本地(git clone 或 rsync)
- 测试隔离 `TEST_DATABASE_URL=ask_ai_test`;Python ≥3.12,类型注解

---

## File Structure

| 文件 | 责任 | 动作 |
|---|---|---|
| `backend/embedder/bge.py` | batch_size + max_length 配置化(从 settings 读) | Modify |
| `backend/config.py` | `EMBEDDER_BATCH_SIZE` / `EMBEDDER_MAX_LENGTH` 配置项 | Modify |
| `deploy/sync-worker-t4.sh` | tesla-t4 部署脚本(clone + uv sync + corpus + .env) | Create |
| `scripts/sync.py` | (可选)跨源并行 | Modify(可选 Task 4) |
| `tests/embedder/test_bge.py` | batch_size 配置回归 | Modify |

---

### Task 1: bge.py batch_size + max_length 配置化

**Files:**
- Modify: `backend/embedder/bge.py:82-99`(embed 方法,从硬编码 batch_size=12 改为构造时注入)
- Modify: `backend/embedder/bge.py:46-72`(BGEEmbedder.__init__ 加 batch_size/max_length 参数)
- Modify: `backend/config.py`(Settings 加 `embedder_batch_size` / `embedder_max_length`)
- Modify: `backend/main.py`(构造 BGEEmbedder 时传 settings 的 batch_size/max_length;sync.py 同样)
- Test: `tests/embedder/test_bge.py`

**Interfaces:**
- Produces: `BGEEmbedder(device, model_name, cache_dir, batch_size=12, max_length=8192)`;`embed` 用 `self._batch_size` / `self._max_length`
- Consumes: `Settings.embedder_batch_size`(默认 12,兼容)、`Settings.embedder_max_length`(默认 8192)

- [ ] **Step 1: Write failing test**

```python
# tests/embedder/test_bge.py(新增)
def test_bge_embedder_uses_configured_batch_size():
    """BGEEmbedder 应使用构造时传入的 batch_size / max_length,而非硬编码。"""
    from backend.embedder.bge import BGEEmbedder
    import inspect
    sig = inspect.signature(BGEEmbedder.__init__)
    assert "batch_size" in sig.parameters
    assert "max_length" in sig.parameters
    # embed 方法应引用 self._batch_size(不硬编码 12)
    src = inspect.getsource(BGEEmbedder.embed)
    assert "self._batch_size" in src
    assert "self._max_length" in src
```

- [ ] **Step 2: Run — expect FAIL**(`batch_size` 参数不存在)

`TEST_DATABASE_URL=... .venv/bin/python -m pytest tests/embedder/test_bge.py::test_bge_embedder_uses_configured_batch_size -v`

- [ ] **Step 3: Implement**

```python
# backend/embedder/bge.py — BGEEmbedder.__init__ 加参数
def __init__(
    self,
    device: str = "auto",
    model_name: str = "BAAI/bge-m3",
    cache_dir: str | None = None,
    batch_size: int = 12,       # 新增,默认 12 兼容 mac mps
    max_length: int = 8192,     # 新增
) -> None:
    # ... 现有 device/cache 解析 ...
    self._batch_size = batch_size
    self._max_length = max_length
    # ... 加载模型 ...

# embed 方法改用 self._batch_size / self._max_length
def embed(self, texts: list[str]) -> list[np.ndarray]:
    embeddings = self._model.encode(
        texts,
        batch_size=self._batch_size,      # 原 12
        max_length=self._max_length,       # 原 8192
        return_dense=True,
        return_sparse=False,
        return_colbert_vecs=False,
    )
    return [np.asarray(v) for v in embeddings["dense_vecs"]]
```

```python
# backend/config.py — Settings 加字段
class Settings(BaseSettings):
    # ... 现有 ...
    embedder_batch_size: int = 12
    embedder_max_length: int = 8192
```

```python
# backend/main.py(及 scripts/sync.py)— 构造 BGEEmbedder 传配置
embedder = BGEEmbedder(
    device=settings.embedder_device,
    batch_size=settings.embedder_batch_size,
    max_length=settings.embedder_max_length,
)
```

- [ ] **Step 4: Run — expect PASS**(现有 embed 测试不回归 + 新测试过)

- [ ] **Step 5: Commit** — `feat(embedder): batch_size/max_length 配置化(为 GPU 大 batch 准备)`

---

### Task 2: 部署 sync worker 到 tesla-t4(连 mac 共享 DB/Weaviate)

**Files:**
- Create: `deploy/sync-worker-t4.sh`(部署 + 跑 sync 的脚本)
- Modify: `.env.example`(补 `EMBEDDER_DEVICE` / `EMBEDDER_BATCH_SIZE` / `EMBEDDER_MAX_LENGTH` / `POSTGRES_HOST` / `WEAVIATE_URL` 说明)

**Interfaces:**
- Produces: tesla-t4 上的 ask-ai checkout + venv(torch cuda + FlagEmbedding)+ corpus + `.env`(POSTGRES_HOST/WEAVIATE_URL 指 mac Tailscale IP)
- Consumes: Task 1 的 batch_size 配置;mac 的 docker Postgres/Weaviate 对 Tailscale 开放

- [ ] **Step 1: 确认 mac Tailscale IP + docker 端口对 tesla-t4 可达**

```bash
# mac 上查 Tailscale IP
tailscale ip -4
# 确认 docker pg/weaviate 绑 0.0.0.0(deploy/docker-compose.yml ports: "5432:5432" 已绑)
# 从 tesla-t4 测连通
ssh tesla-t4 "curl -s http://<mac-tailscale-ip>:8080/v1/.well-known/ready && echo ' weaviate OK'"
ssh tesla-t4 "nc -zv <mac-tailscale-ip> 5432 2>&1 | tail -1"
```

若不通:mac docker ports 改 `"0.0.0.0:5432:5432"` + macOS 防火墙允许 tesla-t4(Tailscale 通常允许)。

- [ ] **Step 2: 写部署脚本**

```bash
# deploy/sync-worker-t4.sh
#!/usr/bin/env bash
set -euo pipefail
# 在 mac 上跑:把 sync worker 部署到 tesla-t4 并启动全量 sync
MAC_TS_IP="${MAC_TS_IP:-$(tailscale ip -4)}"
T4="${T4:-tesla-t4}"
CORPUS_DIR="${CORPUS_DIR:-$HOME/Documents/GitHub/ask-ai-corpus}"

echo "=== 1. tesla-t4 装 ask-ai + 依赖 ==="
ssh "$T4" "mkdir -p ~/ask-ai && cd ~/ask-ai && \
  git clone -q <ask-ai-git-url> . 2>/dev/null || git pull -q"
ssh "$T4" "cd ~/ask-ai && python3 -m venv .venv && .venv/bin/pip install -q -U pip && \
  .venv/bin/pip install -q FlagEmbedding transformers torch weaviate-client 'sqlalchemy[asyncio]' asyncpg psycopg2-binary pydantic-settings python-dotenv pyyaml httpx tiktoken passlib bcrypt PyJWT"

echo "=== 2. rsync corpus 到 tesla-t4 ==="
rsync -a --info=progress2 "$CORPUS_DIR/" "$T4:~/ask-ai-corpus/"

echo "=== 3. 写 .env(指 mac 共享 DB/Weaviate + GPU 配置)==="
ssh "$T4" "cat > ~/ask-ai/.env <<EOF
POSTGRES_HOST=$MAC_TS_IP
POSTGRES_PORT=5432
POSTGRES_DB=ask_ai
POSTGRES_USER=ask_ai
POSTGRES_PASSWORD=changeme
WEAVIATE_URL=http://$MAC_TS_IP:8080
WEAVIATE_CLASS_NAME=Document
EMBEDDER_DEVICE=cuda
EMBEDDER_BATCH_SIZE=64
EMBEDDER_MAX_LENGTH=1024
MODEL_CACHE_DIR=models
GITHUB_TOKEN=$(grep GITHUB_TOKEN $HOME/Documents/GitHub/ask-ai/.env | cut -d= -f2-)
EOF"

echo "=== 4. 启动全量 sync(cuda batch 64)==="
ssh "$T4" "cd ~/ask-ai && nohup .venv/bin/python -u scripts/sync.py > /tmp/sync-t4.log 2>&1 &"
echo "sync 启动在 tesla-t4,日志:ssh tesla-t4 tail -f /tmp/sync-t4.log"
```

- [ ] **Step 3: 执行部署脚本**

```bash
chmod +x deploy/sync-worker-t4.sh
./deploy/sync-worker-t4.sh
```

- [ ] **Step 4: 验证 tesla-t4 上 sync 在跑(cuda)+ 写入 mac 的 Weaviate**

```bash
ssh tesla-t4 "tail -20 /tmp/sync-t4.log | grep -E 'device=|已索引|同步完成|ERROR'"
ssh tesla-t4 "grep 'device=' /tmp/sync-t4.log | head -1"  # 应 device=cuda
# mac 上确认 Weaviate 在涨
curl -s http://localhost:8080/v1/graphql -X POST -H 'Content-Type: application/json' -d '{"query":"{ Aggregate { Document { meta { count } } } }"}'
```

- [ ] **Step 5: Commit** — `feat(deploy): sync worker 部署到 tesla-t4(GPU cuda batch 64)`

---

### Task 3: 全量索引验证(~50 分钟)

**Files:** 无代码改动,验证 task

- [ ] **Step 1: 等 tesla-t4 sync 完成(监控)**

```bash
ssh tesla-t4 "tail -5 /tmp/sync-t4.log | grep -E '同步完成|ERROR|Traceback'"
ssh tesla-t4 "pgrep -f 'scripts/sync.py' >/dev/null && echo '在跑' || echo '已结束'"
# mac 查 Weaviate 最终数(应 ~25 万)
curl -s http://localhost:8080/v1/graphql -X POST -H 'Content-Type: application/json' -d '{"query":"{ Aggregate { Document { meta { count } } } }"}'
# sync_log 全部源成功
docker exec deploy-postgres-1 psql -U ask_ai -d ask_ai -c "SELECT source_id, status, items_new, duration_ms/1000||'s' FROM sync_log ORDER BY started_at DESC LIMIT 12;"
```

- [ ] **Step 2: 验证多分支正确性**

```bash
# documents 表各分支有行(复合 PK)
docker exec deploy-postgres-1 psql -U ask_ai -d ask_ai -c "SELECT source_id, branch, chunk_count FROM documents WHERE source_id LIKE 'ne301-local/%' ORDER BY branch, source_id LIMIT 20;"
# Weaviate 多分支 chunk
curl -s http://localhost:8080/v1/graphql -X POST -H 'Content-Type: application/json' -d '{"query":"{ Aggregate { Document(groupBy: [\"product\"]) { groupedBy { value } meta { count } } } }"}'
```

- [ ] **Step 3: 端到端问答回归(用 Plan 1 的 TS_record 问题子集)**

跑 5 个之前精准答的问题,确认全量索引后答案质量不降、召回更全。

- [ ] **Step 4: 记录耗时 + commit 验证记录**

```bash
echo "全量索引耗时: <X> 分钟,Weaviate <N> chunk" >> deploy/sync-worker-t4.sh.log
git add deploy/ && git commit -m "test: 全量索引 tesla-t4 GPU 验证记录"
```

---

### Task 4(可选): 跨源并行优化

**仅当 Task 3 验证后 50 分钟仍嫌慢才做。** 当前串行 + T4 batch 64 预计 ~50 分钟,已够用。

若要做:sync.py 改 producer-consumer——`ProcessPoolExecutor` 并行跨源/跨分支文件读取 + tree-sitter 分块(CPU 密型),单 GPU worker 进程消费 chunk queue 做 batch embedding + 写 Weaviate(避免多进程重复加载 BGE-m3 撑爆 T4 显存)。预计再提速 2-3x(~20 分钟)。

**不在本期默认范围**,作为 follow-up。

---

## SCIP 符号层(§13 步骤 5/P4)— 后置

端到端测试已证:向量 + rerank 对 support/文档/代码文件级召回足够(65% 精准 + 20% 诚实拒答)。SCIP 符号(函数级精确)**降为可选**,仅在出现"客户问函数级、文件级召回不够"的真实需求时另起 Plan。不在 Plan 2。

---

## Self-Review

**1. Spec 覆盖**:
- §13 步骤 4(GPU 并行)→ Task 1(batch 配置)+ Task 2(部署)+ Task 3(验证)✓
- §4.3.5 部署(tesla-t4)→ Task 2 ✓
- §13 步骤 5(SCIP)→ 明确后置(端到端测试证 rerank 够)✓

**2. 占位符**:Task 2 的 `<ask-ai-git-url>` / `<mac-tailscale-ip>` 是执行时填的变量(脚本里有 `MAC_TS_IP` 自动取 + git-url 占位,执行时替换),非"TODO 待定"。其余 task 代码完整。

**3. 类型一致性**:`BGEEmbedder(batch_size, max_length)` / `Settings.embedder_batch_size/embedder_max_length` 在 Task 1 各处一致 ✓

**风险**:
- Task 2 部署依赖 mac Tailscale IP + docker 端口对 tesla-t4 可达(Step 1 验证;若不通改 docker-compose ports)
- tesla-t4 的 torch cuda 版本(可能有 cu126 venv)要兼容 FlagEmbedding;Step 2 装依赖若冲突,改用现有 torch venv + 只装 FlagEmbedding
- corpus rsync ~2GB(首次),后续增量
- max_length 1024 对代码 chunk(~600 token)够;长 markdown 文档若截断影响质量,可调回 8192 + batch 16
