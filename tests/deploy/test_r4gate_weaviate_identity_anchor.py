"""r3gate R4-1:Weaviate v1.28.0 真实版本兼容 —— 控制面+数据面组合身份锚。

A 实码复审阻塞(R3 = 三项确定性阻塞之一)要点:R3 新
``_schema_collection_identity()`` 只认 /v1/schema class 对象的
``collectionId``/``uuid``;生产 compose 固定
``cr.weaviate.io/semitechnologies/weaviate:1.28.0``,其官方 OpenAPI
``definitions.Class`` **没有**这些字段(本地同版实例 2026-10-20 实测一致:
class 词表 = class/description/invertedIndexConfig/multiTenancyConfig/
properties/replicationConfig/shardingConfig/vectorIndexConfig/
vectorIndexType/vectorizer);R3 绿色测试里的 collectionId 是 fake 构造
数据。另实测 1.28.0 ``/v1/meta.hostname`` = 绑定地址自述
``http://[::]:8080``,与客户端 URL 分属命名空间(R2 绑定在该版本默认配置
下不可满足);``/v1/nodes[0].name`` = CLUSTER_HOSTNAME 自报。

RED 实证(R3 现码 b9769af1,2026-10-20):
- fake fixture(1.28 真实 schema 形状,meta 自洽)→ IsolationIdentityUnprovable
  (collectionId 缺失)—— A 复审阻塞复现;
- 真实 1.28.0 实例 → IsolationIdentityMismatch(meta hostname≠URL)——
  真实版本第二不可满足点。

修复后(GREEN,本文件钉住 T-WV-01..14):
- 锚 v2(1.28.0)= 控制面+数据面组合锚:控制面(deploy workflow SSH 步骤,
  known_hosts 钉扎)只读 docker inspect(镜像 config digest/数据卷挂载/
  CLUSTER_HOSTNAME env)+ 数据卷元数据清单哈希,与 A 带外钉扎值任一不匹配
  → 容器 preflight 之前中止;数据面(本仓库 evaluator)把 URL 可达实例绑定
  到钉扎 CLUSTER_HOSTNAME(/v1/nodes 单节点 name 精确比对),集合存在 +
  总对象>0 + filesystem=0 断言不变;meta.hostname 自洽亦接受,绑定地址形态
  (::/0.0.0.0/*/空)放行给 nodes 绑定,其它实际 DNS 名 ≠ URL 一律拒;
- 锚 v1(新版 Weaviate collectionId 单层锚)语义原样保留;
- 诚实边界:数据卷内容钉扎后被整体原样替换且元数据恰好一致不可排除
  (PARTIAL 残余,如实保留,不在测试或文档中宣称排除)。

红线:全部 fake/本地 HTTP/本地真实 1.28.0 容器(离线);锚值均为测试自造
非秘密标识;不连生产、不 push、不改门值;真实执行路径(fake ssh/docker
shim + 真实子进程 + 真实 HTTP),非字符串断言。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
import yaml

import scripts.release_preflight as rp
from scripts.release_preflight import evaluate, main

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "deploy-production.yml"
EVALUATOR_SRC = REPO / "scripts" / "release_preflight.py"
# R5:卷元数据清单哈希扫描规范脚本(workflow 内嵌副本必须与其逐字节一致)
SCAN_SRC = REPO / "scripts" / "weaviate_volume_manifest_scan.sh"

_FAKE_PW = "R4GRN-FAKEPW-WVANCHOR"
_DSN = f"postgresql://iso_user:{_FAKE_PW}@dbhost:6543/iso_db"
_PG_SID = "7200000000000000002"
# 测试自造 v2 锚值(非秘密;绝不代表真实生产标识 —— 生产锚采集属 A-owned)
_CP_HOST = "fake-node-a1.invalid"
_CP_IMG = "sha256:" + "ab" * 32
_CP_VOL = "fake-t4_weaviate_data"
_CP_MAN = "cd" * 32
# uploads 守卫正例夹具:keep.txt 内容与其守卫行哈希严格一致(真实探针 clean 前提)
_KEEP_CONTENT = b"channel-adapt guard fixture upload\n"
_KEEP_SHA = hashlib.sha256(_KEEP_CONTENT).hexdigest()
_GUARD_TSV = f"retained/keep.txt\t{_KEEP_SHA}\n"

# 真实 1.28.0 /v1/schema class 形状 fixture(2026-10-20 本地同版实例实测
# 脱敏摘录;无 collectionId/uuid —— 与官方 spec definitions.Class 一致)
_REAL_128_CLASS = {
    "class": "KnowledgeChunk",
    "description": "real 1.28.0 shape fixture",
    "invertedIndexConfig": {
        "bm25": {"b": 0.75, "k1": 1.2},
        "cleanupIntervalSeconds": 60,
        "stopwords": {"additions": None, "preset": "en", "removals": None},
    },
    "multiTenancyConfig": {
        "autoTenantActivation": False,
        "autoTenantCreation": False,
        "enabled": False,
    },
    "properties": [
        {"name": "text", "dataType": ["text"], "tokenization": "word"},
        {"name": "source_type", "dataType": ["text"], "tokenization": "word"},
    ],
    "replicationConfig": {
        "asyncEnabled": False,
        "deletionStrategy": "NoAutomatedResolution",
        "factor": 1,
    },
    "shardingConfig": {
        "virtualPerPhysical": 128,
        "desiredCount": 1,
        "actualCount": 1,
        "desiredVirtualCount": 128,
        "actualVirtualCount": 128,
        "key": "_id",
        "strategy": "hash",
        "function": "murmur3",
    },
    "vectorIndexType": "hnsw",
    "vectorizer": "none",
}
# 真实 1.28.0 /v1/meta 与 /v1/nodes 实测形状(脱敏)
_REAL_128_META = {
    "grpcMaxMessageSize": 10485760,
    "hostname": "http://[::]:8080",  # 绑定地址自述(实测),非 CLUSTER_HOSTNAME
    "modules": {},
    "version": "1.28.0",
}


def _v2_anchor_file(tmp_path: Path, **overrides) -> Path:
    payload = {
        "version": 2,
        "pg_system_id": _PG_SID,
        "weaviate_cluster_hostname": _CP_HOST,
        "weaviate_image_digest": _CP_IMG,
        "weaviate_volume_name": _CP_VOL,
        "weaviate_volume_manifest_sha256": _CP_MAN,
    }
    payload.update(overrides)
    p = tmp_path / "trust-anchor-v2.json"
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


def _psql_shim(tmp_path: Path, monkeypatch, output: str) -> None:
    argv_file = tmp_path / "psql_shim_argv.txt"
    shim = tmp_path / "psql"
    # 残留电池语句(12 计数)→ 同会话身份行+全零+legacy=1;其余语句 → 原样输出
    shim.write_text(
        "#!/bin/bash\n"
        f'printf \'%s\\n\' "$@" > "{argv_file}"\n'
        'if printf \'%s\\n\' "$@" | grep -q "left(source_id"; then '
        'printf \'%s\\n\' "iso_db" && printf \'%s\\n\' "' + _PG_SID + '" && '
        'printf \'%s\\n\' "0|0|0|0|0|0|0|0|0|0|0|1"; '
        f'else printf \'%s\\n\' "{output}"; fi\n',
        encoding="utf-8",
    )
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")


# --------------------------------------------------------------------------- #
# Weaviate 1.28 形状替身(meta 绑定地址自述 + schema 无 collectionId + nodes)
# --------------------------------------------------------------------------- #


class _FakeWeaviate128:
    """受控 1.28 形状替身:meta/nodes/schema/graphql;故障注入参数化。"""

    def __init__(
        self,
        *,
        meta_hostname: str = "http://[::]:8080",
        nodes_names: list[str] | None = None,
        nodes_status: int = 200,
        nodes_raw: bytes | None = None,
        collections: list | None = None,
        schema_status: int = 200,
        meta_status: int = 200,
        total: int = 5,
        filesystem: int = 0,
        graphql_status: int = 200,
        aggregate_raw: bytes | None = None,
    ):
        self.meta_hostname = meta_hostname
        self.meta_status = meta_status
        self.nodes_names = nodes_names if nodes_names is not None else [_CP_HOST]
        self.nodes_status = nodes_status
        self.nodes_raw = nodes_raw
        self.collections = (
            collections
            if collections is not None
            else [dict(_REAL_128_CLASS)]
        )
        self.schema_status = schema_status
        self.total = total
        self.filesystem = filesystem
        self.graphql_status = graphql_status
        self.aggregate_raw = aggregate_raw
        self.meta_hits = 0
        self.nodes_hits = 0
        self.schema_hits = 0
        self.graphql_queries: list[str] = []
        outer = self

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                if self.path == "/v1/meta":
                    outer._serve(self, outer.meta_status, json.dumps(
                        {**_REAL_128_META, "hostname": outer.meta_hostname}).encode())
                    outer.meta_hits += 1
                elif self.path == "/v1/nodes":
                    outer.nodes_hits += 1
                    if outer.nodes_raw is not None:
                        outer._serve(self, outer.nodes_status, outer.nodes_raw)
                    else:
                        outer._serve(self, outer.nodes_status, json.dumps(
                            {"nodes": [
                                {"batchStats": {"queueLength": 0, "ratePerSecond": 0},
                                 "gitHash": "fakehash", "name": n, "shards": None,
                                 "status": "HEALTHY", "version": "1.28.0"}
                                for n in outer.nodes_names
                            ]}).encode())
                elif self.path == "/v1/schema":
                    outer.schema_hits += 1
                    outer._serve(self, outer.schema_status, json.dumps(
                        {"classes": outer.collections}).encode())
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                outer.graphql_queries.append(payload.get("query", ""))
                if outer.aggregate_raw is not None:
                    # 故障注入:原样回放损坏/非法聚合响应体(R2 count 严格化负例)
                    outer._serve(self, outer.graphql_status, outer.aggregate_raw)
                    return
                outer._serve(self, outer.graphql_status, json.dumps(
                    {"data": {"Aggregate": {
                        "KnowledgeChunk_TOTAL": [{"meta": {"count": outer.total}}],
                        "KnowledgeChunk_FILESYSTEM": [
                            {"meta": {"count": outer.filesystem}}
                        ],
                    }}}).encode())

            def log_message(self, *args):
                pass

        self._server = HTTPServer(("127.0.0.1", 0), _Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def _serve(self, request, status: int, body: bytes):
        request.send_response(status)
        request.send_header("Content-Type", "application/json")
        request.end_headers()
        request.wfile.write(body)

    def stop(self):
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def fake_wv128():
    instances = []

    def _make(**kwargs):
        wv = _FakeWeaviate128(**kwargs)
        instances.append(wv)
        return wv

    yield _make
    for wv in instances:
        wv.stop()


def _full_isolation_v2(tmp_path: Path, port: int) -> dict:
    return {
        "pg_dsn": _DSN,
        "weaviate_url": f"http://127.0.0.1:{port}",
        "weaviate_class": "KnowledgeChunk",
        "trust_anchor": rp._load_trust_anchor(str(_v2_anchor_file(tmp_path)))[0],
    }


# --------------------------------------------------------------------------- #
# 数据面:T-WV-01..08
# --------------------------------------------------------------------------- #


def test_twv01_v2_anchor_real_128_shape_full_pass(tmp_path, fake_wv128, monkeypatch):
    """v2 锚 + 真实 1.28 形状(meta 绑定地址自述/schema 无 collectionId/
    nodes name=钉扎)+ fs=0 → 全链 PASS;聚合在身份全过后恰好一次。"""
    _psql_shim(tmp_path, monkeypatch, f"iso_db\n{_PG_SID}\n0")
    wv = fake_wv128()  # 全部默认 = 真实 1.28 形状 + 匹配锚
    m = _write_manifest(tmp_path)
    verdict, code = evaluate(str(m), verify_upload_isolation=True,
                             isolation=_full_isolation_v2(tmp_path, wv.port))
    assert code == 0 and verdict["status"] == "pass"
    iso = _iso_checks(verdict)
    assert {c["status"] for c in iso} == {"pass"}
    wvc = [c for c in iso if c["name"] == "filesystem_objects"]
    assert wvc[0]["class"] == "isolation_filesystem_clean"
    assert wv.meta_hits == 1 and wv.nodes_hits == 1 and wv.schema_hits == 1
    assert len(wv.graphql_queries) == 1, "身份链(nodes 绑定)全过后才发聚合"
    assert _FAKE_PW not in json.dumps(verdict)


def test_twv02_wrong_nodes_name_mismatch_rejected(tmp_path, fake_wv128, monkeypatch):
    """nodes name ≠ 钉扎 CLUSTER_HOSTNAME → fail-closed;聚合绝不发出。"""
    _psql_shim(tmp_path, monkeypatch, f"iso_db\n{_PG_SID}\n0")
    wv = fake_wv128(nodes_names=["impostor-node.invalid"])
    m = _write_manifest(tmp_path)
    verdict, code = evaluate(str(m), verify_upload_isolation=True,
                             isolation=_full_isolation_v2(tmp_path, wv.port))
    assert code == 2
    wvc = [c for c in _iso_checks(verdict) if c["name"] == "filesystem_objects"]
    assert wvc[0]["status"] == "fail"
    assert wvc[0]["class"] == "isolation_filesystem_identity_mismatch"
    assert "CLUSTER_HOSTNAME" in wvc[0]["reason"]
    assert wv.graphql_queries == [], "身份失败 → 计数断言绝不执行"


def test_twv03_nodes_unprovable_blocked(tmp_path, fake_wv128, monkeypatch):
    """nodes 缺列表/空/多节点/缺 name → IsolationIdentityUnprovable(BLOCKED)。"""
    m = _write_manifest(tmp_path)
    cases = [
        (dict(nodes_raw=b'{"nodes": []}'), "空"),
        (dict(nodes_raw=b'{"status": "HEALTHY"}'), "缺列表"),
        (dict(nodes_names=["n1.invalid", "n2.invalid"]), "多节点"),
        (dict(nodes_raw=json.dumps(
            {"nodes": [{"status": "HEALTHY", "version": "1.28.0"}]}).encode()), "缺name"),
    ]
    for kwargs, label in cases:
        wv = fake_wv128(**kwargs)
        verdict, code = evaluate(str(m), verify_upload_isolation=True,
                                 isolation=_full_isolation_v2(tmp_path, wv.port))
        assert code == 2, label
        wvc = [c for c in _iso_checks(verdict) if c["name"] == "filesystem_objects"]
        assert wvc[0]["status"] == "blocked", label
        assert wvc[0]["class"] == "isolation_weaviate_identity_unprovable", label
        assert wv.graphql_queries == [], label


def test_twv04_v1_anchor_against_real_128_shape_still_blocked(tmp_path, fake_wv128):
    """v1 锚(collectionId 单层)对暴露 collectionId 的实例形状但 schema 缺该
    字段 → 如实 BLOCKED(meta 自洽以到达 collectionId 阶段,复刻 R3 语义);
    R3 阻塞在 v1 路径的诚实语义被钉住,绝不静默放行。"""
    wv = fake_wv128()
    wv.meta_hostname = f"http://127.0.0.1:{wv.port}"  # 自洽(新版本实例可满足)
    m = _write_manifest(tmp_path)
    anchor = {"pg_system_id": _PG_SID, "weaviate_collection_id":
              "01234567-89ab-cdef-0123-456789abcdef"}
    verdict, code = evaluate(
        str(m), verify_upload_isolation=True,
        isolation={
            "pg_dsn": _DSN,
            "weaviate_url": f"http://127.0.0.1:{wv.port}",
            "weaviate_class": "KnowledgeChunk",
            "trust_anchor": anchor,
        },
    )
    assert code == 2
    wvc = [c for c in _iso_checks(verdict) if c["name"] == "filesystem_objects"]
    assert wvc[0]["status"] == "blocked"
    assert wvc[0]["class"] == "isolation_weaviate_identity_unprovable"
    assert "collectionId" in wvc[0]["reason"]
    assert wv.graphql_queries == []


def test_twv05_v2_anchor_loader_shape_validation(tmp_path):
    """锚 v2 每个字段:缺失/形状非法/词表外/version 含混 → 一律拒绝(fail-closed)。"""
    good = json.loads(_v2_anchor_file(tmp_path).read_text(encoding="utf-8"))
    anchor, err = rp._load_trust_anchor(str(_v2_anchor_file(tmp_path)))
    assert err is None and anchor["weaviate_cluster_hostname"] == _CP_HOST

    bad_payloads = [
        {**good, "weaviate_image_digest": "sha256:XYZ"},
        {**good, "weaviate_image_digest": "ab" * 32},
        {**good, "weaviate_volume_manifest_sha256": "ZZ" * 32},
        {**good, "weaviate_cluster_hostname": "-bad-leading-dash"},
        {**good, "weaviate_volume_name": ""},
        {**good, "pg_system_id": "not-a-number"},
        {k: v for k, v in good.items() if k != "weaviate_cluster_hostname"},
        {**good, "evil": "x"},                                # 词表外
        {**good, "weaviate_collection_id": "01234567-89ab-cdef-0123-456789abcdef"},  # v1/v2 混装
        {**good, "version": 3},
        {**good, "version": 1},  # version=1 却带 v2 字段 → 词表外拒绝
        {**good, "weaviate_image_digest": "nothex"},
        {**good, "uploads_sources_dir": "relative/path"},
    ]
    for payload in bad_payloads:
        p = tmp_path / "bad-anchor.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        anchor, err = rp._load_trust_anchor(str(p))
        assert anchor is None and err, f"应拒绝: {sorted(payload)}"
    # 2026-10-22 通道:动态卷清单哈希可选(缺省=退出强制锚);上传面绑定
    # 字段可选且形状受校验
    ok = tmp_path / "ok-anchor.json"
    ok.write_text(json.dumps({k: v for k, v in good.items()
                              if k != "weaviate_volume_manifest_sha256"}),
                  encoding="utf-8")
    anchor, err = rp._load_trust_anchor(str(ok))
    assert anchor is not None and err is None, err
    assert "weaviate_volume_manifest_sha256" not in anchor
    ok2 = tmp_path / "ok-anchor2.json"
    ok2.write_text(json.dumps({**good,
                               "uploads_volume_name": "fake_uploads_data",
                               "uploads_mount_path": "/app/data/uploads",
                               "uploads_sources_dir": "/app/data/uploads/data-sources",
                               "uploads_unknown_guard": "/app/deploy/prod/uploads-unknown-guard.tsv"}),
                    encoding="utf-8")
    anchor2, err2 = rp._load_trust_anchor(str(ok2))
    assert anchor2 is not None and err2 is None, err2
    assert anchor2["uploads_sources_dir"] == "/app/data/uploads/data-sources"


def test_twv06_meta_dns_name_mismatch_rejected_in_v2(tmp_path, fake_wv128, monkeypatch):
    """v2 下 meta 自报**实际 DNS 名** ≠ URL(非绑定地址形态)→ 拒;
    绑定地址形态(::/0.0.0.0/*)放行给 nodes 绑定。"""
    m = _write_manifest(tmp_path)
    # (a) 别名代理自报自己的 DNS 名 → 拒
    wv = fake_wv128(meta_hostname="http://proxy.alias.invalid:8080")
    verdict, code = evaluate(str(m), verify_upload_isolation=True,
                             isolation=_full_isolation_v2(tmp_path, wv.port))
    assert code == 2
    wvc = [c for c in _iso_checks(verdict) if c["name"] == "filesystem_objects"]
    assert wvc[0]["status"] == "fail"
    assert wvc[0]["class"] == "isolation_filesystem_identity_mismatch"
    assert wv.graphql_queries == []
    # (b) 绑定地址形态变体(0.0.0.0)→ 放行,由 nodes 绑定身份(全链 PASS)
    _psql_shim(tmp_path, monkeypatch, f"iso_db\n{_PG_SID}\n0")
    wv2 = fake_wv128(meta_hostname="http://0.0.0.0:8080")
    verdict2, code2 = evaluate(str(m), verify_upload_isolation=True,
                               isolation=_full_isolation_v2(tmp_path, wv2.port))
    assert code2 == 0, "绑定地址形态不应构成身份失败"
    assert verdict2["status"] == "pass"


def test_twv07_identity_chain_order_nodes_before_aggregate(tmp_path, fake_wv128):
    """数据面顺序:meta sanity → nodes 绑定 → schema 存在性 → 聚合;
    nodes HTTP 失败 → probe_failed fail,聚合零执行。"""
    m = _write_manifest(tmp_path)
    wv = fake_wv128(nodes_status=500)
    verdict, code = evaluate(str(m), verify_upload_isolation=True,
                             isolation=_full_isolation_v2(tmp_path, wv.port))
    assert code == 2
    wvc = [c for c in _iso_checks(verdict) if c["name"] == "filesystem_objects"]
    assert wvc[0]["status"] == "fail"
    assert wvc[0]["class"] == "isolation_filesystem_probe_failed"
    assert wv.nodes_hits == 1 and wv.schema_hits == 0 and wv.graphql_queries == []


def test_twv08_collection_missing_or_empty_still_blocked_v2(tmp_path, fake_wv128):
    """v2 身份全过后,集合不存在/总对象=0 → 依旧 BLOCKED(不谎报 PASS)。"""
    m = _write_manifest(tmp_path)
    # (a) 集合不存在
    wv = fake_wv128(collections=[dict(_REAL_128_CLASS, **{"class": "Other"})])
    verdict, code = evaluate(str(m), verify_upload_isolation=True,
                             isolation=_full_isolation_v2(tmp_path, wv.port))
    assert code == 2
    wvc = [c for c in _iso_checks(verdict) if c["name"] == "filesystem_objects"]
    assert wvc[0]["status"] == "blocked" and "/v1/schema 不存在" in wvc[0]["reason"]
    # (b) 总对象 = 0
    wv2 = fake_wv128(total=0, filesystem=0)
    verdict2, code2 = evaluate(str(m), verify_upload_isolation=True,
                               isolation=_full_isolation_v2(tmp_path, wv2.port))
    assert code2 == 2
    wvc2 = [c for c in _iso_checks(verdict2) if c["name"] == "filesystem_objects"]
    assert wvc2[0]["status"] == "blocked" and "总对象 = 0" in wvc2[0]["reason"]


# --------------------------------------------------------------------------- #
# 真实 1.28.0 容器(离线本地实例;不可达即跳过 —— 保持套件确定性)
# --------------------------------------------------------------------------- #

_LIVE_URL = "http://127.0.0.1:8091"
_LIVE_CLASS = "AskDocument"
_LIVE_CLUSTER_HOSTNAME = "7adc06acc397"  # 与生产 compose 同值的本地实例 env(树内非秘密)


def _live_reachable() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8091), timeout=1):
            return True
    except OSError:
        return False


@pytest.mark.skipif(not _live_reachable(), reason="本地真实 1.28.0 实例未运行")
def test_twv09_live_real_128_instance_v2_anchor_clean_pass(tmp_path):
    """真实 1.28.0 实例端到端:锚 v2 钉扎 CLUSTER_HOSTNAME → 数据面全链通过,
    fs=0 → probe 返回 0(绝不触发 v1 的 collectionId BLOCKED)。"""
    anchor = rp._load_trust_anchor(str(_v2_anchor_file(
        tmp_path, weaviate_cluster_hostname=_LIVE_CLUSTER_HOSTNAME)))[0]
    objects = rp.probe_filesystem_objects(
        {
            "url": _LIVE_URL,
            "class": _LIVE_CLASS,
            "expected_cluster_hostname": anchor["weaviate_cluster_hostname"],
        },
        5,
    )
    assert objects == 0, "本地实例保持隔离净集(1 个 upload 对象、0 个 filesystem)"


# --------------------------------------------------------------------------- #
# 控制面(workflow SSH 步骤):T-WV-10..14(fake docker shim 真实执行路径)
# --------------------------------------------------------------------------- #

_ANCHOR_V2_JSON = json.dumps({
    "version": 2,
    "pg_system_id": "7300000000000000003",
    "weaviate_cluster_hostname": _CP_HOST,
    "weaviate_image_digest": _CP_IMG,
    "weaviate_volume_name": _CP_VOL,
    "weaviate_volume_manifest_sha256": _CP_MAN,
})


def _preflight_run_text() -> str:
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = wf["jobs"]["deploy"]["steps"]
    return [s for s in steps if s.get("id") == "preflight"][0]["run"]


_VOLSCAN_RE = re.compile(r"<<'VOLSCAN_SH'\n(.*?)\nVOLSCAN_SH\n", re.DOTALL)


def _volscan_embedded_script() -> str:
    """R5:提取 workflow preflight 步骤内嵌的卷扫描脚本;与仓库规范脚本
    scripts/weaviate_volume_manifest_scan.sh 逐字节一致(漂移即失败)。"""
    m = _VOLSCAN_RE.search(_preflight_run_text())
    assert m, "workflow preflight 未找到内嵌 VOLSCAN_SH 扫描脚本"
    embedded = m.group(1) + "\n"
    assert embedded == SCAN_SRC.read_text(encoding="utf-8"), \
        "workflow 内嵌卷扫描脚本与 scripts/weaviate_volume_manifest_scan.sh 漂移"
    return embedded


FAULT_EXEC_BOOTSTRAP = '#!/usr/bin/env python3\n# D1/D2 沙箱故障注入执行器(A 评审 2026-10-23):原样真实执行被测\n# python -c 代码;注入全部发生在 wrapper 层,被测生产代码零钩子。\n#   TSL_GUARD_WRITE_FAIL   os.write 创建后失败(部分写入后 ENOSPC)\n#   TSL_GUARD_TRUNCATE     os.write 静默截断(写入提前成功结束)\n#   TSL_GUARD_LN_RACE      os.link 发布前目标被并发创建(conflict=异内容 /\n#                           aligned=与冻结工件逐字节一致),link 返回 EEXIST\n#   TSL_D1_SWAP_PARENT     walk_to_parent 首次返回后(trace)父目录被移走,\n#                           原位替换为 symlink(检查-使用竞态注入)\n#   TSL_D2_CLEANUP_FAIL    清理执行失败(容器 exec 层失败模拟)\nimport os, sys, errno\n\nroot, code = sys.argv[1], sys.argv[2]\nargs = sys.argv[3:]\nenv = os.environ\n\nif "# askai-guard-release" in code and env.get("TSL_D2_CLEANUP_FAIL"):\n    print("__G3_REL_UNLINK_FAILED__")\n    sys.exit(1)\n\nreal_write, real_link, real_open = os.write, os.link, os.open\n\nif env.get("TSL_GUARD_WRITE_FAIL"):\n    def fault_write(fd, data):\n        if data:\n            real_write(fd, data[:4])\n        raise OSError(errno.ENOSPC, "injected write failure")\n    os.write = fault_write\nelif env.get("TSL_GUARD_TRUNCATE"):\n    def trunc_write(fd, data):\n        real_write(fd, data[:5])\n        return len(data)\n    os.write = trunc_write\n\nrace = env.get("TSL_GUARD_LN_RACE", "")\nif race in ("conflict", "aligned"):\n    def fault_link(src, dst, **kw):\n        target = next((a for a in args if a.startswith("/")), None)\n        if target is None:\n            raise OSError(errno.EINVAL, "no path arg")\n        body = (b"RACE-ATTACKER" if race == "conflict"\n                else env.get("TSL_GUARD_CONTENT", "").encode())\n        fd = real_open(os.path.dirname(target), os.O_RDONLY | os.O_DIRECTORY)\n        try:\n            tfd = real_open(".d2-race-file", os.O_WRONLY | os.O_CREAT | os.O_TRUNC,\n                            0o600, dir_fd=fd)\n            try:\n                real_write(tfd, body)\n            finally:\n                os.close(tfd)\n            real_link(".d2-race-file", os.path.basename(target),\n                      src_dir_fd=fd, dst_dir_fd=fd)\n        finally:\n            os.close(fd)\n        raise FileExistsError(errno.EEXIST, "injected publish race")\n    os.link = fault_link\n\nif env.get("TSL_D1_SWAP_PARENT"):\n    def tracer(frame, event, arg):\n        if event == "return" and frame.f_code.co_name == "walk_to_parent":\n            target = next((a for a in args if a.startswith("/")), None)\n            if target:\n                d = os.path.dirname(target)\n                if os.path.isdir(d) and not os.path.islink(d):\n                    os.rename(d, d + ".moved-by-attacker")\n                    os.symlink(d + ".moved-by-attacker", d)\n            sys.settrace(None)\n            return None\n        return tracer\n    sys.settrace(tracer)\n\nsys.argv = ["guard"] + args\ntry:\n    exec(code, {"__name__": "__main__"})\nexcept SystemExit as exc:\n    sys.exit(exc.code)\n'

D2_REPLACE_BOOTSTRAP = '#!/usr/bin/env python3\n# D2 注入:evaluator 运行前,目标守卫被【同内容、不同 inode】文件原子替换\n# (发布后-清理前的身份替换竞态确定性复现)。\nimport os, sys\nroot = sys.argv[1]\nd = os.path.join(root, "app", "deploy", "prod")\nbody = os.environ.get("TSL_GUARD_CONTENT", "").encode()\nfd = os.open(d, os.O_RDONLY | os.O_DIRECTORY)\ntry:\n    tfd = os.open(".d2-replace-tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC,\n                  0o600, dir_fd=fd)\n    try:\n        os.write(tfd, body)\n    finally:\n        os.close(tfd)\n    os.rename(".d2-replace-tmp", "uploads-unknown-guard.tsv",\n              src_dir_fd=fd, dst_dir_fd=fd)\nfinally:\n    os.close(fd)\nprint("[d2-inject] target replaced: same content, new inode", file=sys.stderr)\n'


REAL_EVAL_BOOTSTRAP = '''#!/usr/bin/env python3
# A 评审 R3 沙箱引导器:冻结 evaluator 真实执行(容器命名空间机械翻译)。
# 只做路径映射,内容零改动:/tmp 工件 → 容器根内工作流真实送达的文件;
# 信任锚副本仅把 uploads_sources_dir/uploads_unknown_guard 两个容器绝对
# 路径映射到容器根(其余字段逐字保留),evaluator 据此真实读取工作流
# 送达的 guard TSV 与真实挂载目录。
import json, os, subprocess, sys

root = sys.argv[1]
argv = sys.argv[2:]
anchor_c = os.path.join(root, "tmp", "askai-production-identity.json")
anchor_h = os.path.join(root, "tmp", "askai-production-identity.host.json")
with open(anchor_c, encoding="utf-8") as fh:
    ident = json.load(fh)
for key in ("uploads_sources_dir", "uploads_unknown_guard"):
    val = str(ident.get(key) or "")
    if val.startswith("/"):
        ident[key] = root + val
with open(anchor_h, "w", encoding="utf-8") as fh:
    json.dump(ident, fh)
out, i = [], 0
while i < len(argv):
    a = argv[i]
    if a == "--isolation-trust-anchor-file":
        out += [a, anchor_h]
        i += 2
        continue
    out.append(root + a if a.startswith("/tmp/") else a)
    i += 1
env = dict(os.environ)
env.setdefault("WEAVIATE_CLASS_NAME", "KnowledgeChunk")
env.setdefault("POSTGRES_HOST", "iso-db.invalid")
env.setdefault("POSTGRES_PORT", "5432")
env.setdefault("POSTGRES_DB", "iso_db")
env.setdefault("POSTGRES_USER", "iso")
env.setdefault("POSTGRES_PASSWORD", "secret")
sys.exit(subprocess.run(["python3"] + out, env=env).returncode)
'''


class ControlPlaneSandbox:
    """fake ssh + fake docker(compose)沙箱:机械执行 workflow preflight 步骤。"""

    def __init__(self, tmp: Path):
        self.base = tmp
        self.runner = tmp / "runner"
        self.remote_home = tmp / "remote-home"
        self.remote_tmp = tmp / "remote-tmp"
        self.container = tmp / "container"
        self.bin = tmp / "bin"
        self.logs = tmp / "logs"
        for d in (self.runner, self.remote_home / "ask-ai" / "deploy" / "prod",
                  self.remote_tmp, self.container / "tmp", self.bin, self.logs):
            d.mkdir(parents=True, exist_ok=True)
        # R5:沙箱 weaviate 数据卷种子文件 —— 卷清单扫描在沙箱内真实执行
        # (内容为固定测试字面量;元数据哈希由 step_env 用内嵌脚本实测)
        wv_vol = self.container / "var" / "lib" / "weaviate"
        (wv_vol / "shard-0").mkdir(parents=True, exist_ok=True)
        (wv_vol / "singleton.index").write_bytes(b"R5 volscan fixture A\n")
        (wv_vol / "shard-0" / "segment-0001.doc").write_bytes(b"R5 volscan fixture B\n")
        self.ssh_argv = self.logs / "ssh_argv.log"
        self.docker_argv = self.logs / "docker_argv.log"
        self.eval_argv = self.logs / "eval_argv.log"
        # 旧 r2 容器布局(构造期落位,先于任何测试写入):/app/deploy/prod
        # (有 compatibility.json 语义位、无守卫文件)+ uploads 真实挂载目录
        # (内容与缺省 TSL_GUARD_CONTENT 一致,供真实 evaluator 探针)
        (self.container / "app" / "deploy" / "prod").mkdir(parents=True, exist_ok=True)
        (self.container / "app" / "deploy" / "prod" / "compatibility.json").write_text(
            "{\"version\":1,\"rollback\":{\"previous_compatible\":true}}", encoding="utf-8")
        _up = (self.container / "app" / "data" / "uploads" / "data-sources" / "retained")
        _up.mkdir(parents=True, exist_ok=True)
        (_up / "keep.txt").write_bytes(_KEEP_CONTENT)
        self._write_shims()
        self._write_real_eval_helpers()

    def _write_real_eval_helpers(self) -> None:
        """A 评审 R3:冻结 evaluator 真实执行辅助。psql 按 SQL 文本回放真实
        形状输出(身份行/计数行;非 rc 代答);askai-real-eval 把 /tmp 工件
        参数与身份锚中的 uploads_* 容器绝对路径机械映射到沙箱容器根(内容
        零改动),冻结 evaluator 据此真实读取工作流送达的 guard TSV。"""
        (self.bin / "psql").write_text(
            "#!/bin/bash\n"
            "# R3 沙箱 psql 替身:按 SQL 文本回放真实形状输出(非 rc 代答)\n"
            'if printf \'%s\\n\' "$@" | grep -q "left(source_id"; then\n'
            '  printf \'%s\\n\' "iso_db" "${TSL_PSQL_SID:-7300000000000000003}" \\\n'
            '    "${TSL_PSQL_RESIDUE:-0|0|0|0|0|0|0|0|0|0|0|1}"\n'
            'elif printf \'%s\\n\' "$@" | grep -q "upload_mode"; then\n'
            '  printf \'%s\\n\' "iso_db" "${TSL_PSQL_SID:-7300000000000000003}" \\\n'
            '    "${TSL_PSQL_UPLOAD_COUNT:-0}"\n'
            'else\n'
            '  printf \'%s\\n\' "iso_db" "${TSL_PSQL_SID:-7300000000000000003}" "0"\n'
            "fi\n",
            encoding="utf-8",
        )
        (self.bin / "askai-real-eval").write_text(
            REAL_EVAL_BOOTSTRAP,
            encoding="utf-8",
        )
        (self.bin / "askai-fault-exec").write_text(
            FAULT_EXEC_BOOTSTRAP, encoding="utf-8")
        (self.bin / "askai-d2-replace").write_text(
            D2_REPLACE_BOOTSTRAP, encoding="utf-8")
        for shim in ("psql", "askai-real-eval", "askai-fault-exec", "askai-d2-replace"):
            (self.bin / shim).chmod(0o755)

    def _write_shims(self) -> None:
        (self.bin / "flock").write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
        (self.bin / "docker").write_text(
            "#!/bin/bash\n"
            'echo "$*" >> "$TSL_DOCKER_ARGV_LOG"\n'
            "args=()\n"
            'while [ $# -gt 0 ]; do args+=("$1"); shift; done\n'
            'case "${args[0]}" in\n'
            "  pull) exit 0 ;;\n"
            "  create) echo fakecid00000000 ;;\n"
            "  rm) exit 0 ;;\n"
            "  cp)\n"
            '    src="${args[1]}"; dest="${args[$((${#args[@]} - 1))]}"\n'
            '    case "$src" in\n'
            '      *RELEASE.json)\n'
            '        printf \'{"version":"1.0.0","git_sha":"%s","compatibility_contract":true}\' "$TSL_RELEASE_SHA" > "$dest" ;;\n'
            '      *release_preflight.py) cp "$TSL_EVALUATOR_SRC" "$dest" ;;\n'
            '      *compatibility.json)\n'
            '        printf \'{"version":1,"config":[],"host":[],"topology":[],'
            '"dependencies":[],"rollback":{"previous_compatible":true}}\' > "$dest" ;;\n'
            '      *production-identity.json)\n'
            '        if [ "${TSL_IDENTITY_MISSING:-}" = "1" ]; then exit 1; fi\n'
            '        printf \'%s\' "$TSL_IDENTITY_JSON" > "$dest" ;;\n'
            '      *uploads-unknown-guard.tsv)\n'
            '        if [ "${TSL_GUARD_MISSING:-}" = "1" ]; then exit 1; fi\n'
            '        printf \'%s\' "$TSL_GUARD_CONTENT" > "$dest" ;;\n'
            "      *) exit 1 ;;\n"
            "    esac ;;\n"
            "  inspect)\n"
            '    fmt="${args[@]:2}"\n'
            '    case "$fmt" in\n'
            "      *.Image*) echo \"$TSL_CP_IMAGE\" ;;\n"
            "      *Mounts*) if [ \"${args[1]}\" = \"fake-backend-cid\" ]; then echo \"${TSL_UP_VOLS:-fake-t4_uploads_data=/app/data/uploads }\"; else echo \"$TSL_CP_VOLS\"; fi ;;\n"
            "      *Config.Env*) printf '%s\\n' \"$TSL_CP_ENV\" | while IFS= read -r line; do echo \"$line\"; done ;;\n"
            '      *) echo "fake docker inspect: unknown fmt" >&2; exit 1 ;;\n'
            "    esac ;;\n"
            "  compose)\n"
            '    if [ "${TSL_PS_EMPTY:-}" = "1" ]; then exit 0; fi\n'
            '    sub=""\n'
            '    for i in "${!args[@]}"; do\n'
            '      case "${args[$i]}" in ps|exec) sub="${args[$i]}"; break;; esac\n'
            "    done\n"
            '    if [ "$sub" = "ps" ]; then\n'
            '      svc="${args[@]: -1}"\n'
            '      if [ "$svc" = "backend" ]; then echo fake-backend-cid; else echo fake-weaviate-cid; fi\n'
            '      exit 0\n'
            '    fi\n'
            '    exec_idx=-1; svc_idx=-1\n'
            '    for i in "${!args[@]}"; do\n'
            '      if [ "${args[$i]}" = "exec" ]; then exec_idx=$i; fi\n'
            '      if [ "$exec_idx" -ge 0 ] && [ "${args[$i]}" = "backend" ]; then svc_idx=$i; break; fi\n'
            "    done\n"
            '    if [ "$svc_idx" -lt 0 ]; then echo "fake compose: no backend exec" >&2; exit 1; fi\n'
            '    cmd=("${args[@]:$((svc_idx + 1))}")\n'
            '    case "${cmd[0]}" in\n'
            "      cat)\n"
            '        # deployed-version 事实读取:运行中 backend /app/RELEASE.json\n'
            '        if [ "${TSL_DEPLOYED_UNREADABLE:-}" = "1" ]; then exit 1; fi\n'
            '        printf \'{"version":"%s","git_sha":"deployed0sha"}\' "${TSL_DEPLOYED_VERSION:-1.0.0}" ;;\n'
            "      sh)\n"
            '        # sh -c 两种:cat > /tmp/xxx(stdin 写入容器根)/sha256sum(容器内\n'
            '        # 工件哈希 —— 对容器根内真实文件求值;TSL_TAMPER=1 注入不匹配)\n'
            '        case "${cmd[2]}" in\n'
            '          "if [ -L "*)\n'
            '            p="$(printf "%s" "${cmd[2]}" | sed -n "s/^if \\[ -L \\([^ ]*\\) .*/\\1/p")"\n'
            '            if [ -L "$TSL_CONTAINER_ROOT$p" ]; then echo __G3_SYMLINK__\n'
            '            elif [ -f "$TSL_CONTAINER_ROOT$p" ]; then\n'
            '              if command -v sha256sum >/dev/null 2>&1; then sha256sum "$TSL_CONTAINER_ROOT$p"; else shasum -a 256 "$TSL_CONTAINER_ROOT$p"; fi | cut -d\' \' -f1\n'
            '            else echo __G3_ABSENT__; fi\n'
            '            ;;\n'
            '          "cat > "*)\n'
            '            target="${cmd[2]#cat > }"\n'
            '            if [ -n "${TSL_GUARD_WRITE_FAIL:-}" ] && [ "$target" = "/app/deploy/prod/uploads-unknown-guard.tsv" ]; then\n'
            '              echo "fake: injected guard delivery failure" >&2; exit 1\n'
            '            fi\n'
            '            mkdir -p "$TSL_CONTAINER_ROOT$(dirname "$target")"\n'
            '            cat > "$TSL_CONTAINER_ROOT$target"\n'
            '            ;;\n'
            '          sha256sum*)\n'
            '            raw="${cmd[2]#sha256sum }"\n'
            '            f="${raw%% *}"\n'
            '            if [ -n "${TSL_TAMPER:-}" ]; then\n'
            '              echo "deadbeef00000000000000000000000000000000000000000000000000000000  $f"\n'
            '            elif [ -f "$TSL_CONTAINER_ROOT$f" ]; then\n'
            '              if command -v sha256sum >/dev/null 2>&1; then sha256sum "$TSL_CONTAINER_ROOT$f"; else shasum -a 256 "$TSL_CONTAINER_ROOT$f"; fi | sed "s#$TSL_CONTAINER_ROOT##"\n'
            '            else\n'
            '              exit 1\n'
            '            fi ;;\n'
            '          *)\n'
            '            echo "fake compose sh: unexpected: ${cmd[2]}" >&2; exit 1 ;;\n'
            '        esac ;;\n'
            "      rm)\n"
            '        shift_args=("${cmd[@]:2}")\n'
            '        for p in "${shift_args[@]}"; do\n'
            '          rm -f "$TSL_CONTAINER_ROOT$p" 2>/dev/null || true\n'
            "        done ;;\n"
            "      python3)\n"
            '        case "${cmd[1]}" in\n'
            '          -c)\n'
            '            # A 评审 D1/D2(2026-10-23):守卫送达/清理 python 代码\n'
            '            # 原样真实执行(容器绝对路径机械映射容器根);确定性故障\n'
            '            # 注入全部在 wrapper 层(测试侧):os.write 部分写入/静默\n'
            '            # 截断、os.link 发布竞态、父目录校验后替换(trace)、\n'
            '            # 清理失败 —— 被测生产代码零钩子\n'
            '            fargs=("${cmd[@]:3}")\n'
            '            for i in "${!fargs[@]}"; do\n'
            '              case "${fargs[$i]}" in /*) fargs[$i]="$TSL_CONTAINER_ROOT${fargs[$i]}" ;; esac\n'
            '            done\n'
            '            exec "$TSL_FAKEBIN/askai-fault-exec" "$TSL_CONTAINER_ROOT" "${cmd[2]}" "${fargs[@]}"\n'
            '            ;;\n'
            '          /tmp/askai-preflight-evaluator.py)\n'
            '            printf \'%s\\n\' "${cmd[*]}" >> "$TSL_EVAL_ARGV_LOG"\n'
            '            if [ "${TSL_D2_REPLACE_TARGET:-}" = "1" ]; then\n'
            '              "$TSL_FAKEBIN/askai-d2-replace" "$TSL_CONTAINER_ROOT" >&2\n'
            '            fi\n'
            '            if [ "${TSL_EVAL_REAL:-0}" = "1" ]; then\n'
            '              # A 评审 R3:真实执行冻结 evaluator —— 消费沙箱容器根内\n'
            '              # 工作流真实送达的工件(evaluator/manifest/身份锚/guard TSV);\n'
            '              # 只读通道替身 = PATH 内 psql(形状回放)+ TSL_WV_URL(fake 1.28)\n'
            '              export WEAVIATE_URL="${TSL_WV_URL:-}"\n'
            '              exec "$TSL_FAKEBIN/askai-real-eval" "$TSL_CONTAINER_ROOT" "${cmd[@]:1}"\n'
            '            fi\n'
            '            exit "${TSL_EVAL_RC:-0}"\n'
            '            ;;\n'
            '          *)\n'
            '            printf \'%s\\n\' "${cmd[*]}" >> "$TSL_EVAL_ARGV_LOG"\n'
            '            exit "${TSL_EVAL_RC:-0}"\n'
            '            ;;\n'
            '        esac ;;\n'
            "      *)\n"
            '        printf \'%s\\n\' "${cmd[*]}" >> "$TSL_EVAL_ARGV_LOG"\n'
            '        exit "${TSL_EVAL_RC:-0}"\n'
            "        ;;\n"
            "    esac ;;\n"
            '  *) echo "fake docker: unexpected $*" >&2; exit 1 ;;\n'
            "esac\n",
            encoding="utf-8",
        )
        (self.bin / "ssh").write_text(
            "#!/bin/bash\n"
            'echo "$*" >> "$TSL_SSH_ARGV_LOG"\n'
            'remote_cmd="${@: -1}"\n'
            'prefix="${remote_cmd%bash -s}"\n'
            'cat > "$TSL_SANDBOX/remote_script_captured.sh"\n'
            'eval "export ${prefix}"\n'
            'export HOME="$TSL_REMOTE_HOME"\n'
            'export TMPDIR="$TSL_REMOTE_TMP"\n'
            'export PATH="$TSL_FAKEBIN:$PATH"\n'
            'bash "$TSL_SANDBOX/remote_script_captured.sh"\n'
            "exit $?\n",
            encoding="utf-8",
        )
        # R5:跨平台 stat shim(按方言自适应,真实执行系统 stat,非 stub)。
        # 扫描脚本以 BusyBox `stat -c '%n|%s|%Y'` 语义调用;Linux GNU
        # coreutils 原生支持 -c → 直通;macOS BSD stat 无 -c → 转译为等价
        # BSD `-f '%N|%z|%m'`(#183:原 macOS-only 转译在 Ubuntu CI 触发
        # "cannot read file system information" ×15)。方言以运行时探测
        # 判定(GNU stat 独有 --version)。真实目标环境 BusyBox 原生支持
        # -c(已在 r4-weaviate-128 真实容器实测)不经本 shim。
        (self.bin / "stat").write_text(
            "#!/bin/bash\n"
            "if [ \"$1\" = \"-c\" ]; then\n"
            "    if /usr/bin/stat --version >/dev/null 2>&1; then\n"
            "        exec /usr/bin/stat \"$@\"\n"
            "    fi\n"
            "    if [ \"$2\" = \"%n|%s|%Y\" ]; then\n"
            "        shift 2\n"
            "        exec /usr/bin/stat -f '%N|%z|%m' \"$@\"\n"
            "    fi\n"
            "fi\n"
            "exec /usr/bin/stat \"$@\"\n",
            encoding="utf-8",
        )
        # R5:跨平台 sha256sum shim(真实执行,非 stub)。Linux coreutils
        # 原生 sha256sum → 直通;macOS 无 sha256sum → `shasum -a 256`
        # 透传(输出 `<64hex>  <文件名>` 与 BusyBox/coreutils 一致)。
        # (#183:原 shim 硬编码 macOS shasum,Ubuntu 下为潜在失败面。)
        (self.bin / "sha256sum").write_text(
            "#!/bin/bash\n"
            "if [ -x /usr/bin/sha256sum ]; then exec /usr/bin/sha256sum \"$@\"; fi\n"
            "if [ -x /bin/sha256sum ]; then exec /bin/sha256sum \"$@\"; fi\n"
            "exec /usr/bin/shasum -a 256 \"$@\"\n",
            encoding="utf-8",
        )
        for shim in ("flock", "docker", "ssh", "stat", "sha256sum"):
            (self.bin / shim).chmod(0o755)

    def step_env(self, *, identity_json: str | None = None, **overrides) -> dict:
        # 2026-10-22 通道:身份事实 = 沙箱 docker cp 提供的镜像内文件内容
        # (与被测 docker inspect 分离);动态清单哈希已退出,无 volscan 种子。
        if identity_json is None:
            identity_json = json.dumps({
                "version": 2,
                "pg_system_id": "7300000000000000003",
                "weaviate_cluster_hostname": _CP_HOST,
                "weaviate_image_digest": _CP_IMG,
                "weaviate_volume_name": _CP_VOL,
                "uploads_volume_name": "fake-t4_uploads_data",
                "uploads_mount_path": "/app/data/uploads",
                "uploads_sources_dir": "/app/data/uploads/data-sources",
                "uploads_unknown_guard": "/app/deploy/prod/uploads-unknown-guard.tsv",
            })
        overrides.setdefault("TSL_IDENTITY_JSON", identity_json)
        overrides.setdefault("TSL_GUARD_CONTENT", _GUARD_TSV)
        overrides.setdefault("TSL_RELEASE_SHA", "f" * 40)
        env = {
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "HOME": str(self.base / "runner-home"),
            "RUNNER_TEMP": str(self.runner),
            "TSL_SANDBOX": str(self.base),
            "TSL_FAKEBIN": str(self.bin),
            "TSL_REMOTE_HOME": str(self.remote_home),
            "TSL_REMOTE_TMP": str(self.remote_tmp),
            "TSL_CONTAINER_ROOT": str(self.container),
            "TSL_SSH_ARGV_LOG": str(self.ssh_argv),
            "TSL_DOCKER_ARGV_LOG": str(self.docker_argv),
            "TSL_EVAL_ARGV_LOG": str(self.eval_argv),
            "TSL_EVALUATOR_SRC": str(EVALUATOR_SRC),
            "TSL_CP_IMAGE": _CP_IMG,
            "TSL_CP_VOLS": f"{_CP_VOL}=/var/lib/weaviate ",
            "TSL_CP_ENV": f"CLUSTER_HOSTNAME={_CP_HOST}",
            "SSH_KEY": "R4GRN-FAKEKEY-NOT-A-REAL-KEY",
            "SSH_HOST": "tesla-t4.fake.invalid",
            "SSH_USER": "deployer",
            "SSH_KNOWN_HOSTS_B64": base64.b64encode(
                b"tesla-t4.fake.invalid ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFAKER4TST\n"
            ).decode(),
            "DEPLOY_TAG": "v1.0.0",
            "RELEASE_SHA": overrides.get("TSL_RELEASE_SHA", "f" * 40),
        }
        (self.base / "runner-home").mkdir(exist_ok=True)
        env.update(overrides)
        return env

    def run_step(self, env: dict, timeout: int = 90):
        script = self.base / "preflight_step.sh"
        script.write_text(_preflight_run_text(), encoding="utf-8")
        out_file = self.logs / "step_stdout.log"
        err_file = self.logs / "step_stderr.log"
        with open(out_file, "w") as fo, open(err_file, "w") as fe:
            proc = subprocess.Popen(  # noqa: S603 - 固定词表 argv
                ["bash", str(script)], stdout=fo, stderr=fe, env=env,
                cwd=str(self.base), start_new_session=True,
            )
            rc = proc.wait(timeout=timeout)
        return rc, out_file.read_text(encoding="utf-8"), err_file.read_text(encoding="utf-8")

    def eval_argv_text(self) -> str:
        """容器内 evaluator argv 日志(未执行 = 空串;日志文件可能不存在)。"""
        return (
            self.eval_argv.read_text(encoding="utf-8")
            if self.eval_argv.exists()
            else ""
        )

