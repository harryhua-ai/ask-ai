"""r3gate R4-2:PG driver 探针 COUNT 通道 fail-closed(None/NULL 不再解释为 0)。

A 实码复审阻塞(R3 = 三项确定性阻塞之一)要点:R3 ``_pg_probe_driver()``
的 ``count = int(row[0]) if row and row[0] is not None else 0`` 把
fetchone() 返回 None / NULL 的**不可证明计数**解释为 0,可被记录为
``isolation_upload_mode_clean`` pass —— fail-open。

RED 实证(R3 现码 b9769af1,2026-10-20,psycopg2 fake + psql 通道缺失,
真实 ``probe_upload_mode_rows`` 执行路径;身份行/锚均匹配,仅计数行故障):
- fetchone() 第 3 行返回 None → probe 返回 0 → 将记 clean pass(假 PASS 实测);
- COUNT 列 (None,) → probe 返回 0 → 同上(假 PASS 实测)。

修复后(GREEN,本文件以真实执行路径钉住 T-PD-01..08):
仅当 COUNT 成功执行且取得合法非负整数才采用;None/空行/NULL/非法类型
(bool/float/str/bytes)/负数/转换失败/查询异常/断连一律 fail-closed
(RuntimeError → 隔离子项 fail,整体非零退出);无异常吞噬、无默认零;
不加其他隔离判断逻辑。

红线:全部 fake psycopg2/psql shim,真实子进程与真实函数执行路径;DSN
口令为 R4GRN-* 假口令,绝不进 argv/stdout/verdict;不连生产。
"""

from __future__ import annotations

import json
import os
import sys
import types
from decimal import Decimal
from pathlib import Path

import pytest

import scripts.release_preflight as rp
from scripts.release_preflight import evaluate, main

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FAKE_PW = "R4GRN-FAKEPW-PGDRIVER"
_DSN = f"postgresql://iso_user:{_FAKE_PW}@dbhost:6543/iso_db"
_PG_SID = "7200000000000000002"


class _SeqCursor:
    """顺序回放 cursor:execute 记录 SQL,fetchone 按序回放(故障注入点)。"""

    def __init__(self, seq: list, executed: list, fail_on_execute: int | None = None):
        self._seq = list(seq)
        self._executed = executed
        self._fail_on_execute = fail_on_execute

    def execute(self, sql):
        self._executed.append(" ".join(sql.split()))
        if self._fail_on_execute is not None and len(self._executed) == self._fail_on_execute:
            raise RuntimeError("injected query failure (fake)")

    def fetchone(self):
        item = self._seq.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _SeqConn:
    def __init__(self, seq: list, executed: list, fail_on_execute: int | None = None):
        self._seq = seq
        self._executed = executed
        self._fail_on_execute = fail_on_execute

    def cursor(self):
        return _SeqCursor(self._seq, self._executed, self._fail_on_execute)

    def rollback(self):
        self._executed.append("ROLLBACK")

    def close(self):
        self._executed.append("CLOSE")


def _install_driver_channel(monkeypatch, row3, fail_on_execute: int | None = None):
    """psql 通道缺失 + psycopg2 fake(真实 _pg_probe_driver 执行路径)。"""
    executed: list = []
    fake_mod = types.ModuleType("psycopg2")
    fake_mod.connect = lambda **kw: executed.append(
        f"CONNECT host={kw['host']} port={kw['port']} db={kw['dbname']}"
    ) or _SeqConn([("iso_db",), (_PG_SID,), row3], executed, fail_on_execute)
    monkeypatch.setitem(sys.modules, "psycopg2", fake_mod)
    monkeypatch.setattr(rp, "_import_psycopg2", lambda: fake_mod)

    def _psql_missing(*a, **k):
        raise rp.IsolationChannelUnavailable("psql 不可用")

    monkeypatch.setattr(rp, "_pg_probe_psql", _psql_missing)
    return executed


def _write_manifest(tmp_path: Path) -> Path:
    m = tmp_path / "compatibility.json"
    m.write_text(
        json.dumps(
            {
                "version": 1,
                "config": [],
                "host": [],
                "topology": [],
                "dependencies": [],
                "rollback": {"previous_compatible": True},
            }
        ),
        encoding="utf-8",
    )
    return m


def _isolation(tmp_path: Path) -> dict:
    return {
        "pg_dsn": _DSN,
        "weaviate_url": None,
        "weaviate_class": None,
        "trust_anchor": {"pg_system_id": _PG_SID,
                         "weaviate_collection_id": "01234567-89ab-cdef-0123-456789abcdef"},
    }


def _pg_check(verdict: dict) -> dict:
    return [c for c in verdict["checks"] if c["section"] == "isolation"
            and c["name"] == "upload_mode_rows"][0]


# --------------------------------------------------------------------------- #
# T-PD-01/02:合法计数(0 → clean pass;正数 → rows present fail)
# --------------------------------------------------------------------------- #


def test_tpd01_valid_zero_adopts_clean_pass(tmp_path, monkeypatch):
    _install_driver_channel(monkeypatch, (0,))
    rows = rp.probe_upload_mode_rows(
        {"dsn": _DSN, "expected_pg_system_id": _PG_SID}, 5
    )
    assert rows == 0
    m = _write_manifest(tmp_path)
    verdict, code = evaluate(str(m), verify_upload_isolation=True,
                             isolation=_isolation(tmp_path))
    pg = _pg_check(verdict)
    assert pg["status"] == "pass" and pg["class"] == "isolation_upload_mode_clean"


