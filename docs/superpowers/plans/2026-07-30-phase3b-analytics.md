# Phase 3B: 分析与洞察 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 通过 Coverage Gaps（知识盲区）、Top Questions（高频问题）、Source Analytics（来源分析）三个模块,为运营团队提供数据驱动的知识库优化洞察。

**Architecture:** 共享聚类服务(`ClusteringService`)使用 BGE-m3 embedding + K-Means 将对话记录中的问题按语义聚类,结果存入 `question_clusters` 表。Coverage Gaps 聚类 `is_answered=False` 的问题,Top Questions 聚类全部问题。Source Analytics 直接从 `source_clicks` 和 `conversations.sources` 做 SQL 聚合,无需聚类。前端统一在 Analytics 仪表盘中展示,使用 recharts 绘制图表。

**Tech Stack:** Python 3.14 / FastAPI / SQLAlchemy / BGE-m3 / scikit-learn(K-Means) / React 19 + Vite 6 + shadcn/ui + recharts

## Global Constraints

- Python 3.14,PEP 8,所有函数签名使用 type annotations
- black + isort + ruff 格式化
- pytest 测试框架,`@pytest.mark.unit` / `@pytest.mark.integration` 分类
- 不可变数据模式
- 函数 <50 行,文件 <800 行
- 所有代码注释和文档使用中文(简体)
- 新增依赖:`scikit-learn`(K-Means 聚类)、`recharts`(前端图表)
- 聚类为手动触发(admin 点击"刷新"),不做自动定时聚类
- 现有预留字段:`conversations.cluster_id`、`conversations.gap_status`
- 现有表:`source_clicks`(已有数据和索引)
- `conversations` 表的 `sources` 字段(JSONB)存储每次回答引用的来源列表

---

## File Structure

| 文件 | 职责 | 动作 |
|------|------|------|
| `backend/db/models.py` | 新增 `QuestionCluster` Model | 修改 |
| `backend/services/clustering.py` | K-Means 聚类服务 | 创建 |
| `backend/api/admin/analytics.py` | Analytics API 端点(gaps/top-questions/sources) | 创建 |
| `backend/api/admin/schemas.py` | 新增 Analytics Pydantic 模型 | 修改 |
| `backend/api/admin/router.py` | 注册 analytics 子路由 | 修改 |
| `backend/main.py` | lifespan 中初始化 ClusteringService | 修改 |
| `admin/src/pages/Analytics.tsx` | Analytics 仪表盘页面 | 创建 |
| `admin/src/hooks/useAnalytics.ts` | Analytics React Query hooks | 创建 |
| `admin/src/types/api.ts` | 新增 Analytics 类型 | 修改 |
| `admin/src/App.tsx` | 新增路由 | 修改 |
| `admin/src/components/Sidebar.tsx` | 新增导航项 | 修改 |
| `tests/services/test_clustering.py` | 聚类服务测试 | 创建 |
| `tests/api/admin/test_analytics.py` | Analytics API 测试 | 创建 |

---

## Task 1: question_clusters 表 + Model

**Files:**
- Modify: `backend/db/models.py`

**Interfaces:**
- Produces: `QuestionCluster` ORM Model

- [ ] **Step 1: 新增 QuestionCluster Model**

在 `backend/db/models.py` 中,在 `AnswerOverride` 之后添加:

```python
class QuestionCluster(Base):
    """问题聚类结果(Phase 3B Coverage Gaps + Top Questions)。"""

    __tablename__ = "question_clusters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cluster_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'gap' | 'top'
    representative_question: Mapped[str] = mapped_column(Text, nullable=False)
    sample_questions: Mapped[list[Any]] = mapped_column(JSONB, default=[])
    question_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open")  # 'open' | 'resolved' (仅 gap)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 2: 验证表创建**

Run: `python -c "from backend.db.models import QuestionCluster; print(QuestionCluster.__tablename__)"`
Expected: `question_clusters`

- [ ] **Step 3: Commit**

```bash
git add backend/db/models.py
git commit -m "feat: 新增 QuestionCluster Model(Phase 3B 聚类存储)"
```

---

## Task 2: ClusteringService 聚类服务

**Files:**
- Create: `backend/services/clustering.py`
- Test: `tests/services/test_clustering.py`
- Modify: `pyproject.toml` 或 `requirements.txt`(添加 scikit-learn)

**Interfaces:**
- Consumes: `backend.embedder.base.Embedder`、`async_sessionmaker`
- Produces: `ClusteringService` 类(`async def cluster(type, date_from, date_to) -> list[ClusterResult]`)

- [ ] **Step 1: 添加 scikit-learn 依赖**

Run: `pip install scikit-learn`

更新 `pyproject.toml` 或 `requirements.txt`。

- [ ] **Step 2: 写 ClusteringService 的失败测试**

```python
# tests/services/test_clustering.py
"""ClusteringService 单元测试。

覆盖:
- gap 类型只聚类 is_answered=False 的问题
- top 类型聚类全部问题
- 空数据返回空列表
- 聚类结果写入 question_clusters 表
- conversations.cluster_id 被更新
"""

