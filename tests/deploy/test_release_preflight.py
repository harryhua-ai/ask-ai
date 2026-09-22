"""Issue #46:release preflight evaluator 行为契约(fail-closed、有界、零 mutation)。

评估器消费发布树自带的 ``deploy/prod/compatibility.yml``,在任何生产
mutation(DB migration / application rollout)之前给出确定性判定:

- AC2:契约期缺 manifest ⇒ fail-closed;非法 manifest(未知 section/字段/
  枚举、越界 probe 超时、rollback 残缺)⇒ fail-closed;显式空 section = 无
  要求 ⇒ pass;manifest 只从显式路径加载(mutable main 不得重解释);
- AC3:config 只输出 name/shape/判定,**绝不输出值**(含失败路径);
  host capability / dependency probe 均为有界只读操作;
- AC4:rollback 显式 —— previous_compatible=false 的发布必须持有所声明的
  remediation gate 才能通过;历史(前契约)发布走有界兼容路径(--pre-contract-release
  ⇒ pass_with_deferred,未证明类显式列出)。

零 mutation:评估器全程只读(读文件/读目录/socket connect/有界子进程探针),
不写任何状态。退出码:0 = pass / pass_with_deferred;2 = fail-closed。
"""

from __future__ import annotations

import json
import socket
import threading
from pathlib import Path

import pytest

from scripts.release_preflight import evaluate, main

SECRET_PLANT = "super-secret-value-123"


def _write_manifest(tmp_path: Path, body):
    """body 为 dict ⇒ stdlib-JSON 序列化;str 视为原始 JSON 文本(负向用例)。"""
    p = tmp_path / "compatibility.json"
    text = json.dumps(body, ensure_ascii=False, indent=1) if isinstance(body, dict) else body
    p.write_text(text, encoding="utf-8")
    return p


def _run(argv: list[str], cwd=None):
    code = main(argv)
    return code


BASE_OK = {
    "version": 1,
    "config": [],
    "host": [],
    "topology": [],
    "dependencies": [],
    "rollback": {"previous_compatible": True},
}


def _cfg_manifest(config=None, host=None, topology=None, dependencies=None, rollback=None):
    """构造合法 manifest(显式给出要覆盖的 section)。"""
    m = {
        "version": 1, "config": [], "host": [], "topology": [],
        "dependencies": [], "rollback": {"previous_compatible": True},
    }
    if config is not None:
        m["config"] = config
    if host is not None:
        m["host"] = host
    if topology is not None:
        m["topology"] = topology
    if dependencies is not None:
        m["dependencies"] = dependencies
    if rollback is not None:
        m["rollback"] = rollback
    return m


# --------------------------------------------------------------------------- #
# AC2:manifest 所有权 / 时代语义 / 严格 schema
# --------------------------------------------------------------------------- #