@pytest.fixture
def cp_sandbox(tmp_path):
    return ControlPlaneSandbox(tmp_path)


def test_twv10_control_plane_match_proceeds_to_container_preflight(cp_sandbox):
    """控制面全匹配 → 核验 PASS(a/c)→ 容器 preflight 真实执行 → 步骤成功。"""
    rc, out, err = cp_sandbox.run_step(cp_sandbox.step_env())
    assert rc == 0, f"应成功: {out}\n{err}"
    assert "控制面核验 PASS(a)" in out
    assert "控制面核验 PASS(c)" in out
    assert "PREFLIGHT PASS:v1.0.0" in out
    eval_argv = cp_sandbox.eval_argv_text()
    assert "--verify-upload-isolation" in eval_argv
    assert "--deployed-release-version 1.0.0" in eval_argv
    assert "--isolation-trust-anchor-file /tmp/askai-production-identity.json" in eval_argv
    docker_argv = cp_sandbox.docker_argv.read_text(encoding="utf-8")
    assert "inspect" in docker_argv and "exec" in docker_argv, "控制面只读 inspect/exec 真实发生"


def test_twv11_control_plane_digest_mismatch_aborts_before_preflight(cp_sandbox):
    """镜像 digest 不匹配 → 中止;容器内 evaluator 零执行、无 PASS。"""
    wrong = "sha256:" + "ff" * 32
    rc, out, err = cp_sandbox.run_step(
        cp_sandbox.step_env(TSL_CP_IMAGE=wrong)
    )
    assert rc != 0
    assert "已审核身份事实不一致" in err and "镜像" in err
    assert cp_sandbox.eval_argv_text() == "", "evaluator 绝不执行"
    assert "PREFLIGHT PASS" not in out