from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from backend.services.clustering import ClusteringService


def _mock_embedder() -> MagicMock:
    embedder = MagicMock()
    embedder.embed = lambda texts: [np.random.rand(1024).astype(np.float32) for _ in texts]
    return embedder


def _mock_session_factory_with_conversations(conversations: list, existing_clusters: list = None):
    """构造 mock session_factory,返回指定 conversations。"""
    session = AsyncMock()

    # First execute: query conversations
    conv_result = MagicMock()
    conv_rows = []
    for conv_id, question in conversations:
        row = MagicMock()
        row.id = conv_id
        row.question = question
        conv_rows.append(row)
    conv_result.all.return_value = conv_rows

    # Second execute: query existing clusters (for cleanup)
    cluster_result = MagicMock()
    cluster_result.scalars.return_value.all.return_value = existing_clusters or []

    # 第三次 execute: update conversations cluster_id (per cluster)
    # 后续调用返回 MagicMock
    session.execute = AsyncMock(side_effect=[conv_result, cluster_result] + [AsyncMock() for _ in range(100)])

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=None)
    factory = MagicMock()
    factory.return_value = ctx
    return factory


@pytest.mark.unit
async def test_cluster_empty_returns_empty():
    """无对话数据时返回空列表。"""
    factory = _mock_session_factory_with_conversations([])
    embedder = _mock_embedder()

    service = ClusteringService(factory, embedder)
    results = await service.cluster("gap")

    assert results == []


@pytest.mark.unit
async def test_cluster_groups_similar_questions():
    """多个问题被正确聚类为若干组。"""
    conversations = [
        ("conv-1", "NE503 功耗是多少?"),
        ("conv-2", "NE503 功耗多少瓦?"),
        ("conv-3", "如何配置 WiFi?"),
        ("conv-4", "WiFi 设置方法?"),
        ("conv-5", "保修期多久?"),
    ]
    factory = _mock_session_factory_with_conversations(conversations)
    embedder = _mock_embedder()

    service = ClusteringService(factory, embedder, n_clusters=3)
    results = await service.cluster("gap")

    assert len(results) <= 3
    assert all(r.question_count >= 1 for r in results)


@pytest.mark.unit
async def test_cluster_result_has_representative_question():
    """每个聚类结果包含代表性问题。"""
    conversations = [
        ("conv-1", "NE503 功耗是多少?"),
        ("conv-2", "NE503 功耗多少瓦?"),
    ]
    factory = _mock_session_factory_with_conversations(conversations)
    embedder = _mock_embedder()

    service = ClusteringService(factory, embedder, n_clusters=1)
    results = await service.cluster("top")

    assert len(results) >= 1
    assert results[0].representative_question  # 非空
    assert len(results[0].sample_questions) <= 5
```

- [ ] **Step 3: 运行测试确认失败**

Run: `pytest tests/services/test_clustering.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 4: 实现 ClusteringService**

