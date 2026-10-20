"""r3gate R3-1:preflight 隔离断言的可信生产目标身份绑定(独立信任锚)。

A 复审裁决(R2 = PARTIAL/CORRECTION REQUIRED)要点:R2 的
current_database()==DSN dbname 与 /v1/meta hostname==URL host:port 属
**同源配置自洽检查**,不能独立证明连的是权威生产实例 —— 误配同名测试库/
代理环境可制造"0 注册/0 filesystem"假 PASS。

RED 实证(R2 现码 9b2a6029,2026-10-20,psql shim 真实执行路径):
同名库(iso_db)、不同物理集群(system_identifier=7339550012345678901)→
``probe_upload_mode_rows`` 返回 0,``upload_mode_rows`` 判
``isolation_upload_mode_clean`` pass —— 假 PASS 实证(R2 探针从不查询
pg_control_system())。

修复后(GREEN,本文件以真实执行路径钉住 T-ID-01..10):
- PG:同一会话先 current_database() + pg_control_system().system_identifier,
  与带外钉扎信任锚(--isolation-trust-anchor-file)精确比对;锚独立于被测
  DSN/URL/自报 metadata;缺失期望锚值/不一致 → fail-closed;
- Weaviate:GET /v1/schema 取目标 collection 的 collectionId 稳定标识与锚
  比对;不一致 → fail-closed;无强标识字段 → 子项如实 BLOCKED(不降低
  验证强度换 PASS);集合不存在/空 → BLOCKED;
- 锚门禁先行:锚不可用 → 单条 fail 检查,绝不执行任何隔离探针(身份失败
  时隔离结果绝不 PASS);
- 容器内通道:psql 缺失 → 冻结镜像自带 psycopg2 单会话只读探针(同一组
  SELECT、同一身份复核)。

红线:全部 mock/fake/本地 HTTP 服务,禁连生产;锚值均为测试自造的非秘密
标识;DSN 口令均为 R3GRN-* 假口令,绝不进 argv/stdout/stderr/verdict。
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

import scripts.release_preflight as rp
from scripts.release_preflight import evaluate, main

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FAKE_PW = "R3GRN-FAKEPW-TRUSTANCHOR"
_DSN = f"postgresql://iso_user:{_FAKE_PW}@dbhost:6543/iso_db"
# 测试自造锚值(非秘密;绝不代表真实生产标识 —— 生产锚采集属 A-owned,如实 BLOCKED)
_PG_SID = "7100000000000000001"
_WV_CID = "01234567-89ab-cdef-0123-456789abcdef"


def _write_anchor(tmp_path: Path, **overrides) -> Path:
    payload = {
        "version": 1,
        "pg_system_id": _PG_SID,
        "weaviate_collection_id": _WV_CID,
    }
    payload.update(overrides)
    p = tmp_path / "trust-anchor.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


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


def _iso_checks(verdict: dict) -> list[dict]:
    return [c for c in verdict["checks"] if c["section"] == "isolation"]


def _anchor_checks(verdict: dict) -> list[dict]:
    return [c for c in _iso_checks(verdict) if c["name"] == "trust_anchor"]


# --------------------------------------------------------------------------- #
# psql shim(真实子进程执行路径;捕获 argv)
# --------------------------------------------------------------------------- #


@pytest.fixture
def psql_shim(tmp_path, monkeypatch):
    def _install(psql_output: str, *, returncode: int = 0):
        argv_file = tmp_path / "shim_argv.txt"
        shim = tmp_path / "psql"
        body = (
            "#!/bin/bash\n"
            f'printf \'%s\\n\' "$@" > "{argv_file}"\n'
            f'printf \'%s\\n\' "{psql_output}"\n'
        )
        if returncode:
            body += f"exit {returncode}\n"
        shim.write_text(body, encoding="utf-8")
        shim.chmod(0o755)
        monkeypatch.setenv(
            "PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}"
        )
        return argv_file

    return _install


# --------------------------------------------------------------------------- #
# Weaviate 替身(/v1/meta + /v1/schema + /v1/graphql;真实本地 HTTP 服务)
# --------------------------------------------------------------------------- #


class _FakeWeaviate:
    """受控 Weaviate 替身:meta hostname / schema collections / 聚合计数。"""

    def __init__(
        self,
        *,
        meta_hostname: str,
        total: int,
        filesystem: int,
        collections: list | None = None,
        schema_status: int = 200,
        schema_raw: bytes | None = None,
    ):
        self.meta_hostname = meta_hostname
        self.total = total
        self.filesystem = filesystem
        self.collections = collections if collections is not None else [
            {"class": "KnowledgeChunk", "collectionId": _WV_CID}
        ]
        self.schema_status = schema_status
        self.schema_raw = schema_raw
        self.meta_hits = 0
        self.schema_hits = 0
        self.graphql_queries: list[str] = []
        outer = self

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler 契约
                if self.path == "/v1/meta":
                    outer._serve_meta(self)
                elif self.path == "/v1/schema":
                    outer._serve_schema(self)
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):  # noqa: N802
                outer._serve_graphql(self)

            def log_message(self, *args):  # 静默访问日志
                pass

        self._server = HTTPServer(("127.0.0.1", 0), _Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def _serve_meta(self, request):
        self.meta_hits += 1
        body = json.dumps({"hostname": self.meta_hostname, "version": "1.0.0"}).encode()
        request.send_response(200)
        request.send_header("Content-Type", "application/json")
        request.end_headers()
        request.wfile.write(body)

    def _serve_schema(self, request):
        self.schema_hits += 1
        if self.schema_raw is not None:
            body = self.schema_raw
        else:
            body = json.dumps({"collections": self.collections}).encode()
        request.send_response(self.schema_status)
        request.send_header("Content-Type", "application/json")
        request.end_headers()
        request.wfile.write(body)

    def _serve_graphql(self, request):
        length = int(request.headers.get("Content-Length", "0"))
        payload = json.loads(request.rfile.read(length))
        self.graphql_queries.append(payload.get("query", ""))
        body = json.dumps(
            {
                "data": {
                    "Aggregate": {
                        "KnowledgeChunk_TOTAL": [{"meta": {"count": self.total}}],
                        "KnowledgeChunk_FILESYSTEM": [
                            {"meta": {"count": self.filesystem}}
                        ],
                    }
                }
            }
        ).encode()
        request.send_response(200)
        request.send_header("Content-Type", "application/json")
        request.end_headers()
        request.wfile.write(body)

    def stop(self):
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def fake_weaviate():
    instances = []

    def _make(**kwargs):
        wv = _FakeWeaviate(**kwargs)
        instances.append(wv)
        return wv

    yield _make
    for wv in instances:
        wv.stop()


def _wv_cfg(port: int) -> dict:
    return {"url": f"http://127.0.0.1:{port}", "class": "KnowledgeChunk"}


def _full_isolation(tmp_path: Path, port: int) -> dict:
    return {
        "pg_dsn": _DSN,
        "weaviate_url": _wv_cfg(port)["url"],
        "weaviate_class": "KnowledgeChunk",
        "trust_anchor": rp._load_trust_anchor(str(_write_anchor(tmp_path)))[0],
    }


# --------------------------------------------------------------------------- #
# T-ID-01:锚匹配 → 才进入隔离断言(正例全过 → PASS)
# --------------------------------------------------------------------------- #


def test_tid01_anchor_match_proceeds_to_isolation_assertions(tmp_path, psql_shim, fake_weaviate):
    psql_shim(f"iso_db\n{_PG_SID}\n0")
    wv = fake_weaviate(meta_hostname=f"http://127.0.0.1:1", total=5, filesystem=0)
    wv.meta_hostname = f"http://127.0.0.1:{wv.port}"
    m = _write_manifest(tmp_path)
    verdict, code = evaluate(str(m), verify_upload_isolation=True,
                             isolation=_full_isolation(tmp_path, wv.port))
    assert code == 0
    assert verdict["status"] == "pass"
    iso = _iso_checks(verdict)
    assert {c["status"] for c in iso} == {"pass"}
    # 独立锚查询确实发生:PG 会话含 pg_control_system;Weaviate 先 meta 后 schema
    argv = (tmp_path / "shim_argv.txt").read_text(encoding="utf-8")
    assert "SELECT system_identifier FROM pg_control_system()" in argv
    assert "SELECT current_database()" in argv
    assert wv.schema_hits == 1 and wv.meta_hits == 1
    assert any("Aggregate" in q for q in wv.graphql_queries), "身份全过后才发聚合断言"
    assert _FAKE_PW not in json.dumps(verdict)


def test_tid01_psql_missing_falls_back_to_driver_channel(tmp_path, monkeypatch):
    """psql 缺失(冻结镜像容器内)→ psycopg2 单会话只读通道,同一身份复核。"""
    executed: list[str] = []

    class _FakeCursor:
        def __init__(self, conn):
            self._conn = conn
            self._seq = [
                ("iso_db",), (_PG_SID,), (0,),
            ]

        def execute(self, sql):
            executed.append(" ".join(sql.split()))
            if not self._seq:
                raise RuntimeError("unexpected extra query")

        def fetchone(self):
            return self._seq.pop(0)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _FakeConn:
        def cursor(self):
            return _FakeCursor(self)

        def rollback(self):
            executed.append("ROLLBACK")

        def close(self):
            executed.append("CLOSE")

    fake_mod = types.ModuleType("psycopg2")
    fake_mod.connect = lambda **kwargs: executed.append(
        f"CONNECT host={kwargs['host']} port={kwargs['port']} db={kwargs['dbname']}"
    ) or _FakeConn()
    monkeypatch.setitem(sys.modules, "psycopg2", fake_mod)
    monkeypatch.setattr(rp, "_import_psycopg2", lambda: fake_mod)

    def _psql_missing(*a, **k):
        raise rp.IsolationChannelUnavailable("psql 不可用")

    monkeypatch.setattr(rp, "_pg_probe_psql", _psql_missing)
    rows = rp.probe_upload_mode_rows(
        {"dsn": _DSN, "expected_pg_system_id": _PG_SID}, 5
    )
    assert rows == 0
    assert executed[0].startswith("CONNECT host=dbhost port=6543")
    assert any("SELECT current_database()" in q for q in executed)
    assert any("SELECT system_identifier FROM pg_control_system()" in q for q in executed)
    assert any("SELECT count(*) FROM data_sources" in q for q in executed)
    assert "ROLLBACK" in executed and "CLOSE" in executed
    joined = " ".join(executed)
    assert _FAKE_PW not in joined, "连接细节绝不回显口令"


# --------------------------------------------------------------------------- #
# T-ID-02/03:同名库不同 system_id / 错误 PG 实例 → 拒(RED 孪生回归)
# --------------------------------------------------------------------------- #


def test_tid02_same_name_db_different_system_id_rejected(tmp_path, psql_shim):
    """同名库(iso_db)、不同物理集群 → 拒(修复 R2 假 PASS 的核心负例)。"""
    psql_shim(f"iso_db\n7339550012345678901\n0")  # dbname 自洽,但非锚定集群
    m = _write_manifest(tmp_path)
    verdict, code = evaluate(str(m), verify_upload_isolation=True,
                             isolation=_full_isolation(tmp_path, 1))
    assert code == 2
    pg = [c for c in _iso_checks(verdict) if c["name"] == "upload_mode_rows"]
    assert pg[0]["status"] == "fail"
    assert pg[0]["class"] == "isolation_upload_mode_identity_mismatch"
    assert "system_identifier" in pg[0]["reason"] and "信任锚钉扎值" in pg[0]["reason"]
    assert _FAKE_PW not in json.dumps(verdict)


def test_tid03_wrong_pg_instance_rejected(tmp_path, psql_shim):
    """错误 PG 实例(完全不同的 system_id)→ 拒。"""
    psql_shim("other_cluster_db\n0000000000000000002\n0")
    m = _write_manifest(tmp_path)
    verdict, code = evaluate(str(m), verify_upload_isolation=True,
                             isolation=_full_isolation(tmp_path, 1))
    assert code == 2
    pg = [c for c in _iso_checks(verdict) if c["name"] == "upload_mode_rows"]
    assert pg[0]["status"] == "fail"


def test_tid03_driver_channel_identity_mismatch_rejected(monkeypatch):
    """psycopg2 通道同样执行锚比对(身份不一致 → fail-closed,不给计数)。"""

    class _FakeCursor:
        _seq = [("iso_db",), ("9999999999999999999",), (0,)]

        def execute(self, sql):
            pass

        def fetchone(self):
            return self._seq.pop(0)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _FakeConn:
        def cursor(self):
            return _FakeCursor()

        def rollback(self):
            pass

        def close(self):
            pass

    fake_mod = types.ModuleType("psycopg2")
    fake_mod.connect = lambda **kwargs: _FakeConn()
    monkeypatch.setitem(sys.modules, "psycopg2", fake_mod)
    monkeypatch.setattr(rp, "_import_psycopg2", lambda: fake_mod)
    monkeypatch.setattr(
        rp, "_pg_probe_psql",
        lambda *a, **k: (_ for _ in ()).throw(rp.IsolationChannelUnavailable("no psql")),
    )
    with pytest.raises(rp.IsolationIdentityMismatch, match="信任锚钉扎值"):
        rp.probe_upload_mode_rows(
            {"dsn": _DSN, "expected_pg_system_id": _PG_SID}, 5
        )


# --------------------------------------------------------------------------- #
# T-ID-04/05/06:Weaviate 锚比对(错误实例 → 拒;错误/空集合 → BLOCKED;
# 自报 metadata 与锚冲突 → 拒)
# --------------------------------------------------------------------------- #


def test_tid04_wrong_weaviate_instance_rejected(tmp_path, fake_weaviate):
    """错误 Weaviate 实例:同名集合但 collectionId ≠ 锚 → fail-closed。"""
    wv = fake_weaviate(
        meta_hostname="http://x", total=5, filesystem=0,
        collections=[{"class": "KnowledgeChunk",
                      "collectionId": "ffffffff-0000-0000-0000-000000000000"}],
    )
    wv.meta_hostname = f"http://127.0.0.1:{wv.port}"
    m = _write_manifest(tmp_path)
    verdict, code = evaluate(str(m), verify_upload_isolation=True,
                             isolation=_full_isolation(tmp_path, wv.port))
    assert code == 2
    wvc = [c for c in _iso_checks(verdict) if c["name"] == "filesystem_objects"]
    assert wvc[0]["status"] == "fail"
    assert wvc[0]["class"] == "isolation_filesystem_identity_mismatch"
    assert "信任锚钉扎值" in wvc[0]["reason"]
    assert wv.graphql_queries == [], "身份未过绝不发聚合断言"


def test_tid05_wrong_or_empty_collection_blocked(tmp_path, fake_weaviate):
    """错误 collection(实例上不存在)→ BLOCKED;空集合 → BLOCKED。"""
    # (a) schema 无目标 collection
    wv = fake_weaviate(meta_hostname="http://x", total=0, filesystem=0,
                       collections=[{"class": "SomethingElse",
                                     "collectionId": _WV_CID}])
    wv.meta_hostname = f"http://127.0.0.1:{wv.port}"
    m = _write_manifest(tmp_path)
    verdict, code = evaluate(str(m), verify_upload_isolation=True,
                             isolation=_full_isolation(tmp_path, wv.port))
    assert code == 2
    wvc = [c for c in _iso_checks(verdict) if c["name"] == "filesystem_objects"]
    assert wvc[0]["status"] == "blocked"
    assert "/v1/schema 不存在" in wvc[0]["reason"]

    # (b) collectionId 匹配但总对象 = 0(空集合不构成隔离证据)
    wv2 = fake_weaviate(meta_hostname="http://x", total=0, filesystem=0)
    wv2.meta_hostname = f"http://127.0.0.1:{wv2.port}"
    verdict2, code2 = evaluate(str(m), verify_upload_isolation=True,
                               isolation=_full_isolation(tmp_path, wv2.port))
    assert code2 == 2
    wvc2 = [c for c in _iso_checks(verdict2) if c["name"] == "filesystem_objects"]
    assert wvc2[0]["status"] == "blocked"
    assert "总对象 = 0" in wvc2[0]["reason"]


def test_tid05_no_strong_identity_blocked_without_strength_reduction(tmp_path, fake_weaviate):
    """实例无 collectionId/uuid 强标识 → 子项如实 BLOCKED(列出可用字段名,
    不降低验证强度换 PASS)。"""
    wv = fake_weaviate(
        meta_hostname="http://x", total=5, filesystem=0,
        collections=[{"class": "KnowledgeChunk"}],  # 无任何强标识字段
    )
    wv.meta_hostname = f"http://127.0.0.1:{wv.port}"
    m = _write_manifest(tmp_path)
    verdict, code = evaluate(str(m), verify_upload_isolation=True,
                             isolation=_full_isolation(tmp_path, wv.port))
    assert code == 2
    wvc = [c for c in _iso_checks(verdict) if c["name"] == "filesystem_objects"]
    assert wvc[0]["status"] == "blocked"
    assert wvc[0]["class"] == "isolation_weaviate_identity_unprovable"
    assert "字段词表" in wvc[0]["reason"] and "collectionId" in wvc[0]["reason"]
    assert wv.graphql_queries == []


def test_tid06_self_reported_metadata_conflicting_anchor_rejected(tmp_path, fake_weaviate):
    """自报 metadata(/v1/meta hostname 与 URL 自洽)与锚冲突 → 拒:
    同源自洽不能替代独立锚。"""
    wv = fake_weaviate(
        meta_hostname="http://x", total=5, filesystem=0,
        collections=[{"class": "KnowledgeChunk",
                      "collectionId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}],
    )
    wv.meta_hostname = f"http://127.0.0.1:{wv.port}"  # meta 自洽(与 URL 一致)
    with pytest.raises(rp.IsolationIdentityMismatch, match="信任锚钉扎值"):
        rp.probe_filesystem_objects(
            {**_wv_cfg(wv.port), "expected_collection_id": _WV_CID}, 5
        )


# --------------------------------------------------------------------------- #
# T-ID-07/08:缺锚配置 / 锚来源不可读 → 拒(绝不执行隔离探针)
# --------------------------------------------------------------------------- #


def test_tid07_missing_anchor_config_rejected_no_probes(tmp_path, psql_shim, fake_weaviate):
    """缺锚(trust_anchor 未接)→ 单条 fail 检查;psql/Weaviate 探针零执行。"""
    argv_file = psql_shim(f"iso_db\n{_PG_SID}\n0")
    wv = fake_weaviate(meta_hostname="http://x", total=5, filesystem=0)
    wv.meta_hostname = f"http://127.0.0.1:{wv.port}"
    m = _write_manifest(tmp_path)
    verdict, code = evaluate(
        str(m),
        verify_upload_isolation=True,
        isolation={  # 无 trust_anchor / trust_anchor_error
            "pg_dsn": _DSN,
            "weaviate_url": _wv_cfg(wv.port)["url"],
            "weaviate_class": "KnowledgeChunk",
        },
    )
    assert code == 2
    iso = _iso_checks(verdict)
    assert len(iso) == 1
    assert iso[0]["class"] == "isolation_trust_anchor_invalid"
    assert iso[0]["status"] == "fail"
    assert "绝不进入隔离断言" in iso[0]["reason"]
    assert not (tmp_path / "shim_argv.txt").exists(), "psql 探针绝不被执行"
    assert wv.meta_hits == 0 and wv.schema_hits == 0, "Weaviate 探针绝不被执行"


def test_tid08_anchor_source_unreadable_or_invalid_rejected(tmp_path, capsys, monkeypatch):
    """锚来源不可读/非法 JSON/缺字段 → fail-closed(main 真实 CLI 路径)。"""
    monkeypatch.delenv("ISOLATION_PG_DSN", raising=False)
    m = _write_manifest(tmp_path)

    # (a) 文件不存在
    code = main([
        "--manifest", str(m), "--verify-upload-isolation",
        "--isolation-trust-anchor-file", str(tmp_path / "no-such-anchor.json"),
    ])
    assert code == 2
    verdict = json.loads(capsys.readouterr().out)
    assert _anchor_checks(verdict)[0]["class"] == "isolation_trust_anchor_invalid"
    assert "不可读" in _anchor_checks(verdict)[0]["reason"]

    # (b) 非法 JSON
    bad = tmp_path / "bad-anchor.json"
    bad.write_text("{not json", encoding="utf-8")
    code = main([
        "--manifest", str(m), "--verify-upload-isolation",
        "--isolation-trust-anchor-file", str(bad),
    ])
    assert code == 2
    verdict = json.loads(capsys.readouterr().out)
    assert "非合法 JSON" in _anchor_checks(verdict)[0]["reason"]

    # (c) 缺字段(部分锚 = 缺锚配置)
    partial = tmp_path / "partial-anchor.json"
    partial.write_text(json.dumps({"version": 1, "pg_system_id": _PG_SID}), encoding="utf-8")
    code = main([
        "--manifest", str(m), "--verify-upload-isolation",
        "--isolation-trust-anchor-file", str(partial),
    ])
    assert code == 2
    verdict = json.loads(capsys.readouterr().out)
    assert "weaviate_collection_id" in _anchor_checks(verdict)[0]["reason"]

    # (d) 词表外字段 / version 不符
    for payload in (
        {"version": 1, "pg_system_id": _PG_SID, "weaviate_collection_id": _WV_CID,
         "evil": "x"},
        {"version": 2, "pg_system_id": _PG_SID, "weaviate_collection_id": _WV_CID},
    ):
        p = tmp_path / "x-anchor.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        anchor, err = rp._load_trust_anchor(str(p))
        assert anchor is None and err


# --------------------------------------------------------------------------- #
# T-ID-09/10:全过后才执行隔离断言;身份失败时隔离结果绝不 PASS
# --------------------------------------------------------------------------- #


def test_tid09_identity_checks_precede_isolation_assertions(tmp_path, fake_weaviate):
    """身份链未过(schema 锚不一致)→ GraphQL 聚合断言绝不发出;
    锚全过 → 聚合才发生。"""
    m = _write_manifest(tmp_path)
    # 未过:错误 collectionId
    wv_bad = fake_weaviate(meta_hostname="http://x", total=5, filesystem=0,
                           collections=[{"class": "KnowledgeChunk",
                                         "collectionId": "ffff0000-1111-2222-3333-444444444444"}])
    wv_bad.meta_hostname = f"http://127.0.0.1:{wv_bad.port}"
    evaluate(str(m), verify_upload_isolation=True,
             isolation=_full_isolation(tmp_path, wv_bad.port))
    assert wv_bad.graphql_queries == [], "身份失败 → 计数断言绝不执行"
    # 过:正确 collectionId
    wv_ok = fake_weaviate(meta_hostname="http://x", total=5, filesystem=0)
    wv_ok.meta_hostname = f"http://127.0.0.1:{wv_ok.port}"
    evaluate(str(m), verify_upload_isolation=True,
             isolation=_full_isolation(tmp_path, wv_ok.port))
    assert wv_ok.schema_hits == 1
    assert len(wv_ok.graphql_queries) == 1, "身份全过 → 聚合断言恰好一次"


def test_tid10_identity_failure_never_yields_isolation_pass(tmp_path, psql_shim, fake_weaviate):
    """身份失败(锚不一致/缺失)时,任何隔离子项与整体 verdict 绝不 PASS。"""
    m = _write_manifest(tmp_path)
    # (a) PG 锚不一致
    psql_shim(f"iso_db\n7339550012345678901\n0")
    wv = fake_weaviate(meta_hostname="http://x", total=5, filesystem=0)
    wv.meta_hostname = f"http://127.0.0.1:{wv.port}"
    verdict, code = evaluate(str(m), verify_upload_isolation=True,
                             isolation=_full_isolation(tmp_path, wv.port))
    assert code == 2 and verdict["status"] == "fail"
    pg = [c for c in _iso_checks(verdict) if c["name"] == "upload_mode_rows"]
    assert pg[0]["status"] == "fail", "身份失败的通道绝不 PASS"
    # (b) 探针被外部假设"干净"(0/0)但身份失败 → 仍绝不 PASS(锚门禁在探针之前)
    psql_shim(f"iso_db\n{_PG_SID}\n0")
    wv_ok = fake_weaviate(meta_hostname="http://x", total=5, filesystem=0)
    wv_ok.meta_hostname = f"http://127.0.0.1:{wv_ok.port}"
    verdict2, code2 = evaluate(
        str(m), verify_upload_isolation=True,
        isolation={
            "pg_dsn": _DSN,
            "weaviate_url": _wv_cfg(wv_ok.port)["url"],
            "weaviate_class": "KnowledgeChunk",
            # 缺 trust_anchor → 锚门禁 fail(即使"探针会返回 0")
        },
    )
    assert code2 == 2 and verdict2["status"] == "fail"
    assert not any(c["status"] == "pass" for c in _iso_checks(verdict2))


# --------------------------------------------------------------------------- #
# 信任锚加载器 / 容器 env 组件通道 / CLI 接线
# --------------------------------------------------------------------------- #


def test_load_trust_anchor_contract(tmp_path):
    p = _write_anchor(tmp_path)
    anchor, err = rp._load_trust_anchor(str(p))
    assert err is None
    assert anchor == {"pg_system_id": _PG_SID, "weaviate_collection_id": _WV_CID.lower()}

    # 缺路径参数
    assert rp._load_trust_anchor(None)[1] and "缺" in rp._load_trust_anchor(None)[1]
    assert rp._load_trust_anchor("  ")[1]

    # 非法 system_id 形状
    bad = _write_anchor(tmp_path, pg_system_id="not-a-number-7100000000000000001x")
    anchor, err = rp._load_trust_anchor(str(bad))
    assert anchor is None and "十进制" in err

    # 大小写归一:UUID 大写锚与小写实测可比
    up = _write_anchor(tmp_path, weaviate_collection_id=_WV_CID.upper())
    anchor, err = rp._load_trust_anchor(str(up))
    assert err is None and anchor["weaviate_collection_id"] == _WV_CID.lower()


def test_dsn_from_pg_env_parts_assembles_in_memory_only():
    env = {
        "POSTGRES_HOST": "postgres",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "ask_ai",
        "POSTGRES_USER": "ask_ai",
        "POSTGRES_PASSWORD": "R3GRN-PARTPW/x@:",  # 特殊字符必须被 percent-encode
    }
    dsn = rp._dsn_from_pg_env_parts(env)
    assert dsn.startswith("postgresql://ask_ai:")
    assert "/" in dsn and "ask_ai" in dsn
    assert ":" in dsn.split("@")[0]  # 编码后的口令段
    fields = rp._pg_target_fields(dsn)
    assert fields["password"] == "R3GRN-PARTPW/x@:"  # 往返一致(内存内)
    assert fields["dbname"] == "ask_ai" and fields["host"] == "postgres"

    # 任一必需组件缺失 → None(绝不编造/回退)
    for missing in ("POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"):
        broken = dict(env)
        broken.pop(missing)
        assert rp._dsn_from_pg_env_parts(broken) is None
    assert rp._dsn_from_pg_env_parts({**env, "POSTGRES_PASSWORD": ""}) is None


def test_main_cli_parts_channel_and_env_weaviate(tmp_path, capsys, psql_shim, monkeypatch):
    """CLI 全接线:--isolation-pg-dsn-parts(容器 env 组件)+ env 变量名通道
    Weaviate + 锚文件 → PASS;argv 绝无任何 DSN/URL 值本身。"""
    psql_shim(f"iso_db\n{_PG_SID}\n0")
    monkeypatch.setenv("POSTGRES_HOST", "dbhost")
    monkeypatch.setenv("POSTGRES_PORT", "6543")
    monkeypatch.setenv("POSTGRES_DB", "iso_db")
    monkeypatch.setenv("POSTGRES_USER", "iso_user")
    monkeypatch.setenv("POSTGRES_PASSWORD", _FAKE_PW)
    anchor_file = _write_anchor(tmp_path)
    m = _write_manifest(tmp_path)
    # Weaviate 通道走 env 变量名(容器自身 env 语义):指向不可达端口 → 该子项
    # fail(连接失败),但 DSN 通道(锚匹配)应 PASS —— 验证装配通道真实生效
    monkeypatch.setenv("WEAVIATE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("WEAVIATE_CLASS_NAME", "KnowledgeChunk")
    code = main([
        "--manifest", str(m),
        "--verify-upload-isolation",
        "--isolation-pg-dsn-parts",
        "--isolation-weaviate-url-env", "WEAVIATE_URL",
        "--isolation-weaviate-class-env", "WEAVIATE_CLASS_NAME",
        "--isolation-trust-anchor-file", str(anchor_file),
    ])
    assert code == 2  # weaviate 127.0.0.1:1 不可达 → fail-closed(通道本身已生效)
    out = capsys.readouterr()
    verdict = json.loads(out.out)
    pg = [c for c in _iso_checks(verdict) if c["name"] == "upload_mode_rows"]
    assert pg[0]["status"] == "pass", "parts 装配通道 + 锚匹配 → PG 子项 PASS"
    wvc = [c for c in _iso_checks(verdict) if c["name"] == "filesystem_objects"]
    assert wvc[0]["status"] == "fail"
    assert _FAKE_PW not in out.out + out.err, "装配的 DSN 口令绝不外泄"
    argv = (tmp_path / "shim_argv.txt").read_text(encoding="utf-8")
    assert _FAKE_PW not in argv and "postgresql://" not in argv, "psql argv 只有参数化目标"


def test_cli_dsn_parts_channel_is_exclusive_no_silent_fallback(tmp_path, capsys, monkeypatch):
    """--isolation-pg-dsn-parts 显式给出 → 组件缺失即 BLOCKED,绝不静默回退
    ISOLATION_PG_DSN env 变量(无默认回退原则)。"""
    monkeypatch.setenv("ISOLATION_PG_DSN", _DSN)  # 旧通道有值,但 parts 通道缺组件
    monkeypatch.delenv("POSTGRES_HOST", raising=False)
    anchor_file = _write_anchor(tmp_path)
    m = _write_manifest(tmp_path)
    code = main([
        "--manifest", str(m),
        "--verify-upload-isolation",
        "--isolation-pg-dsn-parts",
        "--isolation-trust-anchor-file", str(anchor_file),
    ])
    assert code == 2
    verdict = json.loads(capsys.readouterr().out)
    pg = [c for c in _iso_checks(verdict) if c["name"] == "upload_mode_rows"]
    assert pg[0]["status"] == "blocked", "parts 通道缺组件 → BLOCKED,不回退旧通道"


def test_schema_identity_parser_shapes():
    """_schema_collection_identity:新旧响应形状封闭解析;无值不回显。"""
    item, cid, fields = rp._schema_collection_identity(
        {"collections": [{"class": "K", "collectionId": "u1"}]}, "K"
    )
    assert cid == "u1" and fields == ["class", "collectionId"]
    item, cid, _ = rp._schema_collection_identity(
        [{"class": "K", "uuid": "u2"}], "K"
    )
    assert cid == "u2"
    item, cid, _ = rp._schema_collection_identity(
        {"collections": [{"name": "K", "collectionId": "u3"}]}, "K"
    )
    assert cid == "u3"
    assert rp._schema_collection_identity({"collections": []}, "K")[0] is None
    assert rp._schema_collection_identity("garbage", "K")[0] is None
    assert rp._schema_collection_identity({"objects": [{"class": "K", "collectionId": "u4"}]}, "K")[1] == "u4"
    # re 词表:class 名合法性独立于 schema 解析
    assert re.fullmatch(rp._WEAVIATE_CLASS_RE.pattern, "KnowledgeChunk")
