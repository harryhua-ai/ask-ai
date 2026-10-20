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
import json
import os
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

_FAKE_PW = "R4GRN-FAKEPW-WVANCHOR"
_DSN = f"postgresql://iso_user:{_FAKE_PW}@dbhost:6543/iso_db"
_PG_SID = "7200000000000000002"
# 测试自造 v2 锚值(非秘密;绝不代表真实生产标识 —— 生产锚采集属 A-owned)
_CP_HOST = "fake-node-a1.invalid"
_CP_IMG = "sha256:" + "ab" * 32
_CP_VOL = "fake-t4_weaviate_data"
_CP_MAN = "cd" * 32

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
    shim.write_text(
        "#!/bin/bash\n"
        f'printf \'%s\\n\' "$@" > "{argv_file}"\n'
        f'printf \'%s\\n\' "{output}"\n',
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
        {k: v for k, v in good.items() if k != "weaviate_volume_manifest_sha256"},
        {**good, "evil": "x"},                                # 词表外
        {**good, "weaviate_collection_id": "01234567-89ab-cdef-0123-456789abcdef"},  # v1/v2 混装
        {**good, "version": 3},
        {**good, "version": 1},  # version=1 却带 v2 字段 → 词表外拒绝
    ]
    for payload in bad_payloads:
        p = tmp_path / "bad-anchor.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        anchor, err = rp._load_trust_anchor(str(p))
        assert anchor is None and err, f"应拒绝: {sorted(payload)}"


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
        self.ssh_argv = self.logs / "ssh_argv.log"
        self.docker_argv = self.logs / "docker_argv.log"
        self.eval_argv = self.logs / "eval_argv.log"
        self._write_shims()

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
            '        printf \'{"version":"1.0.0","compatibility_contract":true}\' > "$dest" ;;\n'
            '      *release_preflight.py) cp "$TSL_EVALUATOR_SRC" "$dest" ;;\n'
            '      *compatibility.json)\n'
            '        printf \'{"version":1,"config":[],"host":[],"topology":[],'
            '"dependencies":[],"rollback":{"previous_compatible":true}}\' > "$dest" ;;\n'
            "      *) exit 1 ;;\n"
            "    esac ;;\n"
            "  inspect)\n"
            '    fmt="${args[@]:2}"\n'
            '    case "$fmt" in\n'
            "      *.Image*) echo \"$TSL_CP_IMAGE\" ;;\n"
            "      *Mounts*) echo \"$TSL_CP_VOLS\" ;;\n"
            "      *Config.Env*) printf '%s\\n' \"$TSL_CP_ENV\" | while IFS= read -r line; do echo \"$line\"; done ;;\n"
            '      *) echo "fake docker inspect: unknown fmt" >&2; exit 1 ;;\n'
            "    esac ;;\n"
            "  exec)\n"
            '    printf \'%s\\n\' "$*" >> "$TSL_DOCKER_ARGV_LOG"\n'
            '    echo "$TSL_CP_MAN  -" ;;\n'
            "  compose)\n"
            '    if [ "${TSL_PS_EMPTY:-}" = "1" ]; then exit 0; fi\n'
            '    sub=""\n'
            '    for i in "${!args[@]}"; do\n'
            '      case "${args[$i]}" in ps|exec) sub="${args[$i]}"; break;; esac\n'
            "    done\n"
            '    if [ "$sub" = "ps" ]; then echo fake-weaviate-cid; exit 0; fi\n'
            '    exec_idx=-1; svc_idx=-1\n'
            '    for i in "${!args[@]}"; do\n'
            '      if [ "${args[$i]}" = "exec" ]; then exec_idx=$i; fi\n'
            '      if [ "$exec_idx" -ge 0 ] && [ "${args[$i]}" = "backend" ]; then svc_idx=$i; break; fi\n'
            "    done\n"
            '    if [ "$svc_idx" -lt 0 ]; then echo "fake compose: no backend exec" >&2; exit 1; fi\n'
            '    cmd=("${args[@]:$((svc_idx + 1))}")\n'
            '    case "${cmd[0]}" in\n'
            "      sh)\n"
            '        # sh -c 两种:cat > /tmp/xxx(stdin 写入容器根)/sha256sum(容器内\n'
            '        # 工件哈希 —— 对容器根内真实文件求值;TSL_TAMPER=1 注入不匹配)\n'
            '        case "${cmd[2]}" in\n'
            '          "cat > "*)\n'
            '            target="${cmd[2]#cat > }"\n'
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
            '        printf \'%s\\n\' "${cmd[*]}" >> "$TSL_EVAL_ARGV_LOG"\n'
            '        exit "${TSL_EVAL_RC:-0}"\n'
            "        ;;\n"
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
        for shim in ("flock", "docker", "ssh"):
            (self.bin / shim).chmod(0o755)

    def step_env(self, *, anchor_json: str = _ANCHOR_V2_JSON, **overrides) -> dict:
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
            "TSL_CP_MAN": _CP_MAN,
            "SSH_KEY": "R4GRN-FAKEKEY-NOT-A-REAL-KEY",
            "SSH_HOST": "tesla-t4.fake.invalid",
            "SSH_USER": "deployer",
            "SSH_KNOWN_HOSTS_B64": base64.b64encode(
                b"tesla-t4.fake.invalid ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFAKER4TST\n"
            ).decode(),
            "DEPLOY_TAG": "v1.0.0",
            "TRUST_ANCHOR_B64": base64.b64encode(anchor_json.encode()).decode(),
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
    """控制面全匹配 → 核验 PASS → 容器 preflight 真实执行 → 步骤成功。"""
    rc, out, err = cp_sandbox.run_step(cp_sandbox.step_env())
    assert rc == 0, f"应成功: {out}\n{err}"
    assert "控制面锚核验 PASS" in out
    assert "PREFLIGHT PASS:v1.0.0" in out
    eval_argv = cp_sandbox.eval_argv_text()
    assert "--verify-upload-isolation" in eval_argv
    docker_argv = cp_sandbox.docker_argv.read_text(encoding="utf-8")
    assert "inspect" in docker_argv and "exec" in docker_argv, "控制面只读 inspect/exec 真实发生"