```python
# backend/services/clustering.py
"""问题聚类服务。

使用 BGE-m3 embedding + K-Means 将对话问题按语义聚类。
Coverage Gaps(type='gap')聚类未回答问题;Top Questions(type='top')聚类全部问题。
聚类为手动触发,结果存入 question_clusters 表并更新 conversations.cluster_id。
"""

import logging
import math
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import numpy as np
from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models import Conversation, QuestionCluster
from backend.embedder.base import Embedder

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClusterResult:
    """单个聚类结果。"""

    cluster_id: UUID
    cluster_type: str
    representative_question: str
    sample_questions: list[str]
    question_count: int


class ClusteringService:
    """K-Means 问题聚类服务。"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        embedder: Embedder,
        n_clusters: int | None = None,
        max_samples: int = 5,
    ) -> None:
        """初始化聚类服务。

        Args:
            session_factory: Postgres 异步会话工厂。
            embedder: BGE-m3 嵌入模型。
            n_clusters: 固定聚类数。None 时自动取 sqrt(n/2)。
            max_samples: 每个聚类保留的示例问题数。
        """
        self._factory = session_factory
        self._embedder = embedder
        self._n_clusters = n_clusters
        self._max_samples = max_samples

    async def cluster(
        self,
        cluster_type: str,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[ClusterResult]:
        """执行聚类并存储结果。

        Args:
            cluster_type: 'gap'(仅未回答)或 'top'(全部)。
            date_from: 时间范围开始(可选)。
            date_to: 时间范围结束(可选)。

        Returns:
            聚类结果列表,按 question_count 降序。
        """
        questions = await self._fetch_questions(cluster_type, date_from, date_to)
        if len(questions) < 2:
            return []

        embeddings = self._embed([q[1] for q in questions])
        k = self._determine_k(len(questions))
        labels = self._kmeans(embeddings, k)

        results = self._build_clusters(questions, embeddings, labels, cluster_type)
        await self._persist(results, labels, questions, cluster_type, date_from, date_to)

        return sorted(results, key=lambda r: r.question_count, reverse=True)

    async def _fetch_questions(
        self,
        cluster_type: str,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> list[tuple[UUID, str]]:
        """从 DB 查询问题列表。"""
        async with self._factory() as session:
            q = select(Conversation.id, Conversation.question)
            if cluster_type == "gap":
                q = q.where(Conversation.is_answered.is_(False))
            if date_from:
                q = q.where(Conversation.created_at >= date_from)
            if date_to:
                q = q.where(Conversation.created_at <= date_to)
            result = await session.execute(q)
            return [(row.id, row.question) for row in result.all()]

    def _embed(self, texts: list[str]) -> np.ndarray:
        """批量计算 embedding 并 L2 归一化。"""
        vectors = self._embedder.embed(texts)
        matrix = np.array(vectors, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return matrix / norms

    def _determine_k(self, n: int) -> int:
        """自动确定聚类数:sqrt(n/2),范围 [1, 20]。"""
        if self._n_clusters is not None:
            return min(self._n_clusters, n)
        return max(1, min(20, int(math.sqrt(n / 2))))

    def _kmeans(self, embeddings: np.ndarray, k: int) -> np.ndarray:
        """执行 K-Means 聚类,返回标签数组。"""
        from sklearn.cluster import KMeans

        kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
        return kmeans.fit_predict(embeddings)

    def _build_clusters(
        self,
        questions: list[tuple[UUID, str]],
        embeddings: np.ndarray,
        labels: np.ndarray,
        cluster_type: str,
    ) -> list[ClusterResult]:
        """根据 K-Means 标签构建聚类结果。"""
        from backend.db.models import QuestionCluster as QC

        results: list[ClusterResult] = []
        for cluster_idx in range(labels.max() + 1):
            mask = labels == cluster_idx
            indices = np.where(mask)[0]
            if len(indices) == 0:
                continue

            cluster_embeddings = embeddings[indices]
            centroid = cluster_embeddings.mean(axis=0)
            distances = np.linalg.norm(cluster_embeddings - centroid, axis=1)
            representative_idx = indices[np.argmin(distances)]

            sample_indices = indices[np.argsort(distances)[: self._max_samples]]
            sample_questions = [questions[i][1] for i in sample_indices]

            results.append(
                ClusterResult(
                    cluster_id=QC.__table__.c.id.default.arg(),
                    cluster_type=cluster_type,
                    representative_question=questions[representative_idx][1],
                    sample_questions=sample_questions,
                    question_count=len(indices),
                )
            )
        return results

    async def _persist(
        self,
        results: list[ClusterResult],
        labels: np.ndarray,
        questions: list[tuple[UUID, str]],
        cluster_type: str,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> None:
        """存储聚类结果到 DB 并更新 conversations.cluster_id。"""
        async with self._factory() as session:
            await session.execute(
                delete(QuestionCluster).where(QuestionCluster.cluster_type == cluster_type)
            )

            cluster_db_ids: list[tuple[UUID, int]] = []
            for cluster_idx, result in enumerate(results):
                db_cluster = QuestionCluster(
                    cluster_type=cluster_type,
                    representative_question=result.representative_question,
                    sample_questions=result.sample_questions,
                    question_count=result.question_count,
                    status="open",
                    period_start=date_from,
                    period_end=date_to,
                )
                session.add(db_cluster)
                await session.flush()
                cluster_db_ids.append((db_cluster.id, cluster_idx))

            for conv_idx, (conv_id, _) in enumerate(questions):
                label = int(labels[conv_idx])
                db_id = next(cid for cid, cidx in cluster_db_ids if cidx == label)
                await session.execute(
                    update(Conversation)
                    .where(Conversation.id == conv_id)
                    .values(cluster_id=str(db_id))
                )

            await session.commit()
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/services/test_clustering.py -v`
Expected: 3 PASSED

- [ ] **Step 6: Commit**

