"""共享嵌入运行时的 sync 侧客户端(RemoteSyncEmbedder)。

执行契约(Hardware-Aware Model Runtime §6/§14):
- sync_embedding 不再自载模型:经内部嵌入端点消费 backend 的**单一驻留**
  嵌入实例(同模型+同 GPU → 至多一个活跃运行时);
- GPU→CPU 单向回退在服务端完成(同模型、语义不变);本句柄把服务端设备
  真相镜像进既有 SyncEmbedderHandle 遥测面(W2:gpu/cpu/gpu_to_cpu +
  cpu_batches/cpu_docs),不产生第二回退权威;
- 有界:客户端按 EMBEDDER_BATCH_SIZE 主动切片顺序发送(Issue #72 矫正:
  此前整列表单请求,拼平规模 > 限值即 422、整代零激活),无无界队列/重试
  (run 级上限沿用 sync_requests);服务端 422 仍是最后防线,契约不变。
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

import numpy as np

from backend.embedder.fallback import SyncEmbedderHandle
from backend.runtime.internal_auth import internal_api_token

logger = logging.getLogger(__name__)

# 单一派生权威:内部令牌只在 runtime.internal_auth 定义,此处仅别名复用,
# 杜绝两侧推导漂移。
internal_token = internal_api_token
_DEFAULT_BASE_URL = "http://backend:8000"
_REQUEST_TIMEOUT_SECONDS = 600


class _RemoteEmbedderClient:
    """内部嵌入端点的最小 HTTP 客户端(同步阻塞;由调用方线程池驱动)。

    切批契约(Issue #72):按 ``batch_size`` 把输入切为连续片,顺序 POST、
    按输入序拼接 —— 单请求条数永不越服务端限(生产 16);任一片失败即
    整体失败(无部分结果、无客户端重试),服务端错误如实透传并附切片
    上下文;设备真相逐片合并(单向 GPU→CPU,绝不回退 GPU)。
    """

    def __init__(
        self, base_url: str, token: str, dimension: int = 1024, batch_size: int = 12
    ) -> None:
        if int(batch_size) < 1:
            raise ValueError(f"batch_size must be >= 1, got {batch_size}")
        self.base_url = base_url.rstrip("/")
        self._token = token
        self.dimension = dimension
        # 与内部嵌入端点同源(settings.embedder_batch_size);缺省取 Settings
        # 权威缺省(config.py),保证无 env 直构造时也不越同配置服务端。
        self.batch_size = int(batch_size)
        self.execution_device = "gpu"
        self.fallback_reason: str | None = None
        self.fallback_detail: str | None = None

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        if not texts:
            return []
        total = len(texts)
        slice_count = (total + self.batch_size - 1) // self.batch_size
        vectors: list[np.ndarray] = []
        for slice_index, start in enumerate(range(0, total, self.batch_size), start=1):
            batch = list(texts[start : start + self.batch_size])
            vectors.extend(self._embed_slice(batch, slice_index, slice_count))
        return vectors

    def _embed_slice(
        self, batch: list[str], slice_index: int, slice_count: int
    ) -> list[np.ndarray]:
        payload = json.dumps({"texts": batch}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/internal/embeddings",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-Internal-Token": self._token,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT_SECONDS) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                detail = (exc.read() or b"").decode("utf-8", errors="replace")[:300]
            except Exception:  # noqa: BLE001 - fp 可能为 None
                detail = str(exc)
            raise RuntimeError(
                f"internal embeddings HTTP {exc.code}"
                f" (slice {slice_index}/{slice_count}, items={len(batch)}): {detail}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(
                f"internal embeddings unreachable"
                f" (slice {slice_index}/{slice_count}, items={len(batch)}): {exc}"
            ) from exc
        vectors = [np.asarray(v, dtype=np.float32) for v in body.get("vectors", [])]
        if len(vectors) != len(batch):
            raise RuntimeError(
                f"internal embeddings (slice {slice_index}/{slice_count})"
                f" returned {len(vectors)} vectors, expected {len(batch)}"
            )
        # 服务端设备真相镜像(含服务端已完成的单向 GPU→CPU 回退;条件自带
        # 幂等性:一旦 CPU,后续片的 gpu 报告不会把真相拉回)
        device = body.get("execution_device", "gpu")
        if device == "cpu" and self.execution_device != "cpu":
            self.execution_device = "cpu"
            self.fallback_reason = body.get("fallback_reason")
            self.fallback_detail = body.get("fallback_detail")
            if self.fallback_reason:
                logger.warning(
                    "backend 共享嵌入运行时已回退 CPU(reason=%s);sync 后续批次走 CPU",
                    self.fallback_reason,
                )
            else:
                logger.info("backend 嵌入运行时为原生 CPU 常驻(无回退事实);sync 经内部端点消费")
        return vectors


class RemoteSyncEmbedder(SyncEmbedderHandle):
    """实现 Embedder 协议的 sync 句柄:远端共享运行时 + 既有遥测面。

    继承 :class:`SyncEmbedderHandle` 以保持 sync.py/IngestionPipeline 的
    isinstance 遥测契约(activity_snapshot / cpu_counters /
    telemetry_execution_device 等);本地 fallback_to_cpu 在远端模式下永不
    触发(服务端已完成单向回退),若被调用则如实报终止错误。
    """

    def __init__(self, client: _RemoteEmbedderClient) -> None:
        super().__init__(
            client,
            runtime_device="gpu" if client.execution_device == "gpu" else "cpu",
            cpu_factory=lambda: client,  # 回退已服务端化;此工厂不应被调用
            cpu_fallback_enabled=False,
        )
        self._client = client

    @property
    def dimension(self) -> int:
        return self._client.dimension

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        self._embedding_attempts += 1
        vectors = self._client.embed(texts)
        if self._client.execution_device == "cpu":
            if self._runtime_device != "cpu":
                self._runtime_device = "cpu"
                # 原生 CPU 常驻(服务端无回退事实)≠ 回退:仅当服务端给出
                # fallback_reason 才记回退,绝不臆造 cuda_oom(否则 CPU 部署
                # 的每次同步都会被遥测误报为 gpu_to_cpu)。
                if self._client.fallback_reason:
                    self._fallback_attempted = True
                    self._fallback_reason = self._client.fallback_reason
                    self._fallback_detail = self._client.fallback_detail
            self.record_cpu_batch(len(texts))
        return vectors


def build_remote_sync_embedder(settings) -> RemoteSyncEmbedder:
    """构造共享运行时客户端句柄(sync.py 的 build_sync_embedder 新实现)。

    切批上界取同一 Settings 权威(settings.embedder_batch_size,与内部
    嵌入端点同源同值;生产 compose 对 backend/sync 等服务注入同一值)。
    """
    base_url = getattr(settings, "internal_api_base_url", None) or _DEFAULT_BASE_URL
    client = _RemoteEmbedderClient(
        base_url=base_url,
        token=internal_token(settings.jwt_secret),
        batch_size=int(settings.embedder_batch_size),
    )
    return RemoteSyncEmbedder(client)