def test_twv11_control_plane_digest_mismatch_aborts_before_preflight(cp_sandbox):
    """镜像 digest 不匹配 → 中止;容器内 evaluator 零执行、镜像零拉取。"""
    wrong = "sha256:" + "ff" * 32
    rc, out, err = cp_sandbox.run_step(
        cp_sandbox.step_env(TSL_CP_IMAGE=wrong)
    )
    assert rc != 0
    assert "控制面锚不匹配" in err and "镜像" in err
    assert cp_sandbox.eval_argv_text() == "", "evaluator 绝不执行"
    assert "PREFLIGHT PASS" not in out
    docker_argv = cp_sandbox.docker_argv.read_text(encoding="utf-8")
    assert " pull " not in f" {docker_argv} ", "中止发生在 docker pull 之前"


def test_twv12_control_plane_volume_hostname_manifest_mismatch_aborts(cp_sandbox):
    """数据卷挂载缺失 / CLUSTER_HOSTNAME 不匹配 / 清单哈希不匹配 → 全部中止。"""
    for label, overrides in [
        ("volume", dict(TSL_CP_VOLS="some_other_volume=/var/lib/weaviate ")),
        ("hostname", dict(TSL_CP_ENV="CLUSTER_HOSTNAME=other-node.invalid")),
        ("manifest", dict(TSL_CP_MAN="ee" * 32)),
    ]:
        rc, out, err = cp_sandbox.run_step(cp_sandbox.step_env(**overrides))
        assert rc != 0, label
        assert "控制面锚不匹配" in err, label
        assert cp_sandbox.eval_argv_text() == "", label


def test_twv13_control_plane_weaviate_not_running_aborts(cp_sandbox):
    """weaviate 容器未运行(compose ps 空)→ 身份无法核验 → 中止。"""
    rc, out, err = cp_sandbox.run_step(cp_sandbox.step_env(TSL_PS_EMPTY="1"))
    assert rc != 0
    assert "weaviate 容器未运行" in err
    assert cp_sandbox.eval_argv_text() == ""


def test_twv14_control_plane_v1_anchor_skips_inspect_legacy_path(cp_sandbox):
    """v1 锚(新版 Weaviate 单层锚)→ 控制面块跳过(零 inspect/exec of weaviate),
    走 R3 原有容器 preflight 路径(向后兼容,行为不变)。"""
    v1 = json.dumps({
        "version": 1,
        "pg_system_id": "7300000000000000003",
        "weaviate_collection_id": "01234567-89ab-cdef-0123-456789abcdef",
    })
    rc, out, err = cp_sandbox.run_step(cp_sandbox.step_env(anchor_json=v1))
    assert rc == 0, f"v1 路径应保持 R3 行为: {out}\n{err}"
    assert "控制面锚核验" not in out, "v1 锚无控制面块"
    assert "PREFLIGHT PASS:v1.0.0" in out
    docker_argv = cp_sandbox.docker_argv.read_text(encoding="utf-8")
    assert "inspect fake-weaviate-cid" not in docker_argv, \
        "v1 锚不做运行中 weaviate 容器的控制面核验(仅允许审计用镜像 inspect)"


def test_twv15_control_plane_invalid_v2_anchor_shape_aborts(cp_sandbox):
    """锚 v2 字段形状非法 → 控制面 fail-closed(容器 preflight 零执行)。"""
    bad = json.dumps({**json.loads(_ANCHOR_V2_JSON),
                      "weaviate_image_digest": "sha256:nothex"})
    rc, out, err = cp_sandbox.run_step(cp_sandbox.step_env(anchor_json=bad))
    assert rc != 0
    assert "形状非法" in err
    assert cp_sandbox.eval_argv_text() == ""


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