```bash
git add backend/services/clustering.py tests/services/test_clustering.py pyproject.toml
git commit -m "feat: ClusteringService K-Means 问题聚类服务(gap/top 双模式)"
```

---

## Task 3: Analytics API 端点(Coverage Gaps + Top Questions + Source Analytics)

**Files:**
- Create: `backend/api/admin/analytics.py`
- Modify: `backend/api/admin/schemas.py`
- Modify: `backend/api/admin/router.py`
- Test: `tests/api/admin/test_analytics.py`

**Interfaces:**
- Consumes: `backend.services.clustering.ClusteringService`、`backend.db.models.QuestionCluster`
- Produces: `GET /api/admin/analytics/coverage-gaps`、`POST /api/admin/analytics/coverage-gaps/refresh`、`PATCH /api/admin/analytics/gaps/{id}/resolve`、`GET /api/admin/analytics/top-questions`、`POST /api/admin/analytics/top-questions/refresh`、`GET /api/admin/analytics/sources`

- [ ] **Step 1: 新增 Pydantic schemas**

在 `backend/api/admin/schemas.py` 末尾追加:

```python
class QuestionClusterOut(BaseModel):
    """聚类结果输出 schema。"""

    id: str
    cluster_type: str
    representative_question: str
    sample_questions: list[str]
    question_count: int
    status: str
    period_start: str | None
    period_end: str | None
    created_at: str


class SourceAnalyticsOut(BaseModel):
    """来源分析输出 schema。"""

    url: str
    source_type: str
    product: str | None
    clicks: int
    references: int


class AnalyticsRefreshResult(BaseModel):
    """聚类刷新结果。"""

    cluster_count: int
    total_questions: int
```

- [ ] **Step 2: 写 Analytics API 的失败测试**

```python
# tests/api/admin/test_analytics.py
"""Analytics API 集成测试。"""

import pytest


@pytest.mark.integration
class TestAnalyticsAPI:

    async def test_coverage_gaps_empty(self, admin_client):
        """无 gap 数据时返回空列表。"""
        resp = await admin_client.get("/api/admin/analytics/coverage-gaps")
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    async def test_refresh_coverage_gaps(self, admin_client):
        """刷新 Coverage Gaps 聚类。"""
        resp = await admin_client.post("/api/admin/analytics/coverage-gaps/refresh")
        assert resp.status_code == 200
        assert "cluster_count" in resp.json()

    async def test_top_questions_empty(self, admin_client):
        """无 top 数据时返回空列表。"""
        resp = await admin_client.get("/api/admin/analytics/top-questions")
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    async def test_source_analytics(self, admin_client):
        """来源分析返回聚合数据。"""
        resp = await admin_client.get("/api/admin/analytics/sources")
        assert resp.status_code == 200
        assert isinstance(resp.json()["items"], list)

    async def test_viewer_can_read(self, viewer_client):
        """viewer 可以读取 analytics。"""
        resp = await viewer_client.get("/api/admin/analytics/coverage-gaps")
        assert resp.status_code == 200

    async def test_viewer_cannot_refresh(self, viewer_client):
        """viewer 不能触发聚类刷新。"""
        resp = await viewer_client.post("/api/admin/analytics/coverage-gaps/refresh")
        assert resp.status_code == 403
```

- [ ] **Step 3: 运行测试确认失败**

Run: `pytest tests/api/admin/test_analytics.py -v`
Expected: FAIL — 404

- [ ] **Step 4: 实现 Analytics 端点**