def test_twv12_control_plane_volume_hostname_mismatch_aborts(cp_sandbox):
    """数据卷挂载缺失 / CLUSTER_HOSTNAME 不匹配 → 全部中止(容器 preflight 之前)。"""
    for label, overrides in [
        ("volume", dict(TSL_CP_VOLS="some_other_volume=/var/lib/weaviate ")),
        ("hostname", dict(TSL_CP_ENV="CLUSTER_HOSTNAME=other-node.invalid")),
    ]:
        rc, out, err = cp_sandbox.run_step(cp_sandbox.step_env(**overrides))
        assert rc != 0, label
        assert "已审核身份事实不一致" in err, label
        assert cp_sandbox.eval_argv_text() == "", label


def test_twv13_control_plane_weaviate_not_running_aborts(cp_sandbox):
    """weaviate 容器未运行(compose ps 空)→ 身份无法核验 → 中止。"""
    rc, out, err = cp_sandbox.run_step(cp_sandbox.step_env(TSL_PS_EMPTY="1"))
    assert rc != 0
    assert "weaviate 容器未运行" in err
    assert cp_sandbox.eval_argv_text() == ""


def test_twv14_identity_file_missing_from_image_aborts(cp_sandbox):
    """2026-10-22 通道:镜像缺 deploy/prod/production-identity.json(打包违约)
    ⇒ fail-closed 中止(身份期望不可缺失,绝不退化为自证)。"""
    rc, out, err = cp_sandbox.run_step(cp_sandbox.step_env(TSL_IDENTITY_MISSING="1"))
    assert rc != 0
    assert "production-identity.json" in err
    assert cp_sandbox.eval_argv_text() == ""
    assert "PREFLIGHT PASS" not in out


