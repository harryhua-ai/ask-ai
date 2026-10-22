"""r3 发布安全门 G2(修复 2):preflight --verify-upload-isolation 只读隔离断言。

12 项测试映射(胶囊):
- T9:preflight 缺有效隔离证据 → 新断言 fail-closed 非零退出 + 结构化原因。
  显式启用(``--verify-upload-isolation``);未启用时行为零变化。
  断言语义(按当前门语义取严):目标 DB ``upload_mode=true`` 注册行必须为 0
  才 PASS;filesystem 类 Weaviate 对象必须为 0 才 PASS;只读查询通道不可用
  → 该子项 BLOCKED(不谎报 PASS),整体仍非零退出。

红线:本检查不创建 remediation ACK、不改 compatibility.json 门值;workflow
接线留给集成授权。探针全程只读(SELECT count(*) / GraphQL Aggregate)。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.release_preflight as rp
from scripts.release_preflight import evaluate, main


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


_FULL_ISOLATION = {
    "pg_dsn": "postgresql+asyncpg://usr:secretpw@dbhost:6543/dbname",
    "weaviate_url": "http://wvhost:8080",
    "weaviate_class": "KnowledgeChunk",
}

# R3-1:隔离断言自 R3 起强制携带独立信任锚(测试自造非秘密锚值;
# 锚级负例与 T-ID-01..10 见 test_r3gate_preflight_trust_anchor.py)
_R3_ANCHOR = {
    "pg_system_id": "7100000000000000001",
    "weaviate_collection_id": "01234567-89ab-cdef-0123-456789abcdef",
}
_FULL_ISOLATION_WITH_ANCHOR = {**_FULL_ISOLATION, "trust_anchor": dict(_R3_ANCHOR)}


def _iso_checks(verdict: dict) -> list[dict]:
    return [c for c in verdict["checks"] if c["section"] == "isolation"]


# --------------------------------------------------------------------------- #
# 未启用 = 零变化
# --------------------------------------------------------------------------- #


def test_flag_disabled_zero_behavior_change(tmp_path, capsys):
    """未启用 --verify-upload-isolation:判定零漂移,不出现任何 isolation 检查。"""
    m = _write_manifest(tmp_path)
    assert main(["--manifest", str(m)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert _iso_checks(out) == []
    assert out["status"] == "pass"


# --------------------------------------------------------------------------- #
# T9:fail-closed 三态(contaminated → fail / 通道缺失 → blocked / 干净 → pass)
# --------------------------------------------------------------------------- #


def test_t9_enabled_without_channels_blocks_fail_closed(tmp_path):
    """启用但无任何只读查询通道(锚可用)→ 两子项 BLOCKED,整体非零退出
    (不谎报 PASS)。锚缺失路径另见 trust_anchor 测试 T-ID-07。"""
    m = _write_manifest(tmp_path)
    verdict, code = evaluate(
        str(m),
        verify_upload_isolation=True,
        isolation={"trust_anchor": dict(_R3_ANCHOR)},
    )
    assert code == 2
    assert verdict["status"] == "fail"
    iso = _iso_checks(verdict)
    assert {c["name"] for c in iso} == {"upload_mode_rows", "filesystem_objects"}
    assert all(c["status"] == "blocked" for c in iso)
    assert all("不谎报" in c["reason"] for c in iso)


def test_t9_contaminated_evidence_fails_closed(tmp_path, monkeypatch):
    """有通道且证据为污染(upload_mode 行 > 0 / filesystem 对象 > 0)→ fail。"""
    monkeypatch.setattr(rp, "probe_upload_mode_rows", lambda cfg, timeout_s: 2)
    monkeypatch.setattr(rp, "probe_retired_source_residue", lambda cfg, timeout_s: dict.fromkeys(rp._RETIRE_RESIDUE_KEYS, 1))
    monkeypatch.setattr(rp, "probe_filesystem_objects", lambda cfg, timeout_s: 7)
    m = _write_manifest(tmp_path)
    verdict, code = evaluate(
        str(m), verify_upload_isolation=True, isolation=dict(_FULL_ISOLATION_WITH_ANCHOR)
    )
    assert code == 2
    classes = {c["class"] for c in _iso_checks(verdict)}
    assert "isolation_upload_mode_rows_present" in classes
    assert "isolation_filesystem_objects_present" in classes
    reasons = " | ".join(c["reason"] for c in _iso_checks(verdict))
    assert "2" in reasons and "7" in reasons  # 结构化原因携带计数证据


def test_t9_clean_evidence_passes(tmp_path, monkeypatch):
    """0 注册行 + 0 filesystem 对象(基线)→ PASS,退出码 0。"""
    monkeypatch.setattr(rp, "probe_upload_mode_rows", lambda cfg, timeout_s: 0)
    monkeypatch.setattr(rp, "probe_retired_source_residue", lambda cfg, timeout_s: {**dict.fromkeys(rp._RETIRE_RESIDUE_KEYS, 0), "legacy_generations": 1})
    monkeypatch.setattr(rp, "probe_filesystem_objects", lambda cfg, timeout_s: 0)
    m = _write_manifest(tmp_path)
    verdict, code = evaluate(
        str(m), verify_upload_isolation=True, isolation=dict(_FULL_ISOLATION_WITH_ANCHOR)
    )
    assert code == 0
    assert verdict["status"] == "pass"
    iso = _iso_checks(verdict)
    assert {c["status"] for c in iso} == {"pass"}
    assert {c["class"] for c in iso} == {
        "isolation_upload_mode_clean",
        "isolation_filesystem_clean",
        "isolation_residue_clean",
        "isolation_legacy_present",
    }


def test_probe_unavailable_blocked_vs_probe_failed_fail(tmp_path, monkeypatch):
    """通道缺失 → BLOCKED;通道存在但探针失败 → fail-closed fail(可区分)。"""
    m = _write_manifest(tmp_path)

    def _raise_unavailable(cfg, timeout_s):
        raise rp.IsolationChannelUnavailable("psql 不可用")

    monkeypatch.setattr(rp, "probe_upload_mode_rows", _raise_unavailable)
    monkeypatch.setattr(rp, "probe_retired_source_residue", _raise_unavailable)
    monkeypatch.setattr(rp, "probe_filesystem_objects", _raise_unavailable)
    verdict, code = evaluate(
        str(m), verify_upload_isolation=True, isolation=dict(_FULL_ISOLATION_WITH_ANCHOR)
    )
    assert code == 2
    assert all(c["status"] == "blocked" for c in _iso_checks(verdict))

    def _raise_probe(cfg, timeout_s):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(rp, "probe_upload_mode_rows", _raise_probe)
    monkeypatch.setattr(rp, "probe_retired_source_residue", _raise_probe)
    monkeypatch.setattr(rp, "probe_filesystem_objects", _raise_probe)
    verdict2, code2 = evaluate(
        str(m), verify_upload_isolation=True, isolation=dict(_FULL_ISOLATION_WITH_ANCHOR)
    )
    assert code2 == 2
    assert all(c["status"] == "fail" for c in _iso_checks(verdict2))
    assert {c["class"] for c in _iso_checks(verdict2)} == {
        "isolation_upload_mode_probe_failed",
        "isolation_filesystem_probe_failed",
        "isolation_residue_probe_failed",
    }


# --------------------------------------------------------------------------- #
# 只读探针实现契约(psql / GraphQL Aggregate)
# --------------------------------------------------------------------------- #


def test_psql_probe_readonly_and_password_never_in_argv(monkeypatch):
    """psql 探针:只读 SELECT;口令只进 PGPASSWORD env,绝不进 argv;
    R2-4①:同一会话必须先执行 current_database() 身份复核;
    R3-1:同会话追加 system_identifier 锚实测查询(psql 输出 3 行)。"""
    captured: dict = {}

    def fake_run(argv, capture_output, text, timeout, env, check):
        captured["argv"] = argv
        captured["env"] = env
        return SimpleNamespace(
            returncode=0, stdout="dbname\n7100000000000000001\n0\n", stderr=""
        )

    monkeypatch.setattr(rp.subprocess, "run", fake_run)
    rows = rp.probe_upload_mode_rows(
        {
            "dsn": _FULL_ISOLATION["pg_dsn"],
            "expected_pg_system_id": "7100000000000000001",
        },
        5,
    )
    assert rows == 0
    argv = captured["argv"]
    assert argv[0] == "psql"
    assert "secretpw" not in " ".join(argv), "口令不得出现在 argv(进程列表可见)"
    assert captured["env"]["PGPASSWORD"] == "secretpw"
    joined = " ".join(argv)
    assert "-c" in argv
    assert "SELECT current_database()" in joined, "R2-4①:必须执行身份复核查询"
    assert "SELECT system_identifier FROM pg_control_system()" in joined, "R3-1:锚实测"
    assert "SELECT count(*) FROM data_sources" in joined
    assert "config->>'upload_mode' = 'true'" in joined
    assert "dbhost" in joined and "6543" in joined and "dbname" in joined


def test_psql_probe_maps_missing_binary_to_channel_unavailable(monkeypatch):
    """psql 与 psycopg2 只读通道**均**缺失 → IsolationChannelUnavailable(BLOCKED);
    仅 psql 缺失时 R3-2 起回退冻结镜像自带 psycopg2 通道(见 trust_anchor 测试)。"""
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("psql")

    monkeypatch.setattr(rp.subprocess, "run", fake_run)

    def _no_driver():
        raise rp.IsolationChannelUnavailable("psql 与 psycopg2 只读查询通道均不可用")

    monkeypatch.setattr(rp, "_import_psycopg2", _no_driver)
    with pytest.raises(rp.IsolationChannelUnavailable):
        rp.probe_upload_mode_rows(
            {
                "dsn": _FULL_ISOLATION["pg_dsn"],
                "expected_pg_system_id": "7100000000000000001",
            },
            5,
        )


def test_psql_probe_rejects_dsn_without_dbname():
    with pytest.raises(RuntimeError):
        rp.probe_upload_mode_rows({"dsn": "postgresql://usr:pw@host:5432/"}, 5)


class _FakeHTTPResponse:
    def __init__(self, status: int, body: bytes):
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body


def test_weaviate_probe_parses_aggregate_count(monkeypatch):
    """GraphQL Aggregate 只读探针:解析 meta.count;错误响应 fail-closed。
    R2-4②:先 GET /v1/meta 做 hostname ↔ URL 绑定,再双聚合计数;
    R3-1:中间追加 GET /v1/schema collectionId 锚比对。"""
    captured: dict = {}

    class FakeConn:
        def __init__(self, host, port, timeout):
            captured["endpoint"] = (host, port, timeout)

        def request(self, method, path, body=None, headers=None):
            captured.setdefault("requests", []).append((method, path))
            if body:
                captured.setdefault("bodies", []).append(json.loads(body))

        def getresponse(self):
            method, path = captured["requests"][-1]
            if method == "GET" and path == "/v1/meta":
                return _FakeHTTPResponse(
                    200, json.dumps({"hostname": "http://wvhost:8080"}).encode()
                )
            if method == "GET" and path == "/v1/schema":
                return _FakeHTTPResponse(
                    200,
                    json.dumps(
                        {"collections": [
                            {"class": "KnowledgeChunk",
                             "collectionId": "01234567-89ab-cdef-0123-456789abcdef"}
                        ]}
                    ).encode(),
                )
            return _FakeHTTPResponse(
                200,
                json.dumps(
                    {
                        "data": {
                            "Aggregate": {
                                "KnowledgeChunk_TOTAL": [{"meta": {"count": 30}}],
                                "KnowledgeChunk_FILESYSTEM": [{"meta": {"count": 3}}],
                            }
                        }
                    }
                ).encode(),
            )

        def close(self):
            pass

    # 只替换连接工厂(FakeConn 直替);不触碰 HTTPConnection.__new__ ——
    # 对继承类属性 setattr 会在还原时残留 class-dict 条目,污染后续用真实
    # http.client 的测试(R3 trust_anchor 套件实测踩中该残留)。
    monkeypatch.setattr(rp, "_http_connection_factory", lambda scheme, host, port, timeout: FakeConn(host, port, timeout))
    count = rp.probe_filesystem_objects(
        {
            "url": "http://wvhost:8080",
            "class": "KnowledgeChunk",
            "expected_collection_id": "01234567-89ab-cdef-0123-456789abcdef",
        },
        5,
    )
    assert count == 3
    assert ("GET", "/v1/meta") in captured["requests"], "R2-4②:必须先做身份绑定"
    assert ("GET", "/v1/schema") in captured["requests"], "R3-1:必须做锚比对"
    assert ("POST", "/v1/graphql") in captured["requests"]
    assert captured["requests"].index(("GET", "/v1/schema")) < captured["requests"].index(
        ("POST", "/v1/graphql")
    ), "锚比对必须先于聚合断言"
    assert 'source_type' in json.dumps(captured["bodies"][-1]), (
        "filesystem 过滤谓词必须保留在聚合查询中"
    )
    assert captured["endpoint"] == ("wvhost", 8080, 5)


def test_weaviate_probe_rejects_injection_class_name():
    """class 名词表校验:非 [A-Za-z][A-Za-z0-9_]* 一律拒绝(无 GraphQL 注入面)。"""
    with pytest.raises(RuntimeError):
        rp.probe_filesystem_objects(
            {"url": "http://h:8080", "class": "K}){ignore",
             "expected_collection_id": "x"}, 5
        )


def test_weaviate_probe_non_200_fails_closed(monkeypatch):
    class FakeConn:
        def __init__(self, *a):
            pass

        def request(self, *a, **k):
            pass

        def getresponse(self):
            return _FakeHTTPResponse(503, b"unavailable")

        def close(self):
            pass

    monkeypatch.setattr(
        rp, "_http_connection_factory", lambda scheme, host, port, timeout: FakeConn()
    )
    with pytest.raises(RuntimeError):
        rp.probe_filesystem_objects(
            {"url": "http://h:8080", "class": "K",
             "expected_collection_id": "01234567-89ab-cdef-0123-456789abcdef"}, 5
        )


# --------------------------------------------------------------------------- #
# CLI 接线
# --------------------------------------------------------------------------- #


def test_main_cli_wiring_clean(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(rp, "probe_upload_mode_rows", lambda cfg, timeout_s: 0)
    monkeypatch.setattr(rp, "probe_retired_source_residue", lambda cfg, timeout_s: {**dict.fromkeys(rp._RETIRE_RESIDUE_KEYS, 0), "legacy_generations": 1})
    monkeypatch.setattr(rp, "probe_filesystem_objects", lambda cfg, timeout_s: 0)
    monkeypatch.setenv("ISOLATION_PG_DSN", _FULL_ISOLATION["pg_dsn"])
    anchor = tmp_path / "anchor.json"
    anchor.write_text(
        json.dumps({"version": 1, **_R3_ANCHOR}), encoding="utf-8"
    )
    m = _write_manifest(tmp_path)
    code = main(
        [
            "--manifest", str(m),
            "--verify-upload-isolation",
            "--isolation-trust-anchor-file", str(anchor),
            "--isolation-weaviate-url", _FULL_ISOLATION["weaviate_url"],
            "--isolation-weaviate-class", _FULL_ISOLATION["weaviate_class"],
        ]
    )
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert {c["status"] for c in _iso_checks(out)} == {"pass"}


def test_main_cli_wiring_blocked_exit_nonzero(tmp_path, capsys, monkeypatch):
    """锚可用但通道缺失 → blocked;锚缺失 → 锚门禁 fail(见 T-ID-07)。"""
    monkeypatch.delenv("ISOLATION_PG_DSN", raising=False)
    anchor = tmp_path / "anchor.json"
    anchor.write_text(
        json.dumps({"version": 1, **_R3_ANCHOR}), encoding="utf-8"
    )
    m = _write_manifest(tmp_path)
    code = main([
        "--manifest", str(m), "--verify-upload-isolation",
        "--isolation-trust-anchor-file", str(anchor),
    ])
    assert code == 2
    out = json.loads(capsys.readouterr().out)
    assert all(c["status"] == "blocked" for c in _iso_checks(out))