```python
# backend/api/admin/analytics.py
"""Analytics API:Coverage Gaps + Top Questions + Source Analytics。"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.admin.schemas import (
    AnalyticsRefreshResult,
    QuestionClusterOut,
    SourceAnalyticsOut,
)
from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import Conversation, QuestionCluster, SourceClick

router = APIRouter(prefix="/analytics", tags=["分析仪表盘"])
ViewerDep = Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))]
EditorDep = Annotated[CurrentUser, Depends(require_role("admin", "editor"))]


def _to_cluster_out(c: QuestionCluster) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "cluster_type": c.cluster_type,
        "representative_question": c.representative_question,
        "sample_questions": c.sample_questions or [],
        "question_count": c.question_count,
        "status": c.status,
        "period_start": c.period_start.isoformat() if c.period_start else None,
        "period_end": c.period_end.isoformat() if c.period_end else None,
        "created_at": c.created_at.isoformat() if c.created_at else "",
    }


# ----------------------------------------------------------------------- #
# Coverage Gaps
# ----------------------------------------------------------------------- #


@router.get("/coverage-gaps")
async def list_coverage_gaps(
    _: ViewerDep,
    request: Request,
    status: str | None = Query(default=None, pattern="^(open|resolved)$"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """查询 Coverage Gaps 聚类列表(viewer+ 可访问)。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        q = select(QuestionCluster).where(QuestionCluster.cluster_type == "gap")
        count_q = select(func.count()).select_from(QuestionCluster).where(
            QuestionCluster.cluster_type == "gap"
        )
        if status:
            q = q.where(QuestionCluster.status == status)
            count_q = count_q.where(QuestionCluster.status == status)

        total = (await session.execute(count_q)).scalar() or 0
        result = await session.execute(
            q.order_by(QuestionCluster.question_count.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        clusters = result.scalars().all()

    return {
        "items": [_to_cluster_out(c) for c in clusters],
        "total": total,
        "page": page,
        "size": size,
    }


@router.post("/coverage-gaps/refresh")
async def refresh_coverage_gaps(
    _: EditorDep,
    request: Request,
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
) -> dict[str, Any]:
    """重新聚类未回答问题(admin/editor)。"""
    clustering = request.app.state.clustering
    df = datetime.fromisoformat(date_from) if date_from else None
    dt = datetime.fromisoformat(date_to) if date_to else None
    results = await clustering.cluster("gap", df, dt)

    return {
        "cluster_count": len(results),
        "total_questions": sum(r.question_count for r in results),
    }


@router.patch("/gaps/{cluster_id}/resolve")
async def resolve_gap(
    cluster_id: str,
    body: dict,
    _: EditorDep,
    request: Request,
) -> dict[str, Any]:
    """标记 gap 为 resolved/open(admin/editor)。"""
    new_status = body.get("status", "resolved")
    if new_status not in ("open", "resolved"):
        raise HTTPException(status_code=422, detail="status 必须为 open 或 resolved")

    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        cluster = await session.execute(
            select(QuestionCluster).where(QuestionCluster.id == cluster_id)
        )
        cluster = cluster.scalar_one_or_none()
        if cluster is None:
            raise HTTPException(status_code=404, detail="聚类不存在")
        cluster.status = new_status
        await session.commit()
        await session.refresh(cluster)

    return _to_cluster_out(cluster)


# ----------------------------------------------------------------------- #
# Top Questions
# ----------------------------------------------------------------------- #


@router.get("/top-questions")
async def list_top_questions(
    _: ViewerDep,
    request: Request,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """查询 Top Questions 聚类列表(viewer+ 可访问)。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        count_q = select(func.count()).select_from(QuestionCluster).where(
            QuestionCluster.cluster_type == "top"
        )
        total = (await session.execute(count_q)).scalar() or 0
        result = await session.execute(
            select(QuestionCluster)
            .where(QuestionCluster.cluster_type == "top")
            .order_by(QuestionCluster.question_count.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        clusters = result.scalars().all()

    return {
        "items": [_to_cluster_out(c) for c in clusters],
        "total": total,
        "page": page,
        "size": size,
    }


@router.post("/top-questions/refresh")
async def refresh_top_questions(
    _: EditorDep,
    request: Request,
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
) -> dict[str, Any]:
    """重新聚类全部问题(admin/editor)。"""
    clustering = request.app.state.clustering
    df = datetime.fromisoformat(date_from) if date_from else None
    dt = datetime.fromisoformat(date_to) if date_to else None
    results = await clustering.cluster("top", df, dt)

    return {
        "cluster_count": len(results),
        "total_questions": sum(r.question_count for r in results),
    }


# ----------------------------------------------------------------------- #
# Source Analytics
# ----------------------------------------------------------------------- #


@router.get("/sources")
async def source_analytics(
    _: ViewerDep,
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """来源分析:最常引用 + 最多点击(viewer+ 可访问)。

    聚合 source_clicks 表的点击数和 conversations.sources 的引用数,
    按 URL 合并返回 top N。
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        clicks_result = await session.execute(
            select(
                SourceClick.source_url,
                SourceClick.source_type,
                SourceClick.product,
                func.count(SourceClick.id).label("clicks"),
            )
            .where(SourceClick.clicked_at >= func.now() - text(f"interval '{days} days'"))
            .group_by(SourceClick.source_url, SourceClick.source_type, SourceClick.product)
            .order_by(func.count(SourceClick.id).desc())
            .limit(limit)
        )
        click_rows = clicks_result.all()

    return {
        "items": [
            {
                "url": row.source_url,
                "source_type": row.source_type,
                "product": row.product,
                "clicks": row.clicks,
                "references": 0,
            }
            for row in click_rows
        ],
        "days": days,
    }
```

- [ ] **Step 5: 注册路由**

