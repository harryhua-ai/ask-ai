"""每日 LLM 调用预算熔断。

Phase 1:内存计数器(单 worker)。超阈值拒绝新请求并返回降级响应。
多 worker / 持久化场景 Phase 2 迁移至 Redis 或 Postgres。
"""

import logging
import threading
from dataclasses import dataclass
from datetime import date

import tiktoken

logger = logging.getLogger(__name__)
_enc = tiktoken.get_encoding("cl100k_base")


@dataclass(frozen=True)
class BudgetConfig:
    """预算配置(不可变)。"""

    daily_request_limit: int = 500
    daily_token_limit: int = 2_000_000


@dataclass
class _Counter:
    """单日计数器。"""

    requests: int = 0
    tokens: int = 0


def estimate_tokens(text: str) -> int:
    """用 cl100k_base 估算 token 数(与 Task 9 chunking 同编码;DeepSeek 实际 tokenizer 的合理近似)。"""
    return len(_enc.encode(text))


class BudgetLimiter:
    """每日 LLM 调用预算熔断,保护计费额度。

    Phase 1:内存计数器(单 worker)。超阈值拒绝新请求并返回降级响应。
    多 worker / 持久化场景 Phase 2 迁移至 Redis 或 Postgres。
    """

    def __init__(self, config: BudgetConfig, *, _now=None) -> None:
        self._config = config
        self._now = _now or date.today
        self._current_date: date = self._now()
        self._counter = _Counter()
        self._lock = threading.Lock()

    def _maybe_reset(self) -> None:
        today = self._now()
        if today != self._current_date:
            self._current_date = today
            self._counter = _Counter()

    def check_and_reserve(self, estimated_tokens: int) -> bool:
        """检查并预扣预算;成功返回 True,超限返回 False。"""
        with self._lock:
            self._maybe_reset()
            if self._counter.requests >= self._config.daily_request_limit:
                logger.warning("预算熔断:日请求数达上限 %d", self._config.daily_request_limit)
                return False
            if self._counter.tokens + estimated_tokens > self._config.daily_token_limit:
                logger.warning("预算熔断:日 token 估算达上限 %d", self._config.daily_token_limit)
                return False
            self._counter.requests += 1
            self._counter.tokens += estimated_tokens
            return True

    def snapshot(self) -> dict:
        """返回当前计数快照(用于监控/调试端点)。"""
        with self._lock:
            self._maybe_reset()
            return {
                "date": self._current_date.isoformat(),
                "requests": self._counter.requests,
                "tokens": self._counter.tokens,
                "daily_request_limit": self._config.daily_request_limit,
                "daily_token_limit": self._config.daily_token_limit,
            }