def test_twv15_control_plane_invalid_identity_content_aborts(cp_sandbox):
    """身份事实内容非法(非 JSON/字段形状坏)→ fail-closed(容器 preflight 零执行)。"""
    bad_json = "{not-json"
    rc, out, err = cp_sandbox.run_step(
        cp_sandbox.step_env(identity_json=bad_json))
    assert rc != 0
    assert cp_sandbox.eval_argv_text() == ""
    bad_digest = json.dumps({
        "version": 2,
        "pg_system_id": "7300000000000000003",
        "weaviate_cluster_hostname": _CP_HOST,
        "weaviate_image_digest": "sha256:nothex",
        "weaviate_volume_name": _CP_VOL,
    })
    rc2, out2, err2 = cp_sandbox.run_step(
        cp_sandbox.step_env(identity_json=bad_digest))
    assert rc2 != 0
    assert cp_sandbox.eval_argv_text() == ""


def test_twv17_deployed_version_unreadable_aborts(cp_sandbox):
    """2026-10-22 通道:已部署版本事实不可读(运行中 backend /app/RELEASE.json
    不可得)⇒ previous_compatible=false 的回滚方向无法判定 → fail-closed 中止。"""
    rc, out, err = cp_sandbox.run_step(
        cp_sandbox.step_env(TSL_DEPLOYED_UNREADABLE="1"))
    assert rc != 0
    assert "已部署版本不可读" in err
    assert cp_sandbox.eval_argv_text() == ""
    assert "PREFLIGHT PASS" not in out