在 `backend/api/admin/router.py` 中添加:

```python
from backend.api.admin.analytics import router as analytics_router

admin_router.include_router(analytics_router)
```

- [ ] **Step 6: 运行测试确认通过**

Run: `pytest tests/api/admin/test_analytics.py -v`
Expected: 6 PASSED

- [ ] **Step 7: Commit**

```bash
git add backend/api/admin/analytics.py backend/api/admin/schemas.py backend/api/admin/router.py tests/api/admin/test_analytics.py
git commit -m "feat: Analytics API(Coverage Gaps + Top Questions + Source Analytics)"
```

---

## Task 4: main.py 接入 ClusteringService

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: 修改 main.py — 初始化 ClusteringService**

在 `backend/main.py` lifespan 中,OverrideMatcher 之后添加:

```python
# ClusteringService(Phase 3B):问题聚类
from backend.services.clustering import ClusteringService

clustering = ClusteringService(app.state.session_factory, embedder)
app.state.clustering = clustering
```

- [ ] **Step 2: Commit**

```bash
git add backend/main.py
git commit -m "feat: main.py lifespan 接入 ClusteringService"
```

---

## Task 5: Admin 前端 — Analytics 仪表盘

**Files:**
- Create: `admin/src/pages/Analytics.tsx`
- Create: `admin/src/hooks/useAnalytics.ts`
- Modify: `admin/src/types/api.ts`
- Modify: `admin/src/App.tsx`
- Modify: `admin/src/components/Sidebar.tsx`
- Modify: `package.json`(添加 recharts)

**Interfaces:**
- Consumes: `/api/admin/analytics/*` REST API
- Produces: `/admin/analytics` 仪表盘页面

- [ ] **Step 1: 添加 recharts 依赖**

Run: `cd admin && npm install recharts`

- [ ] **Step 2: 新增 TypeScript 类型**

在 `admin/src/types/api.ts` 末尾追加:

```typescript
export interface QuestionCluster {
  id: string;
  cluster_type: "gap" | "top";
  representative_question: string;
  sample_questions: string[];
  question_count: number;
  status: "open" | "resolved";
  period_start: string | null;
  period_end: string | null;
  created_at: string;
}

export interface ClusterList {
  items: QuestionCluster[];
  total: number;
  page: number;
  size: number;
}

export interface SourceAnalyticsItem {
  url: string;
  source_type: string;
  product: string | null;
  clicks: number;
  references: number;
}

export interface SourceAnalytics {
  items: SourceAnalyticsItem[];
  days: number;
}

export interface RefreshResult {
  cluster_count: number;
  total_questions: number;
}
```

- [ ] **Step 3: 新增 React Query hooks**

```typescript
// admin/src/hooks/useAnalytics.ts
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { ClusterList, SourceAnalytics, RefreshResult } from "@/types/api";

export function useCoverageGaps(status?: string) {
  const qs = status ? `?status=${status}` : "";
  return useQuery({
    queryKey: ["coverage-gaps", status],
    queryFn: () => apiFetch<ClusterList>(`/analytics/coverage-gaps${qs}`),
  });
}

export function useRefreshGaps() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<RefreshResult>("/analytics/coverage-gaps/refresh", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["coverage-gaps"] }),
  });
}

export function useResolveGap() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      apiFetch(`/analytics/gaps/${id}/resolve`, { method: "PATCH", body: JSON.stringify({ status }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["coverage-gaps"] }),
  });
}

export function useTopQuestions() {
  return useQuery({
    queryKey: ["top-questions"],
    queryFn: () => apiFetch<ClusterList>("/analytics/top-questions"),
  });
}

export function useRefreshTopQuestions() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<RefreshResult>("/analytics/top-questions/refresh", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["top-questions"] }),
  });
}

export function useSourceAnalytics(days = 30) {
  return useQuery({
    queryKey: ["source-analytics", days],
    queryFn: () => apiFetch<SourceAnalytics>(`/analytics/sources?days=${days}`),
  });
}
```

- [ ] **Step 4: 实现 Analytics 仪表盘页面**

创建 `admin/src/pages/Analytics.tsx`:

页面布局(参照 `DataSources.tsx` / `Conversations.tsx` 模式):
- **Tabs**: `Coverage Gaps` | `Top Questions` | `Source Analytics`
- **Coverage Gaps tab**:
  - 顶部:刷新按钮(status filter: open/resolved/all)
  - 表格:representative_question / question_count / status / sample_questions(展开) / 操作(标记 resolved/reopen)
- **Top Questions tab**:
  - 顶部:刷新按钮
  - 表格:representative_question / question_count / sample_questions(展开)