def test_explicit_empty_sections_pass(tmp_path, capsys):
    m = _write_manifest(tmp_path, BASE_OK)
    assert _run(["--manifest", str(m)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "pass"


def test_contract_era_missing_manifest_fails_closed(tmp_path, capsys):
    code = _run(["--manifest", str(tmp_path / "absent.yml")])
    assert code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "fail"
    assert any(c["class"] == "manifest_missing" for c in out["checks"])


def test_pre_contract_release_missing_manifest_bounded_path(tmp_path, capsys):
    """AC4:历史(前契约)发布 = 有界兼容路径;未证明类必须显式列出。"""
    m = tmp_path / "absent.yml"
    assert _run(["--manifest", str(m), "--pre-contract-release"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "pass_with_deferred"
    assert out["era"] == "pre_contract"
    deferred_classes = {d["class"] for d in out["deferred"]}
    assert {"config", "host", "topology", "dependencies", "rollback"} <= deferred_classes


@pytest.mark.parametrize(
    "body,why",
    [
        ({"version": 2, "rollback": {"previous_compatible": True}}, "version 漂移"),
        ({"version": 1, "unknown_section": [], "rollback": {"previous_compatible": True}}, "未知 section"),
        ({"version": 1, "config": [], "host": [{"capability": "free_disk_ge_1tb"}],
          "topology": [], "dependencies": [],
          "rollback": {"previous_compatible": True}}, "未知 capability(防任意检查注入)"),
        ({"version": 1, "config": [], "host": [], "topology": [],
          "dependencies": [{"name": "db", "probe": "shell_nc", "host": "h", "port": 1, "timeout_s": 3}],
          "rollback": {"previous_compatible": True}}, "未知 probe(杜绝 shell-in-manifest)"),
        ({"version": 1, "config": [], "host": [], "topology": [],
          "dependencies": [{"name": "db", "probe": "tcp_connect", "host": "h", "port": 1, "timeout_s": 600}],
          "rollback": {"previous_compatible": True}}, "probe 超时越界(必须有界)"),
        ({"version": 1, "config": [], "host": [], "topology": [], "dependencies": []}, "rollback 段缺失"),
        ({"version": 1, "config": [], "host": [], "topology": [], "dependencies": [],
          "rollback": {"previous_compatible": False}}, "rollback 不兼容声明缺 remediation_gate"),
        ("{not json at all", "非 JSON 文本"),
    ],
)
def test_invalid_manifest_fails_closed(tmp_path, capsys, body, why):
    m = _write_manifest(tmp_path, body)
    assert _run(["--manifest", str(m)]) == 2, why
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "fail"
    assert any(c["class"] == "manifest_invalid" for c in out["checks"]), why


def test_manifest_loaded_from_explicit_path_not_cwd(tmp_path, capsys, monkeypatch):
    """AC2:评估只看显式 manifest;cwd/主干的同名文件不得重解释(冻结树所有权)。"""
    conflicting = tmp_path / "conflicting-root"
    conflicting.mkdir()
    (conflicting / "compatibility.yml").write_text(
        "version: 1\nconfig:\n  - name: MUST_FAIL\n    required: true\n    shape: non_empty_string\n    secret: false\n"
        "host: []\ntopology: []\ndependencies: []\nrollback:\n  previous_compatible: true\n",
        encoding="utf-8",
    )
    good = _write_manifest(tmp_path, BASE_OK)
    monkeypatch.chdir(conflicting)  # cwd 里有同名冲突 manifest
    assert _run(["--manifest", str(good)]) == 0, "cwd 的 manifest 不得参与判定"


# --------------------------------------------------------------------------- #
# AC3:config 存在性/形状(值绝不外泄)
# --------------------------------------------------------------------------- #


def test_config_missing_required_fails_without_value_leak(tmp_path, capsys, monkeypatch):
    m = _write_manifest(
        tmp_path,
        _cfg_manifest(config=[
            {"name": "REQUIRED_VAR", "required": True, "shape": "non_empty_string", "secret": True},
        ]),
    )
    monkeypatch.setenv("OTHER_VAR", SECRET_PLANT)  # 无关变量含密值
    assert _run(["--manifest", str(m), "--env", "REQUIRED_VAR=", "--env", f"OTHER_VAR={SECRET_PLANT}"]) == 2
    captured = capsys.readouterr()
    assert SECRET_PLANT not in captured.out and SECRET_PLANT not in captured.err, (
        "评估输出(含失败路径)绝不输出任何配置值"
    )
    out = json.loads(captured.out)
    assert any(c["class"] == "config_missing" and c["name"] == "REQUIRED_VAR" for c in out["checks"])


def test_config_wrong_shape_fails_and_hides_value(tmp_path, capsys):
    m = _write_manifest(
        tmp_path,
        _cfg_manifest(config=[
            {"name": "NUM_VAR", "required": True, "shape": "integer", "secret": False},
        ]),
    )
    assert _run(["--manifest", str(m), "--env", f"NUM_VAR={SECRET_PLANT}"]) == 2
    captured = capsys.readouterr()
    assert SECRET_PLANT not in captured.out and SECRET_PLANT not in captured.err, (
        "形状不匹配也只输出 name/期望形状/实际形状类,绝不回显值"
    )
    out = json.loads(captured.out)
    assert any(c["class"] == "config_invalid_shape" for c in out["checks"])


def test_config_present_passes(tmp_path, capsys):
    m = _write_manifest(
        tmp_path,
        _cfg_manifest(config=[
            {"name": "NUM_VAR", "required": True, "shape": "integer", "secret": True},
        ]),
    )
    assert _run(["--manifest", str(m), "--env", "NUM_VAR=42"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "pass"
    assert "42" not in capsys.readouterr().out


def test_config_optional_absent_passes(tmp_path, capsys):
    m = _write_manifest(
        tmp_path,
        _cfg_manifest(config=[
            {"name": "MAYBE_VAR", "required": False, "shape": "non_empty_string", "secret": False},
        ]),
    )
    assert _run(["--manifest", str(m)]) == 0


# --------------------------------------------------------------------------- #
# AC3:host capability(确定性、有界、只读)
# --------------------------------------------------------------------------- #


def test_host_capability_probe_bounded_and_deterministic(tmp_path, capsys, monkeypatch):
    m = _write_manifest(
        tmp_path, _cfg_manifest(host=[{"capability": "docker_compose_v2"}])
    )
    seen = {}

    def fake_probe(cmd, timeout_s):
        seen["cmd"] = cmd
        seen["timeout_s"] = timeout_s
        return 0, "v2.39.1"  # `docker compose version --short` 的真实形态

    monkeypatch.setattr("scripts.release_preflight._run_probe", fake_probe)
    assert _run(["--manifest", str(m), "--probe-timeout", "7"]) == 0
    assert seen["timeout_s"] <= 7, "capability 探针必须有界"
    assert seen["cmd"] == ["docker", "compose", "version", "--short"]


def test_host_capability_absent_fails_actionable(tmp_path, capsys, monkeypatch):
    m = _write_manifest(
        tmp_path, _cfg_manifest(host=[{"capability": "nvidia_gpu"}])
    )
    monkeypatch.setattr(
        "scripts.release_preflight._run_probe", lambda cmd, timeout_s: (1, "")
    )
    assert _run(["--manifest", str(m)]) == 2
    out = json.loads(capsys.readouterr().out)
    assert any(c["class"] == "host_capability_missing" and c["name"] == "nvidia_gpu" for c in out["checks"])


# --------------------------------------------------------------------------- #
# AC3:dependency probe(有界、非 mutation)
# --------------------------------------------------------------------------- #


def test_dependency_probe_reachable(tmp_path, capsys):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    threading.Thread(target=lambda: (srv.accept()[0].close() if srv else None), daemon=True).start()
    try:
        m = _write_manifest(
            tmp_path,
            _cfg_manifest(dependencies=[{
                "name": "probe-ok", "probe": "tcp_connect",
                "host": "127.0.0.1", "port": port, "timeout_s": 2,
            }]),
        )
        assert _run(["--manifest", str(m)]) == 0
    finally:
        srv.close()


def test_dependency_probe_unreachable_fails_actionable(tmp_path, capsys):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    dead_port = srv.getsockname()[1]
    srv.close()  # 端口已无人监听
    m = _write_manifest(
        tmp_path,
        _cfg_manifest(dependencies=[{
            "name": "probe-dead", "probe": "tcp_connect",
            "host": "127.0.0.1", "port": dead_port, "timeout_s": 2,
        }]),
    )
    assert _run(["--manifest", str(m)]) == 2
    out = json.loads(capsys.readouterr().out)
    assert any(c["class"] == "dependency_unreachable" and c["name"] == "probe-dead" for c in out["checks"])


def test_topology_declaration_deferred_to_existing_gate(tmp_path, capsys):
    """AC3:topology 声明式输出;same-tag 由部署原语既有 [6/6] 步强制(显式 deferred)。"""
    m = _write_manifest(
        tmp_path,
        _cfg_manifest(topology=[{"requirement": "same_tag_all_services"}]),
    )
    assert _run(["--manifest", str(m)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert any(d["class"] == "topology" for d in out["deferred"]), (
        "评估器不可证的同拓扑一致性必须显式 defer 到部署原语既有门,不得静默"
    )


# --------------------------------------------------------------------------- #
# AC4:rollback 兼容性门
# --------------------------------------------------------------------------- #


def test_rollback_compatible_passes_without_ack(tmp_path, capsys):
    m = _write_manifest(tmp_path, BASE_OK)
    assert _run(["--manifest", str(m)]) == 0


def test_rollback_incompatible_requires_declared_gate(tmp_path, capsys):
    m = _write_manifest(
        tmp_path,
        _cfg_manifest(rollback={
            "previous_compatible": False,
            "remediation_gate": "release_mig_002_reindex",
        }),
    )
    assert _run(["--manifest", str(m)]) == 2
    out = json.loads(capsys.readouterr().out)
    chk = [c for c in out["checks"] if c["class"] == "rollback_remediation_gate_required"]
    assert chk and chk[0]["reason"].find("release_mig_002_reindex") != -1, (
        "拒绝信息必须 actionable:指明所声明的 remediation gate 名称"
    )


def test_rollback_incompatible_with_matching_ack_passes(tmp_path, capsys):
    m = _write_manifest(
        tmp_path,
        _cfg_manifest(rollback={
            "previous_compatible": False,
            "remediation_gate": "release_mig_002_reindex",
        }),
    )
    assert _run(["--manifest", str(m), "--remediation-ack", "release_mig_002_reindex"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "pass"


def test_rollback_incompatible_wrong_ack_fails(tmp_path, capsys):
    m = _write_manifest(
        tmp_path,
        _cfg_manifest(rollback={
            "previous_compatible": False,
            "remediation_gate": "release_mig_002_reindex",
        }),
    )
    assert _run(["--manifest", str(m), "--remediation-ack", "some_other_gate"]) == 2


# --------------------------------------------------------------------------- #
# 零 mutation / 输出机器可读
# --------------------------------------------------------------------------- #


def test_verdict_is_machine_readable(tmp_path, capsys):
    m = _write_manifest(tmp_path, BASE_OK)
    assert _run(["--manifest", str(m), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert {"status", "era", "checks", "deferred"} <= set(payload)
    assert all({"section", "name", "class", "status"} <= set(c) for c in payload["checks"])