def test_twv18_uploads_guard_missing_from_image_aborts(cp_sandbox):
    """镜像缺 deploy/prod/uploads-unknown-guard.tsv(打包违约)→ fail-closed 中止。"""
    rc, out, err = cp_sandbox.run_step(
        cp_sandbox.step_env(TSL_GUARD_MISSING="1"))
    assert rc != 0
    assert "uploads-unknown-guard" in err
    assert cp_sandbox.eval_argv_text() == ""
    assert "PREFLIGHT PASS" not in out


def test_twv19_evaluator_content_integrity_tamper_aborts(cp_sandbox):
    """容器内侧哈希核对(评估器/manifest/身份事实/守卫)任一不匹配 ⇒ 绝不执行
    evaluator,fail-closed 中止(R4-3① 纪律在新工件面等价保留)。"""
    rc, out, err = cp_sandbox.run_step(
        cp_sandbox.step_env(TSL_TAMPER="1"))
    assert rc != 0
    assert "内容完整性核验失败" in err or "内容核验不匹配" in err
    assert "PREFLIGHT PASS" not in out


# --------------------------------------------------------------------------- #
# 通道适配修正(2026-10-22):冻结守卫送达 = 身份事实声明路径(A #138 c6341149628)
# --------------------------------------------------------------------------- #