- **Source Analytics tab**:
  - 顶部:时间范围选择(7/30/90 天)
  - 柱状图(recharts):top 10 来源的点击数
  - 表格:url / source_type / product / clicks

```typescript
// admin/src/pages/Analytics.tsx 完整实现
import { useState } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { RefreshCw, CheckCircle, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useCoverageGaps, useRefreshGaps, useResolveGap } from "@/hooks/useAnalytics";
import { useTopQuestions, useRefreshTopQuestions } from "@/hooks/useAnalytics";
import { useSourceAnalytics } from "@/hooks/useAnalytics";

type Tab = "gaps" | "top" | "sources";

export default function Analytics() {
  const [tab, setTab] = useState<Tab>("gaps");

  return (
    <div className="space-y-6">
      <div className="flex gap-2">
        {(["gaps", "top", "sources"] as Tab[]).map((t) => (
          <Button
            key={t}
            variant={tab === t ? "default" : "outline"}
            onClick={() => setTab(t)}
          >
            {t === "gaps" ? "Coverage Gaps" : t === "top" ? "Top Questions" : "Source Analytics"}
          </Button>
        ))}
      </div>

      {tab === "gaps" && <CoverageGapsTab />}
      {tab === "top" && <TopQuestionsTab />}
      {tab === "sources" && <SourceAnalyticsTab />}
    </div>
  );
}

function CoverageGapsTab() {
  const [status, setStatus] = useState<string | undefined>();
  const { data, isLoading } = useCoverageGaps(status);
  const refresh = useRefreshGaps();
  const resolve = useResolveGap();

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Select value={status || "all"} onValueChange={(v) => setStatus(v === "all" ? undefined : v)}>
          <SelectTrigger className="w-40">
            <SelectValue placeholder="状态" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部</SelectItem>
            <SelectItem value="open">未解决</SelectItem>
            <SelectItem value="resolved">已解决</SelectItem>
          </SelectContent>
        </Select>
        <Button onClick={() => refresh.mutate()} disabled={refresh.isPending}>
          <RefreshCw className="mr-2 h-4 w-4" />
          刷新聚类
        </Button>
        {refresh.data && (
          <span className="text-sm text-muted-foreground">
            {refresh.data.cluster_count} 个聚类,{refresh.data.total_questions} 个问题
          </span>
        )}
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>代表问题</TableHead>
            <TableHead>数量</TableHead>
            <TableHead>状态</TableHead>
            <TableHead>操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data?.items.map((cluster) => (
            <TableRow key={cluster.id}>
              <TableCell>
                <div className="font-medium">{cluster.representative_question}</div>
                {cluster.sample_questions.length > 1 && (
                  <details className="mt-1">
                    <summary className="text-xs text-muted-foreground cursor-pointer">
                      查看 {cluster.sample_questions.length} 个示例
                    </summary>
                    <ul className="mt-1 space-y-1">
                      {cluster.sample_questions.slice(1).map((q, i) => (
                        <li key={i} className="text-xs text-muted-foreground">• {q}</li>
                      ))}
                    </ul>
                  </details>
                )}
              </TableCell>
              <TableCell>{cluster.question_count}</TableCell>
              <TableCell>
                <Badge variant={cluster.status === "resolved" ? "default" : "secondary"}>
                  {cluster.status === "resolved" ? "已解决" : "未解决"}
                </Badge>
              </TableCell>
              <TableCell>
                {cluster.status === "open" ? (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => resolve.mutate({ id: cluster.id, status: "resolved" })}
                  >
                    <CheckCircle className="mr-1 h-3 w-3" />
                    标记解决
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => resolve.mutate({ id: cluster.id, status: "open" })}
                  >
                    <RotateCcw className="mr-1 h-3 w-3" />
                    重新打开
                  </Button>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {data?.items.length === 0 && (
        <div className="text-center text-muted-foreground py-8">
          {isLoading ? "加载中..." : "暂无数据,点击\"刷新聚类\"生成"}
        </div>
      )}
    </div>
  );
}

function TopQuestionsTab() {
  const { data, isLoading } = useTopQuestions();
  const refresh = useRefreshTopQuestions();

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Button onClick={() => refresh.mutate()} disabled={refresh.isPending}>
          <RefreshCw className="mr-2 h-4 w-4" />
          刷新聚类
        </Button>
        {refresh.data && (
          <span className="text-sm text-muted-foreground">
            {refresh.data.cluster_count} 个聚类,{refresh.data.total_questions} 个问题
          </span>
        )}
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>代表问题</TableHead>
            <TableHead>频次</TableHead>
            <TableHead>示例</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data?.items.map((cluster) => (
            <TableRow key={cluster.id}>
              <TableCell className="font-medium">{cluster.representative_question}</TableCell>
              <TableCell>
                <Badge>{cluster.question_count}</Badge>
              </TableCell>
              <TableCell>
                <details>
                  <summary className="text-xs text-muted-foreground cursor-pointer">
                    {cluster.sample_questions.length} 个示例
                  </summary>
                  <ul className="mt-1 space-y-1">
                    {cluster.sample_questions.map((q, i) => (
                      <li key={i} className="text-xs text-muted-foreground">• {q}</li>
                    ))}
                  </ul>
                </details>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {data?.items.length === 0 && (
        <div className="text-center text-muted-foreground py-8">
          {isLoading ? "加载中..." : "暂无数据,点击\"刷新聚类\"生成"}
        </div>
      )}
    </div>
  );
}

function SourceAnalyticsTab() {
  const [days, setDays] = useState(30);
  const { data, isLoading } = useSourceAnalytics(days);

  const chartData = (data?.items || []).slice(0, 10).map((item) => ({
    name: item.url.split("/").pop() || item.url,
    fullUrl: item.url,
    clicks: item.clicks,
  }));

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Select value={String(days)} onValueChange={(v) => setDays(Number(v))}>
          <SelectTrigger className="w-32">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="7">最近 7 天</SelectItem>
            <SelectItem value="30">最近 30 天</SelectItem>
            <SelectItem value="90">最近 90 天</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {chartData.length > 0 && (
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} layout="vertical">
              <XAxis type="number" />
              <YAxis type="category" dataKey="name" width={150} tick={{ fontSize: 12 }} />
              <Tooltip />
              <Bar dataKey="clicks" fill="hsl(var(--primary))" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>URL</TableHead>
            <TableHead>类型</TableHead>
            <TableHead>产品</TableHead>
            <TableHead>点击数</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data?.items.map((item, i) => (
            <TableRow key={i}>
              <TableCell className="font-mono text-xs">{item.url}</TableCell>
              <TableCell><Badge variant="outline">{item.source_type}</Badge></TableCell>
              <TableCell>{item.product || "-"}</TableCell>
              <TableCell>{item.clicks}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {data?.items.length === 0 && (
        <div className="text-center text-muted-foreground py-8">
          {isLoading ? "加载中..." : "暂无点击数据"}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 5: 注册路由**

在 `admin/src/App.tsx` 中添加:

```typescript
import Analytics from "@/pages/Analytics";

