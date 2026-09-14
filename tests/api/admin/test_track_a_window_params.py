"""V1.6.3 Wave 1 Track A — BC-1/BC-2 分析窗参数能力测试(remediation plan §3.5,IF-7)。

冻结契约(track-a-contract.md + §3.5 能力矩阵 Outcome B):
- BC-1:GET /tech/answer-gaps 的 window 参数表达 IF-7 全冻结词表
  {今日 today, 近7天 7d, 近30天 30d, 全部 all, 显式起止 range:from/to};
  既有语义不变:last_seen 未知(时间不可用)行永不被窗排除;total=过滤后真值;
  显式起止格式无效 / from>to → 422(禁静默回退)。
- BC-2:GET /analytics/source-health 窗口参数表达 IF-7 全冻结词表(显式起止/all,
  经 from/to ISO 表达);既有 days 语义逐字保留(默认 30、ge=1 le=365);
  DSH-01 语义原样(signal=historical_reliability、MIN_SYNC_RUNS/insufficient_data、
  partial 计分母不计成功);显式窗回显 window={from,to}=实际评估窗(禁静默回退)。
- 仅参数能力:零新表、零新端点、零既有窗口语义变化。

时间确定性设计:显式起止用例用固定锚点日期(2026-09-01..09-09);命名窗
(today/7d/30d)回归用相对 now 的独立簇/源(now-1min / now-40d),与运行日期无关。
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import Conversation, DataSource, QuestionCluster, SyncLog, User
from backend.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")

_USER_EMAIL = "track-a-window@test.com"
# 共享测试库避让:固定 UUID 段(0xACCC...)生成主键,按代表问题前缀清理
_RQ_PREFIX = "TRKAWIN"
_DS_PREFIX = "trkawin-"


def _uid(i: int) -> uuid.UUID:
    return uuid.UUID(int=(0xACCC0000000040008000000000000000 + i))


async def _cleanup(factory):
    async with factory() as session:
        rows = (
            await session.execute(
                select(QuestionCluster).where(
                    QuestionCluster.representative_question.like(f"{_RQ_PREFIX}%")
                )
            )
        ).scalars().all()
        ids = [str(r.id) for r in rows]
        if ids:
            await session.execute(delete(Conversation).where(Conversation.cluster_id.in_(ids)))
            await session.execute(
                delete(QuestionCluster).where(QuestionCluster.id.in_([r.id for r in rows]))
            )
        await session.execute(delete(SyncLog).where(SyncLog.source_id.like(f"{_DS_PREFIX}%")))
        await session.execute(delete(DataSource).where(DataSource.id.like(f"{_DS_PREFIX}%")))
        await session.execute(delete(User).where(User.email == _USER_EMAIL))
        await session.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def window_seed():
    """Track A 窗口参数能力 seed(确定性:固定锚点 + 相对 now 双轨)。

    gap 聚类(BC-1):
    - A:归属会话 created_at=2026-09-05(显式窗 09-01..09-09 内)
    - B:归属会话 created_at=2026-08-01(显式窗外/早)
    - C:归属会话 created_at=2026-09-20(显式窗外/晚)
    - D:0 条归属会话(last_seen 未知 → 任何窗都包含)
    - E:归属会话 created_at=now-1min(任何命名窗 today/7d/30d 内)
    - F:归属会话 created_at=now-40d(7d/30d 窗外、all 内)
    source-health(BC-2):
    - trkawin-win:固定日期 09-05 success / 09-06 partial / 09-07 failed /
      08-01 success(显式窗断言锚)
    - trkawin-rel:now-1h success、now-40d failed(命名窗/days 回归锚)
    """
    factory = app.state.session_factory
    await _cleanup(factory)
    now = datetime.now(UTC)
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email=_USER_EMAIL,
                role="admin",
                password_hash=hash_password("pass"),
            )
        )
        clusters = {}
        for i, rq in enumerate(["A", "B", "C", "D", "E", "F"]):
            c = QuestionCluster(
                id=_uid(i),
                cluster_type="gap",
                representative_question=f"{_RQ_PREFIX}-{rq} 电池续航?",
                sample_questions=[f"{_RQ_PREFIX}-{rq} 样例?"],
                question_count=1,
                status="open",
            )
            session.add(c)
            clusters[rq] = c
        await session.flush()
        conv_specs = [
            ("A", datetime(2026, 9, 5, 10, 0, 0, tzinfo=UTC)),
            ("B", datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)),
            ("C", datetime(2026, 9, 20, 10, 0, 0, tzinfo=UTC)),
            ("E", now - timedelta(minutes=1)),
            ("F", now - timedelta(days=40)),
        ]
        for rq, at in conv_specs:
            session.add(
                Conversation(
                    question=f"{_RQ_PREFIX}-{rq} 会话",
                    is_answered=False,
                    cluster_id=str(clusters[rq].id),
                    created_at=at,
                )
            )
        session.add(
            DataSource(
                id=f"{_DS_PREFIX}win",
                type="web_crawl",
                product="track-a-product",
                enabled=True,
                config={"base_url": "https://trkawin.example.com"},
            )
        )
        session.add(
            DataSource(
                id=f"{_DS_PREFIX}rel",
                type="web_crawl",
                product="track-a-product",
                enabled=True,
                config={"base_url": "https://trkawin-rel.example.com"},
            )
        )
        sync_specs = [
            (f"{_DS_PREFIX}win", "success", datetime(2026, 9, 5, 8, 0, 0, tzinfo=UTC)),
            (f"{_DS_PREFIX}win", "partial", datetime(2026, 9, 6, 8, 0, 0, tzinfo=UTC)),
            (f"{_DS_PREFIX}win", "failed", datetime(2026, 9, 7, 8, 0, 0, tzinfo=UTC)),
            (f"{_DS_PREFIX}win", "success", datetime(2026, 8, 1, 8, 0, 0, tzinfo=UTC)),
            (f"{_DS_PREFIX}rel", "success", now - timedelta(hours=1)),
            (f"{_DS_PREFIX}rel", "failed", now - timedelta(days=40)),
        ]
        for source_id, status, started in sync_specs:
            session.add(
                SyncLog(
                    source_id=source_id,
                    source_type="web_crawl",
                    status=status,
                    started_at=started,
                )
            )
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}
    await _cleanup(app.state.session_factory)


async def _get(url: str, headers) -> tuple[int, dict]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(url, headers=headers)
    return resp.status_code, resp.json() if resp.content else {}


def _rq_set(j: dict) -> set[str]:
    return {it["representative_question"] for it in j["items"]}


def _item(j: dict, source_id: str) -> dict:
    return next(i for i in j["items"] if i["source_id"] == source_id)


# ----------------------------------------------------------------------- #
# BC-1:/tech/answer-gaps window 参数表达 IF-7 全冻结词表
# ----------------------------------------------------------------------- #


class TestBC1AnswerGapsWindow:
    async def test_window_today_calendar_day(self, window_seed):
        """今日=日历日起点;now-1min 簇在窗内、now-40d/固定旧簇在窗外;未知行保留。"""
        code, j = await _get("/api/admin/tech/answer-gaps?window=today", window_seed)
        assert code == 200
        rqs = _rq_set(j)
        assert f"{_RQ_PREFIX}-E 电池续航?" in rqs  # now-1min → 今日内
        assert f"{_RQ_PREFIX}-F 电池续航?" not in rqs  # now-40d → 窗外
        assert f"{_RQ_PREFIX}-A 电池续航?" not in rqs  # 2026-09-05 非今日(锚定过去)
        assert f"{_RQ_PREFIX}-D 电池续航?" in rqs  # last_seen 未知 ≠ 窗口外

    async def test_window_explicit_range_filters_both_bounds(self, window_seed):
        """显式起止 range:from/to:窗内含、窗外早/晚均排除;未知行保留。"""
        code, j = await _get(
            "/api/admin/tech/answer-gaps?window=range:2026-09-01/2026-09-09", window_seed
        )
        assert code == 200
        rqs = _rq_set(j)
        assert f"{_RQ_PREFIX}-A 电池续航?" in rqs  # 09-05 窗内
        assert f"{_RQ_PREFIX}-B 电池续航?" not in rqs  # 08-01 窗外早
        assert f"{_RQ_PREFIX}-C 电池续航?" not in rqs  # 09-20 窗外晚
        assert f"{_RQ_PREFIX}-D 电池续航?" in rqs  # last_seen 未知保留

    async def test_window_explicit_range_same_day_inclusive(self, window_seed):
        """显式起止单日(from==to):当日行含(结束日全天含)。"""
        code, j = await _get(
            "/api/admin/tech/answer-gaps?window=range:2026-09-05/2026-09-05", window_seed
        )
        assert code == 200
        rqs = _rq_set(j)
        assert f"{_RQ_PREFIX}-A 电池续航?" in rqs
        assert f"{_RQ_PREFIX}-B 电池续航?" not in rqs
        assert f"{_RQ_PREFIX}-C 电池续航?" not in rqs

    async def test_window_explicit_range_end_date_inclusive(self, window_seed):
        """显式起止结束日全天包含:end=2026-09-05 时 09-05 当日会话在窗内。"""
        code, j = await _get(
            "/api/admin/tech/answer-gaps?window=range:2026-09-01/2026-09-05", window_seed
        )
        assert code == 200
        assert f"{_RQ_PREFIX}-A 电池续航?" in _rq_set(j)

    async def test_window_existing_named_vocabulary_regression(self, window_seed):
        """既有 7d/30d/all 词表回归:语义不变(total=过滤后真值)。"""
        code, j = await _get("/api/admin/tech/answer-gaps?window=all", window_seed)
        assert code == 200
        assert len(j["items"]) == 6  # A/B/C/D/E/F 全包含

        code, j = await _get("/api/admin/tech/answer-gaps?window=7d", window_seed)
        assert code == 200
        rqs = _rq_set(j)
        assert f"{_RQ_PREFIX}-E 电池续航?" in rqs  # now-1min → 7d 内
        assert f"{_RQ_PREFIX}-F 电池续航?" not in rqs  # now-40d → 7d 外
        assert f"{_RQ_PREFIX}-D 电池续航?" in rqs

        code, j = await _get("/api/admin/tech/answer-gaps?window=30d", window_seed)
        assert code == 200
        rqs = _rq_set(j)
        assert f"{_RQ_PREFIX}-E 电池续航?" in rqs
        assert f"{_RQ_PREFIX}-F 电池续航?" not in rqs

    async def test_window_unknown_pattern_rejected(self, window_seed):
        """词表外窗口 422(既有 pattern 语义保持,禁静默回退)。"""
        code, _ = await _get("/api/admin/tech/answer-gaps?window=5d", window_seed)
        assert code == 422

    async def test_window_explicit_range_invalid_date_rejected(self, window_seed):
        """显式起止含非法日历日期 → 422(通过 regex 但 strptime 失败,禁静默回退)。"""
        code, _ = await _get(
            "/api/admin/tech/answer-gaps?window=range:2026-13-99/2026-13-99", window_seed
        )
        assert code == 422

    async def test_window_explicit_range_inverted_rejected(self, window_seed):
        """显式起止 from>to → 422(禁静默交换/回退)。"""
        code, _ = await _get(
            "/api/admin/tech/answer-gaps?window=range:2026-09-09/2026-09-01", window_seed
        )
        assert code == 422


# ----------------------------------------------------------------------- #
# BC-2:/analytics/source-health 窗口参数表达 IF-7 全冻结词表(显式起止/all)
# ----------------------------------------------------------------------- #


class TestBC2SourceHealthWindow:
    async def test_days_path_unchanged(self, window_seed):
        """既有 days 语义逐字保留:默认 30、window_days 回显、无 window 字段、DSH-01 原样。"""
        code, j = await _get("/api/admin/analytics/source-health", window_seed)
        assert code == 200
        assert j["days"] == 30
        assert "window" not in j  # 既有响应形状零变化(仅显式窗路径新增回显)
        item = _item(j, f"{_DS_PREFIX}rel")
        assert item["window_days"] == 30
        assert item["total_syncs"] == 1  # now-1h 在 30d 窗;now-40d 在窗外(确定性)
        assert item["success_syncs"] == 1
        assert item["signal"] == "historical_reliability"  # DSH-01 语义原样

    async def test_explicit_range_echoes_window_and_filters(self, window_seed):
        """显式起止:window={from,to}=实际评估窗回显;窗外同步不计入分母;DSH-01 语义原样。"""
        code, j = await _get(
            "/api/admin/analytics/source-health?from=2026-09-01&to=2026-09-09", window_seed
        )
        assert code == 200
        assert j["window"]["from"].startswith("2026-09-01")
        assert j["window"]["to"].startswith("2026-09-09")
        item = _item(j, f"{_DS_PREFIX}win")
        assert item["total_syncs"] == 3  # 08-01 的 success 在窗外
        assert item["success_syncs"] == 1
        assert item["partial_syncs"] == 1  # partial 计分母不计成功(DSH-01)
        assert item["failed_syncs"] == 1
        assert item["sync_success_rate"] == pytest.approx(1 / 3, abs=1e-4)
        assert item["signal"] == "historical_reliability"
        assert item["window_days"] == 9  # 09-01..09-09 含首尾 9 天

    async def test_all_span_via_explicit_range(self, window_seed):
        """全部时间以显式起止表达(远早锚点)→ 全历史计数。"""
        code, j = await _get(
            "/api/admin/analytics/source-health?from=2000-01-01&to=2099-12-31", window_seed
        )
        assert code == 200
        item = _item(j, f"{_DS_PREFIX}win")
        assert item["total_syncs"] == 4
        assert j["window"]["from"].startswith("2000-01-01")

    async def test_explicit_range_insufficient_data_semantics(self, window_seed):
        """显式窄窗样本 < MIN_SYNC_RUNS → insufficient_data(DSH-01 原样,不伪造结论)。"""
        code, j = await _get(
            "/api/admin/analytics/source-health?from=2026-09-06&to=2026-09-06", window_seed
        )
        assert code == 200
        item = _item(j, f"{_DS_PREFIX}win")
        assert item["total_syncs"] == 1
        assert item["health"] == "insufficient_data"

    async def test_explicit_range_requires_both_bounds(self, window_seed):
        """只给 from 或只给 to → 422(禁半开窗静默语义)。"""
        code, _ = await _get(
            "/api/admin/analytics/source-health?from=2026-09-01", window_seed
        )
        assert code == 422
        code, _ = await _get(
            "/api/admin/analytics/source-health?to=2026-09-09", window_seed
        )
        assert code == 422

    async def test_explicit_range_invalid_date_rejected(self, window_seed):
        code, _ = await _get(
            "/api/admin/analytics/source-health?from=not-a-date&to=2026-09-09", window_seed
        )
        assert code == 422

    async def test_explicit_range_inverted_rejected(self, window_seed):
        code, _ = await _get(
            "/api/admin/analytics/source-health?from=2026-09-09&to=2026-09-01", window_seed
        )
        assert code == 422