import hashlib as _hashlib


def _delivered_guard_path(sandbox) -> Path:
    return sandbox.container / "app" / "deploy" / "prod" / "uploads-unknown-guard.tsv"


def _stale_temps(sandbox) -> list[str]:
    return [p.name for p in (sandbox.container / "app" / "deploy" / "prod")
            .glob(".askai-guard-new-*")]


def _run_real_eval_step(sandbox, **overrides):
    """启动 fake 1.28 Weaviate 并以 TSL_EVAL_REAL 跑 preflight 步骤。

    被测链路 = workflow 真实送达(容器内单次执行脚本)→ 冻结 evaluator
    真实入口(读取身份锚声明路径上的送达件 + 真实 uploads 目录);psql /
    Weaviate 只读通道由沙箱替身提供形状输出(与 fake ssh/docker 同款)。
    """
    wv = _FakeWeaviate128()
    try:
        env = sandbox.step_env(TSL_EVAL_REAL="1", TSL_WV_URL=f"http://127.0.0.1:{wv.port}",
                               **overrides)
        return sandbox.run_step(env, timeout=180)
    finally:
        wv.stop()


def test_r3_guard_delivery_linked_to_frozen_evaluator_clean_pass(cp_sandbox):
    """A 评审 R3 / AC1:工作流真实送达的 guard(身份锚声明路径)由冻结
    evaluator 真实入口消费 —— clean ⇒ 整链 PASS。

    证据约束(非另造 TSV/固定 rc):evaluator verdict 中的
    isolation_uploads_clean 只可能来自对【声明路径上送达件 × 真实挂载目录】
    的实际枚举+哈希;送达/cleanup 由容器内单次执行脚本真实完成。"""
    rc, out, err = _run_real_eval_step(cp_sandbox)
    assert rc == 0, f"{out[-2000:]}\n{err[-2000:]}"
    assert "PREFLIGHT PASS" in out
    # 冻结 evaluator 真实执行并输出 uploads 守卫 clean 判定(工作流 stdout
    # 捕获 evaluator verdict JSON)
    assert '"isolation_uploads_clean"' in out, out[-1500:]
    assert '"status": "pass"' in out, out[-1500:]
    # evaluator 以工作流 argv 真实运行(声明路径信任锚 + 隔离断言)
    eval_argv = cp_sandbox.eval_argv_text()
    assert "--verify-upload-isolation" in eval_argv
    assert "--isolation-trust-anchor-file /tmp/askai-production-identity.json" in eval_argv
    # 送达 = 身份声明路径(单次执行脚本位置参数)+ 容器内侧完整性核对
    docker_argv = cp_sandbox.docker_argv.read_text(encoding="utf-8")
    assert "/app/deploy/prod/uploads-unknown-guard.tsv" in docker_argv
    assert "sha256sum /app/deploy/prod/uploads-unknown-guard.tsv" in docker_argv
    # R2:cleanup = 精确所有权(送达件已移除;既有文件原状;零临时件残留)
    assert not _delivered_guard_path(cp_sandbox).exists()
    assert (cp_sandbox.container / "app" / "deploy" / "prod"
            / "compatibility.json").exists()
    assert _stale_temps(cp_sandbox) == []
    keep = (cp_sandbox.container / "app" / "data" / "uploads" / "data-sources"
            / "retained" / "keep.txt")
    assert keep.read_bytes() == _KEEP_CONTENT


def test_r3_uploads_drift_full_preflight_fails_no_deployment(cp_sandbox):
    """A 评审 R3 / AC2:uploads 真实漂移 ⇒ 冻结 evaluator(真实执行)判
    drift ⇒ 完整 preflight 非零退出,迁移/rollout 不执行(先于任何
    生产 mutation;evaluator 工件按所有权清理)。"""
    extra = (cp_sandbox.container / "app" / "data" / "uploads" / "data-sources"
             / "retained" / "orphan.txt")
    extra.write_bytes(b"drifted\n")
    rc, out, err = _run_real_eval_step(cp_sandbox)
    assert rc == 2, f"完整 preflight 必须以 evaluator rc=2 fail-closed: {out[-1500:]}"
    assert '"isolation_uploads_drift"' in out, out[-1500:]
    assert "PREFLIGHT PASS" not in out
    # evaluator 真实执行过(argv 在案),且后续部署动作零发生
    assert cp_sandbox.eval_argv_text() != ""
    docker_argv = cp_sandbox.docker_argv.read_text(encoding="utf-8")
    assert "up -d" not in docker_argv and "migrate" not in docker_argv
    # R2:失败路径同样精确清理(送达件移除;临时件零残留;/tmp 工件移除)
    assert not _delivered_guard_path(cp_sandbox).exists()
    assert _stale_temps(cp_sandbox) == []
    assert not (cp_sandbox.container / "tmp" / "askai-preflight-evaluator.py").exists()


def test_r3_blocked_delivery_evaluator_never_passes(cp_sandbox):
    """A 评审 R3 反证(阻断送达):送达失败(write_fail 注入)⇒ 工作流
    fail-closed 于 evaluator 之前 —— 绝不出现「未送达仍 PASS」;与
    clean/drift 两例合成完整联动矩阵。"""
    rc, out, err = _run_real_eval_step(cp_sandbox, TSL_GUARD_WRITE_FAIL="1")
    assert rc != 0
    assert "__G3_WRITE_FAIL__" in (out + err)
    assert "PREFLIGHT PASS" not in out
    assert cp_sandbox.eval_argv_text() == "", "evaluator 绝不执行"


def test_r1_parent_dir_symlink_escape_fails_closed(cp_sandbox):
    """A 评审 R1 / AC2:父目录为符号链接(/app/deploy/prod → 别处)⇒
    末级缺席不再触发写入别处 —— 祖先链校验 fail-closed,链接目标目录
    零新文件,evaluator 零执行。"""
    prod = cp_sandbox.container / "app" / "deploy" / "prod"
    hidden = cp_sandbox.base / "prod-hidden"
    elsewhere = cp_sandbox.base / "elsewhere-target"
    prod.rename(hidden)
    elsewhere.mkdir()
    prod.symlink_to(elsewhere)
    rc, out, err = cp_sandbox.run_step(cp_sandbox.step_env())
    assert rc != 0
    assert "父目录链含符号链接" in (out + err)
    assert list(elsewhere.iterdir()) == [], "链接目标目录绝无新文件(逃逸未发生)"
    assert cp_sandbox.eval_argv_text() == ""