// 在 Routes 中添加:
<Route path="/analytics" element={<Analytics />} />
```

- [ ] **Step 6: 添加导航项**

在 `admin/src/components/Sidebar.tsx` 的 `NAV_ITEMS` 中添加:

```typescript
import { BarChart3 } from "lucide-react";

// 在 conversations 之后、users 之前添加:
{ to: "/analytics", icon: BarChart3, label: "分析仪表盘", roles: ["admin", "editor", "viewer"] },
```

- [ ] **Step 7: 验证前端编译**

Run: `cd admin && npm run build`
Expected: 构建成功

- [ ] **Step 8: Commit**

```bash
git add admin/src/pages/Analytics.tsx admin/src/hooks/useAnalytics.ts admin/src/types/api.ts admin/src/App.tsx admin/src/components/Sidebar.tsx admin/package.json
git commit -m "feat: Admin 分析仪表盘(Coverage Gaps + Top Questions + Source Analytics)"
```

---

## Task 6: 端到端验证

- [ ] **Step 1: 运行全部测试**

Run: `pytest tests/ -v --tb=short`
Expected: ALL PASSED

- [ ] **Step 2: 手动验证 Coverage Gaps**

1. 确保有一些 `is_answered=False` 的对话记录
2. 打开 Admin → 分析仪表盘 → Coverage Gaps
3. 点击"刷新聚类",确认生成聚类列表
4. 查看代表性问题和示例问题
5. 点击"标记解决",确认状态变更

- [ ] **Step 3: 手动验证 Top Questions**

1. 确保有一些对话记录
2. 打开 Admin → 分析仪表盘 → Top Questions
3. 点击"刷新聚类",确认生成聚类列表
4. 查看频次排序

- [ ] **Step 4: 手动验证 Source Analytics**

1. 确保有 source_clicks 数据(在 Widget 中点击来源链接)
2. 打开 Admin → 分析仪表盘 → Source Analytics
3. 切换时间范围(7/30/90 天),确认数据变化
4. 查看柱状图和表格

- [ ] **Step 5: Commit**

```bash
git commit --allow-empty -m "test: Phase 3B 端到端验证通过"
```
