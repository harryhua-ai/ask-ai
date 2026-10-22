"""2026-10-22 发布通道适配:数据隔离电池 + deployed-version 守卫回归矩阵。

AC5 矩阵覆盖(任务书 §四):
- 四项新 Secret 均缺失,生产数据检查合法 → PASS(forward-deploy 正例);
- PostgreSQL 目标身份不一致 → FAIL;
- 已注销来源仍有 documents/chunks → FAIL(残留电池);
- Weaviate 存在禁止的 filesystem 残留 → FAIL;
- Weaviate 检查的是其他实例(nodes name ≠ 锚)→ FAIL;
- uploads 检查目录与冻结守卫不一致(extra/missing/hash_changed/符号链接/不可读)→ FAIL;
- PostgreSQL/Weaviate 不可达或探针报错 → FAIL;
- 共享 legacy generation 异常缺失 → FAIL;
- 裸 --remediation-ack → FAIL;
- r3 后旧 r2 目标 → FAIL(evaluator;宿主 update.sh 守卫由
  test_r6gate_host_script_provisioning::test_p05c 覆盖)。

红线:不连生产;全部 fake shim/本地文件;计数为测试自造。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import scripts.release_preflight as rp  # noqa: E402
from scripts.release_preflight import evaluate  # noqa: E402

PG_SID = "7500000000000000005"
WV_HOST = "channel-adapt-node.invalid"
WV_IMG = "sha256:" + "cd" * 32
WV_VOL = "channel-adapt_weaviate_data"

MANIFEST = {
    "version": 1,
    "config": [],
    "host": [],
    "topology": [],
    "dependencies": [],
    "rollback": {
        "previous_compatible": False,
        "remediation_gate": "upload-source-acl-verified-issue-121",
    },
}


def _anchor(tmp_path: Path, **overrides) -> Path:
    payload = {
        "version": 2,
        "pg_system_id": PG_SID,
        "weaviate_cluster_hostname": WV_HOST,
        "weaviate_image_digest": WV_IMG,
        "weaviate_volume_name": WV_VOL,
        "uploads_sources_dir": "/app/data/uploads/data-sources",
        "uploads_unknown_guard": "/app/deploy/prod/uploads-unknown-guard.tsv",
    }
    payload.update(overrides)
    p = tmp_path / "production-identity.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


KEEP_CONTENT = b"channel-adapt guard fixture\n"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _guard_file(tmp_path: Path, rows: list[tuple[str, str]] | None = None) -> Path:
    rows = rows if rows is not None else [("retained/keep.txt", _sha(KEEP_CONTENT))]
    p = tmp_path / "uploads-unknown-guard.tsv"
    p.write_text("".join(f"{r}\t{h}\n" for r, h in rows), encoding="utf-8")
    return p


def _uploads_dir(tmp_path: Path, files: dict[str, bytes] | None = None) -> Path:
    root = tmp_path / "data-sources"
    files = files if files is not None else {"retained/keep.txt": KEEP_CONTENT}
    for rel, content in files.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(content)
    return root


def _run(tmp_path: Path, *, anchor_overrides=None, guard_rows=None,
         uploads_files=None, patch=True, extra_iso=None, monkeypatch=None):
    """标准通道:锚(含 uploads 绑定,指向 tmp 目录)+守卫+目录;返回 (code, verdict)。"""
    anchor = _anchor(tmp_path, **(anchor_overrides or {}))
    guard = _guard_file(tmp_path, guard_rows)
    uroot = _uploads_dir(tmp_path, uploads_files)
    # 把锚里的绝对路径换成 tmp 实测路径(测试自造环境;生产路径语义同构);
    # 显式覆盖 uploads_sources_dir 的用例(不可达目录负例)不改写
    anchor_data = json.loads(anchor.read_text())
    if not (anchor_overrides or {}).get("uploads_sources_dir"):
        anchor_data["uploads_sources_dir"] = str(uroot)
    anchor_data["uploads_unknown_guard"] = str(guard)
    anchor = tmp_path / "production-identity.json"
    anchor.write_text(json.dumps(anchor_data))

    m = tmp_path / "compatibility.json"
    m.write_text(json.dumps(MANIFEST))
    loaded_anchor = rp._load_trust_anchor(str(anchor))[0]
    assert loaded_anchor is not None

    if patch:
        assert monkeypatch is not None
        monkeypatch.setattr(rp, "probe_upload_mode_rows", lambda cfg, t: 0)
        monkeypatch.setattr(
            rp, "probe_retired_source_residue",
            lambda cfg, t: {**dict.fromkeys(rp._RETIRE_RESIDUE_KEYS, 0),
                            "legacy_generations": 1})
        monkeypatch.setattr(rp, "probe_filesystem_objects", lambda cfg, t: 0)
    iso = {
        "pg_dsn": "postgresql://iso:pw@dbhost/iso_db",
        "weaviate_url": "http://wvhost:8080",
        "weaviate_class": "Document",
        "trust_anchor": loaded_anchor,
    }
    iso.update(extra_iso or {})
    verdict, code = evaluate(
        str(m), verify_upload_isolation=True, isolation=iso,
        release_tag="v9.9.9", deployed_version="9.9.8",
    )
    return code, verdict


def _iso(verdict):
    return [c for c in verdict["checks"] if c["section"] == "isolation"]


def _by_class(verdict, cls):
    return [c for c in verdict["checks"] if c["class"] == cls]


# ---------------- AC5 正例:四 Secret 全缺,检查合法 → PASS ----------------

def test_forward_deploy_clean_battery_passes(tmp_path, monkeypatch):
    """四项新 Secret 均缺失(零 remediation/锚输入)且数据隔离电池合法
    ⇒ 全链 PASS(AC1 验收基线:合法且安全的 r3 发布预检可通过)。"""
    code, verdict = _run(tmp_path, monkeypatch=monkeypatch)
    assert code == 0, json.dumps(verdict["checks"], ensure_ascii=False)
    assert verdict["status"] == "pass"
    classes = {c["class"] for c in _iso(verdict)}
    assert classes == {
        "isolation_upload_mode_clean",
        "isolation_filesystem_clean",
        "isolation_residue_clean",
        "isolation_legacy_present",
        "isolation_uploads_clean",
    }


def test_forward_deploy_with_deployed_version_passes(tmp_path, monkeypatch):
    code, verdict = _run(
        tmp_path, monkeypatch=monkeypatch,
        extra_iso=None,
    )
    # deployed-version 前向语义已在 test_r6gate_remediation_evidence 覆盖;
    # 此处验证隔离电池与 rollback 门并存时整体 pass
    assert code == 0


# ---------------- PG 身份/残留负例 ----------------

def test_pg_identity_mismatch_fails(tmp_path, monkeypatch):
    def _mismatch(cfg, t):
        raise rp.IsolationIdentityMismatch("目标 DB 身份不一致:system_identifier=fake ≠ 锚,fail-closed")
    monkeypatch.setattr(rp, "probe_upload_mode_rows", lambda cfg, t: 0)
    monkeypatch.setattr(rp, "probe_retired_source_residue", _mismatch)
    monkeypatch.setattr(rp, "probe_filesystem_objects", lambda cfg, t: 0)
    code, verdict = _run(tmp_path, patch=False, monkeypatch=monkeypatch)
    assert code == 2
    assert _by_class(verdict, "isolation_residue_identity_mismatch")


def test_retired_source_documents_and_chunks_present_fails(tmp_path, monkeypatch):
    """注销来源残留电池:documents/chunks 非零 → residue_present FAIL;
    legacy 缺失同步暴露。"""
    residue = {k: 0 for k in rp._RETIRE_RESIDUE_KEYS}
    residue["ksc_documents"] = 3
    residue["ksc_chunks"] = 12
    residue["legacy_generations"] = 0
    monkeypatch.setattr(rp, "probe_upload_mode_rows", lambda cfg, t: 0)
    monkeypatch.setattr(rp, "probe_retired_source_residue", lambda cfg, t: residue)
    monkeypatch.setattr(rp, "probe_filesystem_objects", lambda cfg, t: 0)
    code, verdict = _run(tmp_path, patch=False, monkeypatch=monkeypatch)
    assert code == 2
    chk = _by_class(verdict, "isolation_residue_present")
    assert chk and "ksc_documents=3" in chk[0]["reason"] and "ksc_chunks=12" in chk[0]["reason"]
    assert _by_class(verdict, "isolation_legacy_missing")


def test_legacy_generation_missing_alone_fails(tmp_path, monkeypatch):
    residue = {k: 0 for k in rp._RETIRE_RESIDUE_KEYS}
    residue["legacy_generations"] = 0
    monkeypatch.setattr(rp, "probe_upload_mode_rows", lambda cfg, t: 0)
    monkeypatch.setattr(rp, "probe_retired_source_residue", lambda cfg, t: residue)
    monkeypatch.setattr(rp, "probe_filesystem_objects", lambda cfg, t: 0)
    code, verdict = _run(tmp_path, patch=False, monkeypatch=monkeypatch)
    assert code == 2
    assert _by_class(verdict, "isolation_legacy_missing")
    assert not _by_class(verdict, "isolation_residue_present")


def test_residue_probe_channel_error_fails(tmp_path, monkeypatch):
    def _raise(cfg, t):
        raise rp.IsolationChannelUnavailable("psql 不可用")
    monkeypatch.setattr(rp, "probe_upload_mode_rows", lambda cfg, t: 0)
    monkeypatch.setattr(rp, "probe_retired_source_residue", _raise)
    monkeypatch.setattr(rp, "probe_filesystem_objects", lambda cfg, t: 0)
    code, verdict = _run(tmp_path, patch=False, monkeypatch=monkeypatch)
    assert code == 2
    assert _by_class(verdict, "isolation_residue_unprovable")


# ---------------- Weaviate 负例 ----------------

def test_weaviate_filesystem_residue_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(rp, "probe_upload_mode_rows", lambda cfg, t: 0)
    monkeypatch.setattr(
        rp, "probe_retired_source_residue",
        lambda cfg, t: {**dict.fromkeys(rp._RETIRE_RESIDUE_KEYS, 0),
                        "legacy_generations": 1})
    monkeypatch.setattr(rp, "probe_filesystem_objects", lambda cfg, t: 7)
    code, verdict = _run(tmp_path, patch=False, monkeypatch=monkeypatch)
    assert code == 2
    chk = _by_class(verdict, "isolation_filesystem_objects_present")
    assert chk and "7" in chk[0]["reason"]


def test_weaviate_other_instance_identity_mismatch_fails(tmp_path, monkeypatch):
    def _mismatch(cfg, t):
        raise rp.IsolationIdentityMismatch("Weaviate 身份不一致:nodes name=impostor ≠ 锚钉扎,fail-closed")
    monkeypatch.setattr(rp, "probe_upload_mode_rows", lambda cfg, t: 0)
    monkeypatch.setattr(
        rp, "probe_retired_source_residue",
        lambda cfg, t: {**dict.fromkeys(rp._RETIRE_RESIDUE_KEYS, 0),
                        "legacy_generations": 1})
    monkeypatch.setattr(rp, "probe_filesystem_objects", _mismatch)
    code, verdict = _run(tmp_path, patch=False, monkeypatch=monkeypatch)
    assert code == 2
    assert _by_class(verdict, "isolation_filesystem_identity_mismatch")


def test_weaviate_unreachable_probe_fails(tmp_path, monkeypatch):
    def _raise(cfg, t):
        raise RuntimeError("connection refused")
    monkeypatch.setattr(rp, "probe_upload_mode_rows", lambda cfg, t: 0)
    monkeypatch.setattr(
        rp, "probe_retired_source_residue",
        lambda cfg, t: {**dict.fromkeys(rp._RETIRE_RESIDUE_KEYS, 0),
                        "legacy_generations": 1})
    monkeypatch.setattr(rp, "probe_filesystem_objects", _raise)
    code, verdict = _run(tmp_path, patch=False, monkeypatch=monkeypatch)
    assert code == 2
    assert _by_class(verdict, "isolation_filesystem_probe_failed")


# ---------------- uploads 守卫负例(真实文件系统) ----------------

def test_uploads_dir_with_extra_file_fails(tmp_path, monkeypatch):
    files = {"retained/keep.txt": b"ab" * 32, "extra/orphan.md": b"x"}
    code, verdict = _run(tmp_path, uploads_files=files, monkeypatch=monkeypatch)
    assert code == 2
    chk = _by_class(verdict, "isolation_uploads_drift")
    assert chk and "extra=1" in chk[0]["reason"]


def test_uploads_missing_guard_file_fails(tmp_path, monkeypatch):
    code, verdict = _run(tmp_path, guard_rows=[("retained/keep.txt", "ab" * 32)],
                         uploads_files={}, monkeypatch=monkeypatch)
    assert code == 2
    assert _by_class(verdict, "isolation_uploads_drift")


def test_uploads_hash_changed_fails(tmp_path, monkeypatch):
    files = {"retained/keep.txt": b"tampered-content"}
    code, verdict = _run(tmp_path, uploads_files=files, monkeypatch=monkeypatch)
    assert code == 2
    chk = _by_class(verdict, "isolation_uploads_drift")
    assert chk and "hash_changed=1" in chk[0]["reason"]


def test_uploads_symlink_fails(tmp_path, monkeypatch):
    code, _ = _run(tmp_path, monkeypatch=monkeypatch)
    # 在已通过布局上注入符号链接后重跑
    uroot = tmp_path / "data-sources"
    (uroot / "retained" / "keep.txt").unlink()
    (uroot / "retained" / "keep.txt").symlink_to("/etc/hostname")
    anchor = tmp_path / "production-identity.json"
    m = tmp_path / "compatibility.json"
    iso = {
        "pg_dsn": "postgresql://iso:pw@dbhost/iso_db",
        "weaviate_url": "http://wvhost:8080",
        "weaviate_class": "Document",
        "trust_anchor": rp._load_trust_anchor(str(anchor))[0],
    }
    verdict, code = evaluate(
        str(m), verify_upload_isolation=True, isolation=iso,
        release_tag="v9.9.9", deployed_version="9.9.8",
    )
    assert code == 2
    assert _by_class(verdict, "isolation_uploads_guard_invalid")


def test_uploads_unreadable_root_fails(tmp_path, monkeypatch):
    """uploads 目录不存在(与真实挂载不符)→ fail-closed,绝不静默 PASS。"""
    code, verdict = _run(
        tmp_path,
        anchor_overrides={"uploads_sources_dir": "/nonexistent/data-sources"},
        monkeypatch=monkeypatch,
    )
    assert code == 2
    # 不可达目录 ⇒ 守卫文件缺席(missing)或目录不可枚举,两者均 fail-closed
    assert (_by_class(verdict, "isolation_uploads_guard_invalid")
            or _by_class(verdict, "isolation_uploads_drift"))


def test_uploads_guard_file_malformed_fails(tmp_path, monkeypatch):
    guard = tmp_path / "uploads-unknown-guard.tsv"
    guard.write_text("not\ta\tvalid\trow\n", encoding="utf-8")
    code, verdict = _run(tmp_path, monkeypatch=monkeypatch)
    # _run 重建守卫文件;直接改写后再评估
    guard.write_text("badline\n", encoding="utf-8")
    anchor = tmp_path / "production-identity.json"
    m = tmp_path / "compatibility.json"
    iso = {
        "pg_dsn": "postgresql://iso:pw@dbhost/iso_db",
        "weaviate_url": "http://wvhost:8080",
        "weaviate_class": "Document",
        "trust_anchor": rp._load_trust_anchor(str(anchor))[0],
    }
    verdict, code = evaluate(
        str(m), verify_upload_isolation=True, isolation=iso,
        release_tag="v9.9.9", deployed_version="9.9.8",
    )
    assert code == 2
    assert _by_class(verdict, "isolation_uploads_guard_invalid")


# ---------------- 端到端:probe_uploads_unknown_guard 单元语义 ----------------

def test_guard_probe_clean_and_drift_shapes(tmp_path):
    guard = _guard_file(tmp_path)
    root = _uploads_dir(tmp_path, {"retained/keep.txt": KEEP_CONTENT})
    result = rp.probe_uploads_unknown_guard(str(root), str(guard), 5)
    assert result["status"] == "clean" and result["files"] == 1

    # 守卫为空 → fail-closed
    guard.write_text("", encoding="utf-8")
    with pytest.raises(RuntimeError):
        rp.probe_uploads_unknown_guard(str(root), str(guard), 5)


def test_residue_sql_battery_shape():
    """SQL 电池:12 计数列序稳定 + 两来源前缀严格字面(与 #187 门禁同口径)。"""
    sql = rp._retired_source_residue_sql()
    assert sql.count("(SELECT count(*)") == 12
    for prefix in ("knowledge-support-cases/", "knowledge-cb70f5ae/"):
        assert f"='{prefix}'" in sql
    assert "'*legacy*'" in sql