def test_r2_write_failure_cleans_partial_temp_never_publishes(cp_sandbox):
    """A 评审 R2 / AC2:写入在文件创建后失败(部分写入)⇒ 临时件按
    所有权清理(trap),目标绝不发布,既有文件零改动,evaluator 零执行。"""
    rc, out, err = cp_sandbox.run_step(
        cp_sandbox.step_env(TSL_GUARD_WRITE_FAIL="1"))
    assert rc != 0
    assert "__G3_WRITE_FAIL__" in (out + err)
    assert not _delivered_guard_path(cp_sandbox).exists()
    assert _stale_temps(cp_sandbox) == [], "部分写入临时件必须被清理"
    assert cp_sandbox.eval_argv_text() == ""


def test_r2_partial_hash_mismatch_never_publishes(cp_sandbox):
    """A 评审 R2 / AC2:静默部分写入(写入提前成功结束但字节不完整)⇒
    发布前容器侧哈希核对拒绝(__G3_PARTIAL_HASH__),临时件清理、目标
    缺席,evaluator 零执行。"""
    rc, out, err = cp_sandbox.run_step(
        cp_sandbox.step_env(TSL_GUARD_TRUNCATE="1"))
    assert rc != 0
    assert "__G3_PARTIAL_HASH__" in (out + err)
    assert not _delivered_guard_path(cp_sandbox).exists()
    assert _stale_temps(cp_sandbox) == []
    assert cp_sandbox.eval_argv_text() == ""


def test_r2_publish_race_attacker_file_kept_fail_closed(cp_sandbox):
    """A 评审 R1/R2 / AC2:探针后、ln 发布前目标被并发创建(不同内容)⇒
    ln 排他失败 → 复核内容不一致 → fail-closed;并发方的文件既不被覆盖
    也不被误删,本次临时件清理,evaluator 零执行。"""
    rc, out, err = cp_sandbox.run_step(
        cp_sandbox.step_env(TSL_GUARD_LN_RACE="conflict"))
    assert rc != 0
    assert "__G3_RACE_CONFLICT__" in (out + err)
    target = _delivered_guard_path(cp_sandbox)
    assert target.read_text(encoding="utf-8") == "RACE-ATTACKER", \
        "并发方文件必须原样保留(不覆盖/不删除)"
    assert _stale_temps(cp_sandbox) == []
    assert cp_sandbox.eval_argv_text() == ""


def test_r2_publish_race_aligned_reuses_and_never_deletes(cp_sandbox):
    """A 评审 R2 / AC2:并发创建内容与冻结工件一致(__G3_RACE_ALIGNED__)
    ⇒ 复用放行;该文件非本次发布(GUARD_OWN=0)⇒ 成功后的清理绝不
    删除它 —— 误删旧文件风险的直接反证。"""
    rc, out, err = cp_sandbox.run_step(
        cp_sandbox.step_env(TSL_GUARD_LN_RACE="aligned"))
    assert rc == 0, f"{out}\n{err}"
    assert "复用不覆盖" in out
    target = _delivered_guard_path(cp_sandbox)
    assert target.exists(), "非本次发布的同内容文件绝不被清理删除"
    assert target.read_text(encoding="utf-8") == cp_sandbox.step_env()["TSL_GUARD_CONTENT"]


def test_d2_stale_temp_of_unknown_origin_never_deleted_retry_succeeds(cp_sandbox):
    """A 评审 D2 / AC2(异常中止后重新执行):上一轮 SIGKILL 残留的来源不明
    临时件 —— 不按名称模式猜测所有权、绝不盲删;本轮以 PID 唯一新名正常
    送达,成功后按 inode 身份回收本次对象。陈旧件原样保留(所有权不可证
    ⇒ 不触碰,交人工核验/受控 BLOCKED,而非静默清理)。"""
    prod = cp_sandbox.container / "app" / "deploy" / "prod"
    stale = prod / ".askai-guard-new-999"
    stale.write_bytes(b"stale-from-sigkill\n")
    rc, out, err = cp_sandbox.run_step(cp_sandbox.step_env())
    assert rc == 0, f"{out}\n{err}"
    assert not _delivered_guard_path(cp_sandbox).exists(), "本次对象已按身份回收"
    assert stale.read_bytes() == b"stale-from-sigkill\n", "来源不明陈旧件绝不盲删"
    assert [p.name for p in prod.glob(".askai-guard-new-*")] == [stale.name]


def test_d2_stale_symlink_temp_ignored_not_followed(cp_sandbox):
    """A 评审 D2:自有模式名被符号链接占用(来源不明)⇒ 不清扫/不跟随,
    本轮以不同 PID 名送达成功;链接与其目标零触碰。"""
    prod = cp_sandbox.container / "app" / "deploy" / "prod"
    outside = cp_sandbox.base / "outside-secret2"
    outside.write_text("do-not-touch\n", encoding="utf-8")
    (prod / ".askai-guard-new-777").symlink_to(outside)
    rc, out, err = cp_sandbox.run_step(cp_sandbox.step_env())
    assert rc == 0, f"{out}\n{err}"
    assert outside.read_text(encoding="utf-8") == "do-not-touch\n"
    assert not _delivered_guard_path(cp_sandbox).exists()
    assert (prod / ".askai-guard-new-777").is_symlink(), "来源不明链接原样保留"


def test_d1_parent_replaced_after_check_fails_closed_no_escape(cp_sandbox):
    """A 评审 D1 / AC2(检查-使用竞态):父目录校验通过【之后】、创建/发布
    之前被替换为 symlink(trace 注入于 walk_to_parent 首次返回,被测代码
    原样真实执行)⇒ 双次解析交叉核对捕获 ⇒ fail-closed;被移走目录与
    链接目标目录均零新文件;evaluator 零执行。"""
    rc, out, err = cp_sandbox.run_step(
        cp_sandbox.step_env(TSL_D1_SWAP_PARENT="1"))
    assert rc != 0
    assert "__G3_PARENT_UNSTABLE__" in (out + err)
    prod = cp_sandbox.container / "app" / "deploy" / "prod"
    moved = cp_sandbox.container / "app" / "deploy" / "prod.moved-by-attacker"
    assert prod.is_symlink() and moved.is_dir(), "注入确实发生在检查之后"
    # 被移走目录内仅允许沙箱构造期 fixture(compatibility.json 随目录整体
    # 被移走);本轮送达对象零新建 = 写入未发生
    assert {p.name for p in moved.iterdir()} <= {"compatibility.json"}, \
        "被移走目录零新文件(写入未发生)"
    # 经替换后 symlink 解析也不得出现守卫文件
    assert not (cp_sandbox.container / "app" / "deploy" / "prod"
                / "uploads-unknown-guard.tsv").exists()
    assert cp_sandbox.eval_argv_text() == ""
    docker_argv = cp_sandbox.docker_argv.read_text(encoding="utf-8")
    assert "up -d" not in docker_argv and "migrate" not in docker_argv


def test_d2_same_content_replacement_not_deleted_and_no_pass(cp_sandbox):
    """A 评审 D2 / AC2(发布后同内容替换):evaluator 运行前目标被【同内容
    不同 inode】文件原子替换 ⇒ evaluator 判 clean(内容相同),但清理身份
    核对失败(dev:ino 不匹配)⇒ 拒删替换文件 + 完整 preflight 非零,
    绝不输出 PREFLIGHT PASS。内容相同 ≠ 文件身份相同。"""
    rc, out, err = _run_real_eval_step(cp_sandbox, TSL_D2_REPLACE_TARGET="1")
    assert rc != 0, "清理身份不可证必须阻断 PASS"
    assert "__G3_REL_IDENTITY_MISMATCH__" in (out + err)
    assert "PREFLIGHT PASS" not in out
    assert cp_sandbox.eval_argv_text() != "", "evaluator 已真实执行(clean 联动)"
    assert '"isolation_uploads_clean"' in out, "替换件内容与冻结件一致 ⇒ evaluator 判 clean"
    target = _delivered_guard_path(cp_sandbox)
    assert target.exists(), "同内容替换文件不得被误删"
    assert target.read_text(encoding="utf-8") == cp_sandbox.step_env()["TSL_GUARD_CONTENT"]
    assert _stale_temps(cp_sandbox) == []


def test_d2_cleanup_failure_blocks_pass(cp_sandbox):
    """A 评审 D2 / AC2(清理失败):容器清理执行失败(注入)⇒ 整体
    preflight 非零退出、无 PREFLIGHT PASS,送达件如实留存待人工核验
    (绝不 || true 吞掉清理失败)。"""
    rc, out, err = _run_real_eval_step(cp_sandbox, TSL_D2_CLEANUP_FAIL="1")
    assert rc != 0
    assert "PREFLIGHT PASS" not in out
    assert "清理未通过" in (out + err)
    target = _delivered_guard_path(cp_sandbox)
    assert target.exists(), "清理失败 ⇒ 工件如实留存(不谎报 clean)"


def test_d2_pre_delivery_control_plane_failure_leaves_existing_files_untouched(cp_sandbox):
    """A 评审 D2 / AC2(送达前控制面失败):preflight 在送达之前失败
    (已部署版本不可读注入)⇒ EXIT trap 对容器零删除操作 —— 旧容器内
    既有同路径守卫文件与陈旧临时名文件逐字节原样保留。"""
    target = _delivered_guard_path(cp_sandbox)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(cp_sandbox.step_env()["TSL_GUARD_CONTENT"], encoding="utf-8")
    stale = target.parent / ".askai-guard-new-999"
    stale.write_bytes(b"pre-existing-unknown\n")
    before_t, before_s = target.read_bytes(), stale.read_bytes()
    rc, out, err = cp_sandbox.run_step(
        cp_sandbox.step_env(TSL_DEPLOYED_UNREADABLE="1"))
    assert rc != 0
    assert "已部署版本不可读" in (out + err)
    assert target.read_bytes() == before_t, "既有文件零改动"
    assert stale.read_bytes() == before_s, "既有陈旧名文件零触碰"
    assert cp_sandbox.eval_argv_text() == ""


def test_guard_preexisting_same_content_reused_not_overwritten(cp_sandbox):
    """送达目标已存在且内容与冻结工件一致 ⇒ 复用不覆盖(旧容器既有文件
    原状保留),部署继续;成功后的清理绝不删除该既有文件(所有权=0)。"""
    target = _delivered_guard_path(cp_sandbox)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(cp_sandbox.step_env()["TSL_GUARD_CONTENT"], encoding="utf-8")
    before = target.read_bytes()
    rc, out, err = cp_sandbox.run_step(cp_sandbox.step_env())
    assert rc == 0, f"{out}\n{err}"
    assert "已存在且内容与冻结工件一致" in out
    docker_argv = cp_sandbox.docker_argv.read_text(encoding="utf-8")
    assert "cat > /app/deploy/prod/uploads-unknown-guard.tsv" not in docker_argv
    assert target.read_bytes() == before, "既有文件绝不被覆盖"
    assert target.exists(), "复用的既有文件绝不被清理删除(所有权=0)"


