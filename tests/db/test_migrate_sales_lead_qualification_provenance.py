"""#124 AC4: qualification provenance is additive and preserves historical values."""

from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

from backend.db.session import ensure_sales_lead_qualification_provenance_column

TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test",
)
ADMIN_DSN = TEST_DSN.replace("+asyncpg", "+psycopg2").rsplit("/", 1)[0] + "/postgres"
MIGRATION_DB = "ask_ai_lead_qualification_provenance_test"
MIGRATION_DSN_SYNC = ADMIN_DSN.rsplit("/", 1)[0] + "/" + MIGRATION_DB
MIGRATION_DSN_ASYNC = TEST_DSN.rsplit("/", 1)[0] + "/" + MIGRATION_DB

pytestmark = pytest.mark.integration


@pytest.fixture(params=[False, True], ids=["column-absent", "column-already-present"])
def qualification_db(request):
    try:
        admin = create_engine(ADMIN_DSN, isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{MIGRATION_DB}"'))
            conn.execute(text(f'CREATE DATABASE "{MIGRATION_DB}"'))
        admin.dispose()
    except SQLAlchemyError as exc:
        pytest.skip(f"Postgres test server unavailable: {exc}")

    engine = create_engine(MIGRATION_DSN_SYNC)
    provenance_column = ", qualification_provenance VARCHAR(30)" if request.param else ""
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE sales_leads (id INTEGER PRIMARY KEY, status VARCHAR(30) NOT NULL"
                + provenance_column
                + ")"
            )
        )
        conn.execute(text("INSERT INTO sales_leads (id, status) VALUES (1, 'qualified')"))
    yield engine, request.param
    engine.dispose()
    with create_engine(ADMIN_DSN, isolation_level="AUTOCOMMIT").connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{MIGRATION_DB}"'))


def test_migration_adds_only_nullable_provenance_and_preserves_existing_rows(qualification_db):
    sync_engine, column_preexisted = qualification_db
    async_engine = create_async_engine(MIGRATION_DSN_ASYNC)
    statements: list[str] = []

    @event.listens_for(async_engine.sync_engine, "before_cursor_execute")
    def capture_sql(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip())

    async def run_twice():
        await ensure_sales_lead_qualification_provenance_column(async_engine)
        await ensure_sales_lead_qualification_provenance_column(async_engine)

    try:
        asyncio.run(run_twice())
    finally:
        asyncio.run(async_engine.dispose())

    with sync_engine.connect() as conn:
        row = conn.execute(
            text("SELECT status, qualification_provenance FROM sales_leads WHERE id=1")
        ).one()
    assert row.status == "qualified"
    assert row.qualification_provenance is None

    ddl = [statement.upper() for statement in statements if statement.upper().startswith("ALTER")]
    if column_preexisted:
        assert ddl == []
    else:
        assert ddl == [
            "ALTER TABLE SALES_LEADS ADD COLUMN IF NOT EXISTS "
            "QUALIFICATION_PROVENANCE VARCHAR(30)"
        ]
    assert not any(
        any(
            token in statement.upper()
            for token in ("UPDATE ", "DELETE ", "DROP ", "TRUNCATE ", "ALTER COLUMN")
        )
        for statement in statements
    )
