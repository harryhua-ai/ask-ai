"""r3gate R2-1:preflight 隔离断言 DSN 凭据边界(秘密绝不进 argv)。

修复前 RED 实证(R1 代码 898ec64a,现行路径):以
``--isolation-pg-dsn 'postgresql://probe_user:R2REDSECRETPW@…'`` 启动
preflight,运行中 ``ps -o command= -p <pid>`` 输出含完整 DSN 与口令 ——
顶层 CLI 把含密 DSN 留在进程 argv(同机用户/进程列表可见)。

修复后(GREEN,本文件):
- ``--isolation-pg-dsn`` 已移除并显式拒绝(argparse error,exit 2);
- DSN 只经受控环境变量(``--isolation-pg-dsn-env <VAR_NAME>``,缺省读
  ``ISOLATION_PG_DSN``)或安全文件(``--isolation-pg-dsn-file``)进入;
- 缺失(env 未设/文件不可读)→ BLOCKED → 整体非零退出(fail-closed);
- 格式非法 → probe fail-closed fail;连接失败 → probe fail;
- DSN/口令绝不出现于:顶层 argv(ps 实测)、psql argv(仅 PGPASSWORD env)、
  stdout/stderr(JSON verdict 与错误信息)。

红线:本文件所有"口令"均为测试假口令(R2GRN-* / R2RED-*),真实测试库
凭据只经进程 env 进入,绝不落入任何 argv/日志/仓库文件。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import scripts.release_preflight as rp
from scripts.release_preflight import main

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EVALUATOR = _REPO_ROOT / "scripts" / "release_preflight.py"

# 测试假口令(非真实凭据;仅用于断言"绝不外泄")
_FAKE_PW = "R2GRN-FAKEPW-DO-NOT-USE"
_FAKE_DSN = f"postgresql://iso_user:{_FAKE_PW}@dbhost:6543/iso_db"


def _write_manifest(tmp_path: Path, *, slow_dependency: bool = False) -> Path:
    m = tmp_path / "compatibility.json"
    deps = []
    if slow_dependency:
        # 有界黑洞探针:保证被测进程在 ps 检查窗口内存活(≤ probe-timeout)
        deps = [
            {
                "name": "bounded_blackhole",
                "probe": "tcp_connect",
                "host": "10.255.255.1",
                "port": 9,
                "timeout_s": 3,
            }
        ]
    m.write_text(
        json.dumps(
            {
                "version": 1,
                "config": [],
                "host": [],
                "topology": [],
                "dependencies": deps,
                "rollback": {"previous_compatible": True},
            }
        ),
        encoding="utf-8",
    )
    return m


def _iso_checks(verdict: dict) -> list[dict]:
    return [c for c in verdict["checks"] if c["section"] == "isolation"]


@pytest.fixture
def _psql_shim(tmp_path, monkeypatch):
    """受控 psql 替身:记录自身 argv 与收到的 PGPASSWORD,输出计数 0。

    让"正常 env 注入完成只读检查"走**真实子进程执行路径**(argparse →
    DSN 解析 → _psql_argv_env → subprocess),同时在本机无 psql 二进制的
    环境下可重复执行。
    """
    argv_file = tmp_path / "shim_argv.txt"
    pw_file = tmp_path / "shim_pw.txt"
    shim = tmp_path / "psql"
    shim.write_text(
        "#!/bin/bash\n"
        f'printf \'%s\\n\' "$@" > "{argv_file}"\n'
        f'printf \'%s\' "${{PGPASSWORD-}}" > "{pw_file}"\n'
        'printf \'%s\\n\' "iso_db"\n'
        'echo "0"\n',
        encoding="utf-8",
    )
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")
    return {"argv_file": argv_file, "pw_file": pw_file}


# --------------------------------------------------------------------------- #
# 旧旗标显式拒绝(fail-closed)
# --------------------------------------------------------------------------- #


def test_removed_dsn_flag_rejected_fail_closed(tmp_path, capsys):
    """--isolation-pg-dsn 必须被显式拒绝:exit 2,错误信息不得回显 DSN 值。"""
    m = _write_manifest(tmp_path)
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "--manifest", str(m),
                "--verify-upload-isolation",
                "--isolation-pg-dsn", _FAKE_DSN,
            ]
        )
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "--isolation-pg-dsn-env" in err, "必须指引到 env/文件替代通道"
    assert _FAKE_PW not in err and _FAKE_DSN not in err, "错误信息不得回显秘密"


# --------------------------------------------------------------------------- #
# 缺失凭据 fail-closed / 正常注入路径
# --------------------------------------------------------------------------- #


def test_missing_credentials_blocks_nonzero(tmp_path, monkeypatch):
    """env 未设 + 无旗标 → BLOCKED,整体非零退出(绝不静默、绝不回退)。"""
    monkeypatch.delenv("ISOLATION_PG_DSN", raising=False)
    m = _write_manifest(tmp_path)
    verdict, code = rp.evaluate(str(m), verify_upload_isolation=True, isolation={"pg_dsn": None})
    assert code == 2
    assert _iso_checks(verdict)[0]["status"] == "blocked"


def test_default_env_var_injection_positive_with_real_subprocess(
    tmp_path, monkeypatch, _psql_shim, capsys
):
    """缺省 ISOLATION_PG_DSN 注入 → 真实子进程只读探针完成;秘密只在
    PGPASSWORD env,绝不在 psql argv / 顶层输出。"""
    monkeypatch.setenv("ISOLATION_PG_DSN", _FAKE_DSN)
    monkeypatch.setattr(rp, "probe_filesystem_objects", lambda cfg, timeout_s: 0)
    m = _write_manifest(tmp_path)
    code = main(
        [
            "--manifest", str(m),
            "--verify-upload-isolation",
            "--isolation-weaviate-url", "http://wvhost:8080",
            "--isolation-weaviate-class", "KnowledgeChunk",
        ]
    )
    assert code == 0
    out = capsys.readouterr()
    # 顶层 stdout/stderr(JSON verdict + 摘要)绝不含 DSN/口令
    assert _FAKE_PW not in out.out and _FAKE_PW not in out.err
    assert _FAKE_DSN not in out.out and _FAKE_DSN not in out.err
    verdict = json.loads(out.out)
    assert {c["status"] for c in _iso_checks(verdict)} == {"pass"}
    # psql 侧:口令只经 PGPASSWORD env,argv 只见 host/port/user/db/SQL
    shim_argv = _psql_shim["argv_file"].read_text(encoding="utf-8")
    assert _FAKE_PW not in shim_argv, "psql argv 不得含口令"
    assert "-c" in shim_argv and "SELECT count(*) FROM data_sources" in shim_argv
    assert _psql_shim["pw_file"].read_text(encoding="utf-8") == _FAKE_PW


def test_named_env_var_injection_positive(tmp_path, monkeypatch):
    """--isolation-pg-dsn-env <VAR_NAME>:argparse 只见变量名,值经 env 进入。"""
    monkeypatch.setenv("R2TEST_ISO_DSN", _FAKE_DSN)
    monkeypatch.setattr(rp, "probe_upload_mode_rows", lambda cfg, timeout_s: 0)
    monkeypatch.setattr(rp, "probe_filesystem_objects", lambda cfg, timeout_s: 0)
    m = _write_manifest(tmp_path)
    verdict, code = rp.evaluate(
        str(m),
        verify_upload_isolation=True,
        isolation={
            "pg_dsn": os.environ["R2TEST_ISO_DSN"],
            "weaviate_url": "http://wvhost:8080",
            "weaviate_class": "KnowledgeChunk",
        },
    )
    assert code == 0
    assert {c["status"] for c in _iso_checks(verdict)} == {"pass"}


def test_dsn_file_source_positive(tmp_path, monkeypatch, _psql_shim, capsys):
    """--isolation-pg-dsn-file:安全文件(0600)首行即 DSN。"""
    dsn_file = tmp_path / "iso_dsn.secret"
    dsn_file.write_text(f"{_FAKE_DSN}\n", encoding="utf-8")
    dsn_file.chmod(0o600)
    monkeypatch.delenv("ISOLATION_PG_DSN", raising=False)
    monkeypatch.setattr(rp, "probe_filesystem_objects", lambda cfg, timeout_s: 0)
    m = _write_manifest(tmp_path)
    code = main(
        [
            "--manifest", str(m),
            "--verify-upload-isolation",
            "--isolation-pg-dsn-file", str(dsn_file),
            "--isolation-weaviate-url", "http://wvhost:8080",
            "--isolation-weaviate-class", "KnowledgeChunk",
        ]
    )
    assert code == 0
    out = capsys.readouterr()
    assert _FAKE_PW not in out.out
    assert _psql_shim["pw_file"].read_text(encoding="utf-8") == _FAKE_PW


def test_dsn_file_unreadable_blocks_fail_closed(tmp_path, capsys, monkeypatch):
    """--isolation-pg-dsn-file 指向不可读路径 → BLOCKED,非零退出,不崩溃泄密。"""
    monkeypatch.delenv("ISOLATION_PG_DSN", raising=False)
    monkeypatch.setattr(rp, "probe_filesystem_objects", lambda cfg, timeout_s: 0)
    m = _write_manifest(tmp_path)
    code = main(
        [
            "--manifest", str(m),
            "--verify-upload-isolation",
            "--isolation-pg-dsn-file", str(tmp_path / "no-such.secret"),
            "--isolation-weaviate-url", "http://wvhost:8080",
            "--isolation-weaviate-class", "KnowledgeChunk",
        ]
    )
    assert code == 2
    out = capsys.readouterr()
    verdict = json.loads(out.out)
    assert _iso_checks(verdict)[0]["status"] == "blocked"


def test_malformed_dsn_fails_closed_and_never_echoed(tmp_path, monkeypatch, capsys):
    """DSN 格式非法 → probe fail-closed fail;非法值/口令绝不进输出。"""
    bad = "not-a-postgresql-dsn:R2GRN-BADPW"
    monkeypatch.setenv("ISOLATION_PG_DSN", bad)
    monkeypatch.setattr(rp, "probe_filesystem_objects", lambda cfg, timeout_s: 0)
    m = _write_manifest(tmp_path)
    code = main(
        [
            "--manifest", str(m),
            "--verify-upload-isolation",
            "--isolation-weaviate-url", "http://wvhost:8080",
            "--isolation-weaviate-class", "KnowledgeChunk",
        ]
    )
    assert code == 2
    out = capsys.readouterr()
    verdict = json.loads(out.out)
    classes = {c["class"] for c in _iso_checks(verdict)}
    assert "isolation_upload_mode_probe_failed" in classes
    joined = out.out + out.err
    assert "R2GRN-BADPW" not in joined and bad not in joined


# --------------------------------------------------------------------------- #
# 顶层进程 argv 边界(RED 的孪生回归:ps 实测运行中进程)
# --------------------------------------------------------------------------- #


def test_running_process_argv_never_contains_secret(tmp_path):
    """子进程启动 preflight(有界黑洞探针保证存活窗口),运行中 ps 读取其
    argv:秘密(env 注入)绝不出现;argv 只含 env 变量机制,不含任何 DSN。"""
    import socket

    m = _write_manifest(tmp_path, slow_dependency=True)
    out_file = tmp_path / "sub_out.json"
    err_file = tmp_path / "sub_err.txt"
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "ISOLATION_PG_DSN": _FAKE_DSN,
        "HOME": os.environ.get("HOME", str(tmp_path)),
    }
    out_handle = open(out_file, "w")  # noqa: SIM115 - 测试生命周期内持有
    err_handle = open(err_file, "w")
    proc = subprocess.Popen(  # noqa: S603 - 固定词表 argv,非外部输入拼接
        [
            sys.executable,
            str(_EVALUATOR),
            "--manifest", str(m),
            "--verify-upload-isolation",
            "--isolation-pg-dsn-env", "ISOLATION_PG_DSN",
            "--isolation-weaviate-url", "http://wvhost:1",
            "--isolation-weaviate-class", "KnowledgeChunk",
            "--probe-timeout", "3",
        ],
        stdout=out_handle,
        stderr=err_handle,
        env=env,
        cwd=str(_REPO_ROOT),
    )
    observed_running = False
    ps_snapshots: list[str] = []
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and proc.poll() is None:
        ps = subprocess.run(  # noqa: S603
            ["ps", "-o", "command=", "-p", str(proc.pid)],
            capture_output=True, text=True,
        )
        if ps.returncode == 0 and ps.stdout.strip():
            observed_running = True
            ps_snapshots.append(ps.stdout)
            assert _FAKE_PW not in ps.stdout, (
                f"RED 孪生回归失败:口令出现在运行中进程 argv:\n{ps.stdout}"
            )
        else:
            time.sleep(0.05)
    rc = proc.wait(timeout=10)
    out_handle.close()
    err_handle.close()
    assert observed_running, "未能观察到运行中进程(ps 检查窗口失效,测试自身失效)"
    assert any("--isolation-pg-dsn-env" in s for s in ps_snapshots), (
        "ps 快照应见 env 变量机制旗标(证明观察的是真实被测进程)"
    )
    out_text = out_file.read_text(encoding="utf-8")
    err_text = err_file.read_text(encoding="utf-8")
    assert _FAKE_PW not in out_text and _FAKE_PW not in err_text
    assert rc != 0, "无 psql/无 Weaviate 通道 → 必须 fail-closed 非零退出"
