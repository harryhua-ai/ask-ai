# syntax=docker/dockerfile:1.7
# ask-ai GPU 镜像(backend + sync worker 共用,不同 entrypoint)
#
# 多阶段构建:

#   2. builder:cuda + uv 装依赖(torch cu128)

#
# GPU:CUDA 12.8 + cu128 torch(与 tesla-t4 driver 575/CUDA 12.9 兼容)
# 模型/语料不打进镜像,容器启动时挂载(决策 2/3)

# ---------- python builder ----------
FROM nvidia/cuda:12.8.0-cudnn-runtime-ubuntu24.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv python3-pip \
        build-essential git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    ln -s /root/.local/bin/uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./

# uv sync 装依赖(--frozen 锁版本,--no-dev)
RUN uv sync --frozen --no-dev

# 强制重装 torch cu128(匹配 tesla-t4 CUDA 12.9 driver)
# cu128 最新 torch 2.11.0(pypi 默认拉 cu130 需 driver 580+,tesla-t4 575 → CUDA unavailable)
RUN uv pip install torch --index-url https://download.pytorch.org/whl/cu128 --reinstall-package torch

# ---------- runtime ----------
FROM nvidia/cuda:12.8.0-cudnn-runtime-ubuntu24.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    HF_HOME=/models \
    TRANSFORMERS_OFFLINE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv \
        git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3.12 /usr/bin/python3

WORKDIR /app

# 从 builder 拷依赖(.venv)
COPY --from=builder /app/.venv /app/.venv

COPY admin/dist /app/admin/dist

# 拷代码
COPY backend/ ./backend/
COPY scripts/ ./scripts/
COPY config/ ./config/

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT []
CMD ["/app/.venv/bin/python", "-m", "backend.main"]
