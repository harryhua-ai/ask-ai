"""Issue #100 AC1/AC3:上传 → 同一权威 connector 枚举可见(单一权威回归)。

容器拓扑(跨容器共享卷)由 tests/deploy/test_shared_uploads_volume.py 静态
验证 + 生产部署授权后验收;本文件锁的是**写侧↔读侧单一权威**的代码契约:

- 上传端点落盘路径与写入 ``ds.config["root_path"]`` 的读路径同源
  (``UPLOADS_CORPUS_ROOT`` 常量派生,零字面漂移);
- 用该 root_path 实例化的 FilesystemConnector 必须枚举到刚上传的文件
  (AC3:可读源 ⇒ 枚举观察到上传语料,正常 sync 可摄取)。
"""

import uuid
from pathlib import Path

from backend.api.admin.data_sources import UPLOADS_CORPUS_ROOT, _upload_root, _safe_upload_path
from backend.connectors.filesystem import FilesystemConnector
from backend.connectors.registry import SourceConfig


def test_upload_root_derives_from_single_constant():
    """写侧单一权威:_upload_root 由 UPLOADS_CORPUS_ROOT 派生(无字面漂移)。"""
    sid = f"probe-{uuid.uuid4().hex[:8]}"
    assert _upload_root(sid) == UPLOADS_CORPUS_ROOT / sid
    # 单一权威子树 = data/uploads(共享卷容器路径 /app/data/uploads 的仓库
    # 相对形态);镜像 CWD=/app,两形态严格对应
    assert UPLOADS_CORPUS_ROOT.as_posix().startswith("data/uploads")


def test_recorded_root_path_enumerates_uploaded_corpus(tmp_path, monkeypatch):
    """AC3:按上传时记录的 root_path 枚举,必须看到刚上传的文件。

    写侧(上传端点落盘)与读侧(connector 以 config.root_path 枚举)以
    同一相对权威路径对齐 —— 本测试把进程 CWD 切到 tmp_path 模拟「同一
    挂载根下的两方视角」,等价共享卷语义。
    """
    monkeypatch.chdir(tmp_path)
    sid = f"probe-{uuid.uuid4().hex[:8]}"
    base: Path = _upload_root(sid)
    target = _safe_upload_path(base, "docs/知识库/inside.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# uploaded knowledge\n", encoding="utf-8")

    recorded_root_path = f"data/uploads/data-sources/{sid}"  # 上传端点写入 config 的同一字符串形态
    connector = FilesystemConnector(
        SourceConfig(
            id=sid,
            type="filesystem",
            product="probe",
            enabled=True,
            sync_interval="24h",
            branches=[],
            channel_visibility=("widget", "api"),
            config={"root_path": recorded_root_path, "file_types": [".md"]},
        )
    )
    docs = list(connector.fetch_all())
    assert [d.source_id for d in docs] == [f"{sid}/main/docs/知识库/inside.md"], (
        "按记录 root_path 枚举必须观察到上传语料(AC3)"
    )
