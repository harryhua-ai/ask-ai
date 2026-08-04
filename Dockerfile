# syntax=docker/dockerfile:1.7
# ask-ai GPU 镜像(backend + sync worker 共用,不同 entrypoint)
#
# 多阶段构建:
#   1. builder:基于 cuda + uv 装依赖(产出 .venv)
#   2. runtime:拷贝 .venv + 代码,精简(无构建工具链)
#
# GPU:CUDA 12.8 + cu128 torch(与 tesla-t4 torch 2.11+cu128 一致)
# 模型/语料不打进镜像,容器启动时挂载(决策 2/3)
#
# 镜像 tag 由 GitHub Actions 打(ghcr.io/<owner>/ask-ai:<sha>),tesla-t4 docker pull 更新。

# ---------- builder ----------
FROM nvidia/cuda:12.8.0-cudnn-runtime-ubuntu24.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 基础工具 + Python 3.12(tree-sitter grammars 需 build-essential;git for clone)
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv python3-pip \
        build-essential git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# uv(快速依赖安装,锁 uv.lock)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    ln -s /root/.local/bin/uv /usr/local/bin/uv

WORKDIR /app

# 先拷依赖清单(利用层缓存:代码变不重装依赖)
COPY pyproject.toml uv.lock ./

# uv sync 装依赖到 .venv(--frozen 锁版本,--no-dev 不装测试工具)
RUN uv sync --frozen --no-dev

# ---------- runtime ----------
FROM nvidia/cuda:12.8.0-cudnn-runtime-ubuntu24.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    HF_HOME=/models \
    TRANSFORMERS_OFFLINE=1

# 运行时最小依赖:git(sync 拉 corpus)+ ca-certificates(HTTPS)+ curl(健康检查)
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv \
        git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 从 builder 拷依赖(.venv)
COPY --from=builder /app/.venv /app/.venv

# 拷代码(构建时上下文,Actions 里 checkout)
COPY backend/ ./backend/
COPY scripts/ ./scripts/
COPY config/ ./config/

# 默认 entrypoint:backend(uvicorn)
# sync worker 用 docker-compose command 覆盖
EXPOSE 8000

# 健康检查(backend)
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT []
CMD ["/app/.venv/bin/python", "-m", "backend.main"]