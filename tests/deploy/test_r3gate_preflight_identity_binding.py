"""r3gate R2-4:preflight 隔离断言的目标身份绑定 + 防空集合假 PASS。

RED 实证(R1+R2-1 现码,2026-10-19):
- DB 探针只发 ``SELECT count(*)`` —— 身份不可证:错连任意"恰为 0"的库
  也会 PASS(经 psql shim 捕获 argv 证明无 current_database 查询);
- Weaviate 探针只发 filesystem 单聚合 —— 集合总对象 = 0(错连空集合)
  时返回 0 → PASS(假 PASS 实证)。

修复后(GREEN,本文件以真实执行路径钉住):
- DB:同一 psql 会话先 ``SELECT current_database()`` 再计数;与 DSN 声明
  精确一致才有效,不一致/缺身份行 → fail-closed(shim 捕获 argv + 输出);
- Weaviate:先 ``GET /v1/meta`` 并与显式期望(URL host:port)精确绑定;
  GraphQL 双聚合(total + filesystem),total = 0 → BLOCKED(不构成隔离
  证据);meta 不可达/不一致/非 200 → fail-closed;
- JSON verdict 绝不含 DSN/口令。
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

import scripts.release_preflight as rp
from scripts.release_preflight import evaluate, main

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FAKE_PW = "R2GRN-FAKEPW-IDENTITY"


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


# --------------------------------------------------------------------------- #
# psql shim(真实子进程执行路径;捕获 argv 与 PGPASSWORD)
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


_DSN = f"postgresql://iso_user:{_FAKE_PW}@dbhost:6543/iso_db"


# --------------------------------------------------------------------------- #
# R2-4①:DB 目标身份绑定(current_database() ↔ DSN 声明)
# --------------------------------------------------------------------------- #


def test_pg_probe_sends_identity_query_and_accepts_match(psql_shim):
    """探针必须先查 current_database();与声明一致 → 计数有效。"""
    argv_file = psql_shim("iso_db\n0")
    rows = rp.probe_upload_mode_rows({"dsn": _DSN}, 5)
    assert rows == 0
    argv = argv_file.read_text(encoding="utf-8")
    assert "SELECT current_database()" in argv, "必须执行身份复核查询"
    assert "SELECT count(*) FROM data_sources" in argv
    assert _FAKE_PW not in argv


def test_pg_probe_identity_mismatch_fails_closed(psql_shim):
    """current_database() ≠ DSN 声明 → fail-closed(错连他库绝不给计数)。"""
    psql_shim("some_other_db\n0")
    with pytest.raises(RuntimeError, match="身份不一致"):
        rp.probe_upload_mode_rows({"dsn": _DSN}, 5)


def test_pg_probe_identity_unreadable_fails_closed(psql_shim):
    """缺身份行(输出不可证)→ fail-closed。"""
    psql_shim("0")  # 只有一行:无身份行
    with pytest.raises(RuntimeError, match="身份不可证"):
        rp.probe_upload_mode_rows({"dsn": _DSN}, 5)


def test_pg_identity_checks_flow_into_verdict(tmp_path, psql_shim):
    """端到端:身份不一致 → isolation 子项 fail,整体非零;verdict 无秘密。"""
    psql_shim("wrong_db\n0")
    m = _write_manifest(tmp_path)
    verdict, code = evaluate(
        str(m),
        verify_upload_isolation=True,
        isolation={
            "pg_dsn": _DSN,
            "weaviate_url": "http://wvhost:8080",
            "weaviate_class": "KnowledgeChunk",
        },
    )
    assert code == 2
    pg = [c for c in _iso_checks(verdict) if c["name"] == "upload_mode_rows"]
    assert pg[0]["status"] == "fail"
    assert "身份不一致" in pg[0]["reason"]
    assert _FAKE_PW not in json.dumps(verdict)


# --------------------------------------------------------------------------- #
# R2-4②/③:Weaviate /v1/meta 绑定 + 防空集合假 PASS(真实本地 HTTP 服务)
# --------------------------------------------------------------------------- #


class _FakeWeaviate:
    """受控 Weaviate 替身:可配置 meta.hostname / 总数 / filesystem 数。"""

    def __init__(self, *, meta_hostname: str, total: int, filesystem: int):
        self.meta_hostname = meta_hostname
        self.total = total
        self.filesystem = filesystem
        self.meta_hits = 0
        self.graphql_queries: list[str] = []
        self.meta_status = 200
        outer = self

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler 契约
                outer._serve_meta(self)

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
        request.send_response(self.meta_status)
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


def test_weaviate_meta_binding_match_and_counts(fake_weaviate):
    """meta hostname 与 URL 绑定一致 + total>0 → filesystem 计数有效。"""
    wv = fake_weaviate(meta_hostname="http://127.0.0.1:1", total=5, filesystem=0)
    wv.meta_hostname = f"http://127.0.0.1:{wv.port}"
    fs = rp.probe_filesystem_objects(_wv_cfg(wv.port), 5)
    assert fs == 0
    assert wv.meta_hits == 1, "必须先做 /v1/meta 身份绑定"
    assert any("Aggregate" in q and "_TOTAL" in q for q in wv.graphql_queries)


def test_weaviate_meta_hostname_mismatch_fails_closed(fake_weaviate):
    """/v1/meta hostname ≠ 显式期望(URL host:port)→ fail-closed。"""
    wv = fake_weaviate(meta_hostname="http://elsewhere:9999", total=5, filesystem=0)
    with pytest.raises(RuntimeError, match="身份不一致"):
        rp.probe_filesystem_objects(_wv_cfg(wv.port), 5)


def test_weaviate_meta_missing_hostname_fails_closed(fake_weaviate):
    wv = fake_weaviate(meta_hostname="", total=5, filesystem=0)
    with pytest.raises(RuntimeError, match="身份不可证"):
        rp.probe_filesystem_objects(_wv_cfg(wv.port), 5)


def test_weaviate_meta_http_error_fails_closed(fake_weaviate):
    wv = fake_weaviate(meta_hostname="http://127.0.0.1:1", total=5, filesystem=0)
    wv.meta_status = 503
    with pytest.raises(RuntimeError, match="meta 探针 HTTP 503"):
        rp.probe_filesystem_objects(_wv_cfg(wv.port), 5)


def test_weaviate_empty_collection_blocked_never_pass(fake_weaviate):
    """R2-4③ 核心:总对象 = 0(错连空集合)→ 探针 BLOCKED,绝不返回 0 计数。"""
    wv = fake_weaviate(meta_hostname="http://127.0.0.1:1", total=0, filesystem=0)
    wv.meta_hostname = f"http://127.0.0.1:{wv.port}"
    with pytest.raises(rp.IsolationTargetUnproven, match="总对象 = 0"):
        rp.probe_filesystem_objects(_wv_cfg(wv.port), 5)


def test_weaviate_empty_collection_blocks_verdict(tmp_path, fake_weaviate):
    """端到端:空 collection → filesystem 子项 blocked → 整体非零退出。"""
    wv = fake_weaviate(meta_hostname="", total=0, filesystem=0)
    wv.meta_hostname = f"http://127.0.0.1:{wv.port}"
    m = _write_manifest(tmp_path)
    verdict, code = evaluate(
        str(m),
        verify_upload_isolation=True,
        isolation={
            "pg_dsn": "postgresql://u:p@dbhost:5432/iso_db",
            "weaviate_url": _wv_cfg(wv.port)["url"],
            "weaviate_class": "KnowledgeChunk",
        },
    )
    assert code == 2
    wv_checks = [c for c in _iso_checks(verdict) if c["name"] == "filesystem_objects"]
    assert wv_checks[0]["status"] == "blocked"
    assert "总对象 = 0" in wv_checks[0]["reason"]


def test_weaviate_binding_ok_and_clean_passes(tmp_path, fake_weaviate):
    """正例:绑定一致 + total>0 + filesystem=0 → PASS。"""
    wv = fake_weaviate(meta_hostname="", total=7, filesystem=0)
    wv.meta_hostname = f"http://127.0.0.1:{wv.port}"
    m = _write_manifest(tmp_path)
    verdict, code = evaluate(
        str(m),
        verify_upload_isolation=True,
        isolation={
            "pg_dsn": "postgresql://u:p@dbhost:5432/iso_db",
            "weaviate_url": _wv_cfg(wv.port)["url"],
            "weaviate_class": "KnowledgeChunk",
        },
    )
    assert code == 2  # pg 通道缺失(dbhost 不可达)→ fail;weaviate 子项应为 pass
    wv_checks = [c for c in _iso_checks(verdict) if c["name"] == "filesystem_objects"]
    assert wv_checks[0]["status"] == "pass"


def test_verdict_never_contains_dsn_or_password(tmp_path, psql_shim, capsys):
    """JSON verdict + stderr 绝不含 DSN/口令(端到端)。"""
    psql_shim("iso_db\n0")
    m = _write_manifest(tmp_path)
    code = main(
        [
            "--manifest", str(m),
            "--verify-upload-isolation",
            "--isolation-weaviate-url", "http://127.0.0.1:1",
            "--isolation-weaviate-class", "KnowledgeChunk",
        ]
    )
    assert code == 2  # weaviate 127.0.0.1:1 不可达
    out = capsys.readouterr()
    assert _FAKE_PW not in out.out + out.err