def test_tpd02_valid_positive_adopts_fail(tmp_path, monkeypatch):
    _install_driver_channel(monkeypatch, (5,))
    m = _write_manifest(tmp_path)
    verdict, code = evaluate(str(m), verify_upload_isolation=True,
                             isolation=_isolation(tmp_path))
    pg = _pg_check(verdict)
    assert code == 2 and pg["status"] == "fail"
    assert pg["class"] == "isolation_upload_mode_rows_present"
    assert "5 行" in pg["reason"]


def test_tpd02_decimal_integral_zero_accepted(tmp_path, monkeypatch):
    """psycopg2 numeric → Decimal;可无损整转的合法值照常采用。"""
    _install_driver_channel(monkeypatch, (Decimal("0"),))
    rows = rp.probe_upload_mode_rows(
        {"dsn": _DSN, "expected_pg_system_id": _PG_SID}, 5
    )
    assert rows == 0


# --------------------------------------------------------------------------- #
# T-PD-03..05:None 行 / NULL / 非法类型 → 一律 fail-closed
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("row3,label", [
    (None, "fetchone 返回 None 行"),
    ((None,), "COUNT 列 NULL"),
    (("abc",), "字符串计数"),
    ((True,), "布尔计数"),
    ((2.5,), "浮点计数"),
    ((b"0",), "bytes 计数"),
    ((Decimal("1.5"),), "非整 Decimal"),
    ((-3,), "负数"),
    ((), "空行元组"),
], ids=["none-row", "null-value", "str", "bool", "float", "bytes", "decimal-frac", "negative", "empty-row"])
def test_tpd03_unprovable_counts_fail_closed(monkeypatch, row3, label):
    """None 行/NULL/非法类型/负数/空行 → RuntimeError(fail-closed),绝不返回 0。"""
    _install_driver_channel(monkeypatch, row3)
    with pytest.raises(RuntimeError):
        rp.probe_upload_mode_rows(
            {"dsn": _DSN, "expected_pg_system_id": _PG_SID}, 5
        )


# --------------------------------------------------------------------------- #
# T-PD-06/07:查询异常 / 断连 → fail-closed
# --------------------------------------------------------------------------- #


def test_tpd06_query_exception_fail_closed(monkeypatch):
    """COUNT 执行异常 → RuntimeError(无吞噬、无默认零)。"""
    _install_driver_channel(monkeypatch, (0,), fail_on_execute=3)
    with pytest.raises(RuntimeError):
        rp.probe_upload_mode_rows(
            {"dsn": _DSN, "expected_pg_system_id": _PG_SID}, 5
        )


def test_tpd07_disconnect_fail_closed(monkeypatch):
    """断连(fetchone 抛 psycopg2 OperationalError 形状异常)→ fail-closed。"""

    class _OpErr(Exception):
        pass

    _install_driver_channel(monkeypatch, _OpErr("server closed the connection (fake)"))
    with pytest.raises(RuntimeError):
        rp.probe_upload_mode_rows(
            {"dsn": _DSN, "expected_pg_system_id": _PG_SID}, 5
        )


# --------------------------------------------------------------------------- #
# T-PD-08:故障注入下 verdict 无虚假 clean PASS(整体非零 + 无 pass 项)
# --------------------------------------------------------------------------- #


def test_tpd08_injected_null_never_yields_clean_pass_verdict(tmp_path, monkeypatch):
    """NULL 注入 → evaluate 全链:该子项 fail(probe_failed),整体非零,
    verdict 绝无 isolation_upload_mode_clean pass;口令不进 verdict。"""
    _install_driver_channel(monkeypatch, (None,))
    m = _write_manifest(tmp_path)
    verdict, code = evaluate(str(m), verify_upload_isolation=True,
                             isolation=_isolation(tmp_path))
    assert code == 2 and verdict["status"] == "fail"
    pg = _pg_check(verdict)
    assert pg["status"] == "fail"
    assert pg["class"] == "isolation_upload_mode_probe_failed"
    assert not any(c["class"] == "isolation_upload_mode_clean" for c in verdict["checks"])
    assert _FAKE_PW not in json.dumps(verdict)
    assert "conninfo" not in pg["reason"]


def test_tpd08_main_cli_fail_closed_path(tmp_path, monkeypatch, capsys):
    """main 真实 CLI:None 行注入 → 非零退出;stdout verdict 无虚假 clean。"""
    _install_driver_channel(monkeypatch, None)
    m = _write_manifest(tmp_path)
    anchor_file = tmp_path / "anchor.json"
    anchor_file.write_text(json.dumps(
        {"version": 1, "pg_system_id": _PG_SID,
         "weaviate_collection_id": "01234567-89ab-cdef-0123-456789abcdef"}),
        encoding="utf-8")
    monkeypatch.setenv("ISOLATION_PG_DSN", _DSN)
    code = main([
        "--manifest", str(m),
        "--verify-upload-isolation",
        "--isolation-pg-dsn-env", "ISOLATION_PG_DSN",
        "--isolation-trust-anchor-file", str(anchor_file),
    ])
    assert code == 2
    verdict = json.loads(capsys.readouterr().out)
    assert not any(c["class"] == "isolation_upload_mode_clean" for c in verdict["checks"])