def test_guard_preexisting_different_content_fails_closed(cp_sandbox):
    """AC2:送达目标已存在但内容与冻结工件不一致 ⇒ 绝不覆盖/择一,
    零 rollout fail-closed(evaluator 零执行)。"""
    target = _delivered_guard_path(cp_sandbox)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("UNTRUSTED-CONTENT\n", encoding="utf-8")
    rc, out, err = cp_sandbox.run_step(cp_sandbox.step_env())
    assert rc != 0
    assert "已存在但内容与冻结工件不一致" in (err + out)
    assert cp_sandbox.eval_argv_text() == "", "evaluator 绝不执行"
    assert target.read_text(encoding="utf-8") == "UNTRUSTED-CONTENT\n", "不可信既有文件绝不被覆盖"
    assert _stale_temps(cp_sandbox) == []


def test_guard_symlink_escape_fails_closed(cp_sandbox):
    """AC2:送达目标为符号链接(路径逃逸风险)⇒ 绝不写入,fail-closed。"""
    target = _delivered_guard_path(cp_sandbox)
    target.parent.mkdir(parents=True, exist_ok=True)
    outside = cp_sandbox.base / "outside-secret"
    outside.write_text("do-not-touch\n", encoding="utf-8")
    target.symlink_to(outside)
    rc, out, err = cp_sandbox.run_step(cp_sandbox.step_env())
    assert rc != 0
    assert "符号链接" in (err + out)
    assert outside.read_text(encoding="utf-8") == "do-not-touch\n", "逃逸写入未发生"
    assert cp_sandbox.eval_argv_text() == ""


def test_guard_identity_missing_valid_path_fails_closed(cp_sandbox):
    """AC2:身份事实缺少合法 uploads 守卫路径(缺字段/相对路径/含 ..)
    ⇒ fail-closed(冻结 evaluator 按声明路径读取,路径不可信即中止)。"""
    for bad in (
        {"uploads_unknown_guard": "relative/path.tsv"},
        {"uploads_unknown_guard": "/app/../etc/uploads-unknown-guard.tsv"},
        {},
    ):
        identity = json.loads(cp_sandbox.step_env()["TSL_IDENTITY_JSON"])
        identity.update(bad)
        identity.pop("uploads_unknown_guard", None) if bad == {} else None
        rc, out, err = cp_sandbox.run_step(
            cp_sandbox.step_env(identity_json=json.dumps(identity)))
        assert rc != 0, bad
        assert "缺少合法 uploads 守卫路径" in (err + out), bad
        assert cp_sandbox.eval_argv_text() == "", bad


# --------------------------------------------------------------------------- #
# CLI 全链:T-WV-16(v2 锚 + psql + fake 1.28 weaviate → verdict pass)
# --------------------------------------------------------------------------- #


def test_twv16_cli_full_chain_v2_anchor_verdict_pass(tmp_path, fake_wv128, monkeypatch):
    """main 真实 CLI:v2 锚文件 + psql shim + fake 1.28 形状 weaviate →
    exit 0 / verdict pass;argv 绝无 DSN;DSN 口令绝不进 stdout/stderr。"""
    wv = fake_wv128()
    _psql_shim(tmp_path, monkeypatch, f"iso_db\n{_PG_SID}\n0")
    monkeypatch.setenv("ISOLATION_PG_DSN", _DSN)
    monkeypatch.setenv("WEAVIATE_URL", f"http://127.0.0.1:{wv.port}")
    monkeypatch.setenv("WEAVIATE_CLASS_NAME", "KnowledgeChunk")
    m = _write_manifest(tmp_path)
    anchor_file = _v2_anchor_file(tmp_path)
    code = main([
        "--manifest", str(m),
        "--verify-upload-isolation",
        "--isolation-pg-dsn-env", "ISOLATION_PG_DSN",
        "--isolation-weaviate-url-env", "WEAVIATE_URL",
        "--isolation-weaviate-class-env", "WEAVIATE_CLASS_NAME",
        "--isolation-trust-anchor-file", str(anchor_file),
    ])
    assert code == 0
    argv = (tmp_path / "psql_shim_argv.txt").read_text(encoding="utf-8")
    assert _FAKE_PW not in argv and "postgresql://" not in argv


# --------------------------------------------------------------------------- #
# R2 复审阻塞窄修(AC2):Weaviate Aggregate count 严格化 —— T-WV-20..22
# (真实 HTTP fake Weaviate 路径;RED 于 R1 现码 823b025c 实测)
# --------------------------------------------------------------------------- #


def _filesystem_objects_check(verdict: dict) -> dict:
    wvc = [c for c in _iso_checks(verdict) if c["name"] == "filesystem_objects"]
    assert wvc, "verdict 缺 filesystem_objects 检查项"
    return wvc[0]


@pytest.mark.parametrize(
    "bad",
    [False, True, 0.0, 0.5, "0", "3", None, -1],
    ids=lambda v: f"fs-count={v!r}",
)
def test_twv20_illegal_filesystem_count_never_clean_pass(
    tmp_path, fake_wv128, monkeypatch, bad
):
    """T-WV-20:total 为合法正整数而 filesystem meta.count 为非法类型
    (bool/float/字符串/null/负数)→ 绝不产生 clean PASS,也绝不把非法
    证据经 int() 隐式转换成任何计数断言 —— 一律 probe_failed fail-closed。
    RED(823b025c 实测):false/0.0/0.5/"0" 隐式转 0 → 假 clean PASS;
    True/"3" 隐式转 1/3 → 假 objects_present;null/负数本已 fail-closed
    (负例钉住不回归)。"""
    _psql_shim(tmp_path, monkeypatch, f"iso_db\n{_PG_SID}\n0")
    wv = fake_wv128(total=5, filesystem=bad)
    m = _write_manifest(tmp_path)
    verdict, code = evaluate(str(m), verify_upload_isolation=True,
                             isolation=_full_isolation_v2(tmp_path, wv.port))
    label = f"filesystem meta.count={bad!r}"
    assert code == 2, f"{label} 必须 fail-closed,绝不 PASS"
    chk = _filesystem_objects_check(verdict)
    assert (
        chk["status"] == "fail"
        and chk["class"] == "isolation_filesystem_probe_failed"
    ), (
        f"{label} 必须以 probe_failed fail-closed(未知/非法计数不得产生 "
        f"PASS,也不得转换成其它计数断言),实测 {chk['class']}/{chk['status']}"
    )
    assert len(wv.graphql_queries) == 1 and "Aggregate" in wv.graphql_queries[0], \
        f"{label}:聚合必须真实执行过(非身份短路)"


@pytest.mark.parametrize(
    "raw, shape_label",
    [
        (b'{"data": {"Aggregate": {}}}', "alias 缺失"),
        (b'{"data": {"Aggregate": {"KnowledgeChunk_TOTAL": 5,'
         b' "KnowledgeChunk_FILESYSTEM": 0}}}', "groups 非列表"),
        (b'{"data": {"Aggregate": {"KnowledgeChunk_TOTAL": [{}],'
         b' "KnowledgeChunk_FILESYSTEM": [{"meta": {"count": 0}}]}}}', "meta 缺失"),
        (b'{"data": {"Aggregate": {"KnowledgeChunk_TOTAL": [{"meta": {"count": 5}}],'
         b' "KnowledgeChunk_FILESYSTEM": [{"meta": {}}]}}}', "count 缺失"),
        (b'{"data": {"Aggregate": {"KnowledgeChunk_TOTAL": [{"meta": null}],'
         b' "KnowledgeChunk_FILESYSTEM": [{"meta": {"count": 0}}]}}}', "meta null"),
        (b'{"data": {"Aggregate": {"KnowledgeChunk_TOTAL": [{"meta": {"count": 5}}],'
         b' "KnowledgeChunk_FILESYSTEM": [{"meta": {"count": [0]}}]}}}', "count 非标量"),
        (b'{"data": null}', "data null"),
    ],
)
def test_twv21_broken_aggregate_shape_fails_closed(
    tmp_path, fake_wv128, monkeypatch, raw, shape_label
):
    """T-WV-21:损坏的 Aggregate 形状(alias 缺失/groups 非列表/meta 缺失/
    meta null/count 缺失/count 非标量/data null)→ probe_failed fail-closed,
    绝不解释为 0(R1 现码已 fail-closed 的通道,钉住不回归)。"""
    _psql_shim(tmp_path, monkeypatch, f"iso_db\n{_PG_SID}\n0")
    wv = fake_wv128(aggregate_raw=raw)
    m = _write_manifest(tmp_path)
    verdict, code = evaluate(str(m), verify_upload_isolation=True,
                             isolation=_full_isolation_v2(tmp_path, wv.port))
    assert code == 2, f"{shape_label} 必须 fail-closed"
    chk = _filesystem_objects_check(verdict)
    assert (
        chk["status"] == "fail"
        and chk["class"] == "isolation_filesystem_probe_failed"
    ), f"{shape_label} 必须 probe_failed,实测 {chk['class']}/{chk['status']}"


def test_twv22_legal_counts_keep_exact_semantics(tmp_path, fake_wv128, monkeypatch):
    """T-WV-22:合法计数语义不变 —— filesystem=0(合法 JSON 整数 0)→
    clean PASS;filesystem=3(合法正数)→ objects_present fail(污染如实
    报告);total=0 → BLOCKED(空集合上的 0 计数不构成隔离证据)。"""
    m = _write_manifest(tmp_path)
    # (a) 合法 0 → clean PASS
    _psql_shim(tmp_path, monkeypatch, f"iso_db\n{_PG_SID}\n0")
    wv0 = fake_wv128(total=5, filesystem=0)
    verdict, code = evaluate(str(m), verify_upload_isolation=True,
                             isolation=_full_isolation_v2(tmp_path, wv0.port))
    assert code == 0 and verdict["status"] == "pass"
    chk0 = _filesystem_objects_check(verdict)
    assert chk0["class"] == "isolation_filesystem_clean" and chk0["status"] == "pass"
    # (b) 合法正数 → objects_present fail(真实污染证据,如实报告)
    _psql_shim(tmp_path, monkeypatch, f"iso_db\n{_PG_SID}\n0")
    wv3 = fake_wv128(total=5, filesystem=3)
    verdict3, code3 = evaluate(str(m), verify_upload_isolation=True,
                               isolation=_full_isolation_v2(tmp_path, wv3.port))
    assert code3 == 2
    chk3 = _filesystem_objects_check(verdict3)
    assert chk3["class"] == "isolation_filesystem_objects_present"
    assert "3 个" in chk3["reason"]
    # (c) total=0 → BLOCKED(语义不动)
    wvt0 = fake_wv128(total=0, filesystem=0)
    verdictt, codet = evaluate(str(m), verify_upload_isolation=True,
                               isolation=_full_isolation_v2(tmp_path, wvt0.port))
    assert codet == 2
    chkt = _filesystem_objects_check(verdictt)
    assert chkt["status"] == "blocked" and "总对象 = 0" in chkt["reason"]
