"""Technical Safety Boundary 单元测试(阶段1 / G1)。

覆盖任务书 §15 最低行为 1-11:
- .hef / 未知扩展名二进制 / 伪装 .txt 的二进制被通用防线拦截;
- 超大文件在昂贵管线前被拒;
- 合法 Markdown/Python/C/YAML 不被误伤;
- vendor/test 技术安全但知识推荐排除;
- 管理员 file_types 不可绕过技术安全。
"""

from unittest.mock import patch

import pytest

from backend.connectors.registry import SourceConfig
from backend.connectors.safety import (
    ABSOLUTE_HARD_SIZE_MAX,
    DEFAULT_HARD_SIZE_CEILING,
    DEFAULT_REVIEW_SIZE_LIMIT,
    KnowledgeRole,
    TechnicalSafetyPolicy,
)

MB = 1024 * 1024


def _policy(**cfg) -> TechnicalSafetyPolicy:
    return TechnicalSafetyPolicy(cfg)


# ---------------------------------------------------------------- Layer 1


def test_hef_extension_is_technically_unsafe():
    v = _policy().check_path("showcases/models/yolov8s_pose.hef", 1024)
    assert not v.safe
    assert v.reason == "model_artifact_ext"


def test_unknown_extension_binary_content_rejected():
    # 无扩展名 ELF 式内容(实证:neoruntime 的 bin/nginx)——路径无法判别,
    # 内容嗅探必须拦下。
    blob = "\x7fELF\x00\x00" + "\x01\x02" * 256
    v = _policy().check_content(blob)
    assert not v.safe
    assert v.reason in {"binary_content", "poor_decode"}


def test_binary_renamed_to_txt_rejected():
    # 伪装扩展名:82MB 级 .hef 内容改名为 .txt(缩小版)——嗅探拦下
    blob = "HAILO\x00\x00" + "\xff\xfe\x00\x01" * 64
    v = _policy().check_content(blob)
    assert not v.safe


def test_hard_oversized_rejected_by_path_before_content():
    p = _policy(hard_size_ceiling=4 * MB)
    v = p.check_path("docs/huge.md", 5 * MB)
    assert not v.safe
    assert v.reason == "hard_oversized"


def test_absolute_ceiling_cannot_be_raised_by_config():
    # 管理员/配置不得把硬上限抬到绝对上限之上(84MB 级事故物任何配置下被拦)
    p = _policy(hard_size_ceiling=1 << 30)
    assert p.hard_size_ceiling == ABSOLUTE_HARD_SIZE_MAX
    assert p.check_path("x.bin", ABSOLUTE_HARD_SIZE_MAX + 1).safe is False


def test_normal_markdown_allowed():
    p = _policy()
    assert p.check_path("docs/guide.md", 20_000).safe
    assert p.check_content("# 标题\n\n中文段落 with english mix.\n").safe


def test_normal_python_allowed():
    code = "import os\n\n\ndef main():\n    print('你好 world <|endofprompt|> ok')\n"
    assert _policy().check_path("src/main.py", 4_000).safe
    assert _policy().check_content(code).safe


def test_normal_c_and_config_allowed():
    assert _policy().check_path("drv/main.c", 30_000).safe
    assert _policy().check_path("cfg/app.yaml", 2_000).safe
    assert _policy().check_content("server:\n  port: 8080\n").safe


def test_chinese_text_not_misjudged_as_binary():
    # 中文属于非 ASCII 可打印字符,控制字符/NUL/替换字符三类信号均为 0
    doc = "这是一段正常的中文文档。" * 200
    assert _policy().check_content(doc).safe


# ---------------------------------------------------------------- Layer 2


def test_vendor_is_technically_safe_but_recommended_exclude():
    a = _policy().admission("third_party/nlohmann/json.hpp", 900_000, content="#pragma once\n")
    assert a.technical_safe
    assert a.technical_reason is None
    assert a.knowledge_role == KnowledgeRole.VENDOR.value
    assert a.recommendation == "exclude"


def test_test_code_is_technically_safe_but_recommended_exclude():
    a = _policy().admission("web/src/utils/crypto.test.ts", 5_000, content="it('x', () => {})\n")
    assert a.technical_safe
    assert a.knowledge_role == KnowledgeRole.TEST.value
    assert a.recommendation == "exclude"


def test_generated_lock_recommended_exclude_and_docs_include():
    lock = _policy().admission("web/package-lock.json", 240_000, content="{}\n")
    assert lock.technical_safe and lock.recommendation == "exclude"
    doc = _policy().admission("docs/user-guide.md", 30_000, content="# guide\n")
    assert doc.recommendation == "include"


def test_binary_content_gets_binary_role_and_eligible_false():
    a = _policy().admission("weird/output.txt", 100_000, content="\x00\x01\x02" * 500)
    assert not a.technical_safe
    assert a.technical_reason == "binary_content"
    assert a.knowledge_role == KnowledgeRole.BINARY.value
    assert a.eligible is False


def test_review_size_threshold_flags_but_does_not_reject():
    p = _policy(review_size_limit=1 * MB, hard_size_ceiling=16 * MB)
    v = p.check_path("vendor/big.json.hpp", 2 * MB)
    assert v.safe  # 技术安全,只是超过建议阈
    assert DEFAULT_REVIEW_SIZE_LIMIT == 1 * MB and DEFAULT_HARD_SIZE_CEILING == 16 * MB


# ------------------------------------------------- connector 级(管理员不可绕过)


def _github_cfg(file_types, safety_cfg=None, clone_path="/tmp/nope"):
    cfg = {
        "id": "t-github",
        "type": "github",
        "product": "t",
        "enabled": True,
        "config": {
            "repo_url": "https://github.com/x/y.git",
            "clone_path": clone_path,
            "file_types": list(file_types),
            **(safety_cfg or {}),
        },
        "sync_interval": "24h",
        "channel_visibility": ("widget", "api"),
        "branches": ("main",),
    }
    return SourceConfig(**cfg)


def test_admin_file_types_cannot_bypass_technical_safety(tmp_path):
    """管理员显式把 .hef 加入 file_types:白名单放行,技术安全仍拒绝(T11)。"""
    from backend.connectors.github import GitHubConnector

    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "m.hef").write_bytes(b"\x00\x01HAILO" * 64)
    (tmp_path / "readme.md").write_text("# ok\n")

    conn = GitHubConnector(_github_cfg(file_types=[".hef", ".md"], clone_path=str(tmp_path)))
    from unittest.mock import MagicMock

    with patch(
        "backend.connectors.github.subprocess.run",
        return_value=MagicMock(returncode=0, stdout="", stderr=""),
    ):
        docs = list(conn.fetch_all())
    names = [d.metadata["path"] for d in docs]
    assert names == ["readme.md"]
    assert conn.safety_stats["excluded"] == 1
    assert conn.safety_stats["reasons"].get("model_artifact_ext") == 1


def test_giant_file_rejected_before_read(tmp_path):
    """硬尺寸上限在 read_text 之前生效:巨型文件连读取都不发生(T4/T12 前置)。"""
    from backend.connectors.github import GitHubConnector

    (tmp_path / "big.md").write_text("# x")  # 实际很小
    conn = GitHubConnector(
        _github_cfg(
            file_types=[".md"], safety_cfg={"hard_size_ceiling": 2}, clone_path=str(tmp_path)
        )
    )
    from unittest.mock import MagicMock

    with (
        patch(
            "backend.connectors.github.subprocess.run",
            return_value=MagicMock(returncode=0, stdout="", stderr=""),
        ),
        patch.object(
            __import__("pathlib").Path,
            "read_text",
            side_effect=AssertionError("must not read oversized file"),
        ),
    ):
        docs = list(conn.fetch_all())
    assert docs == []
    assert conn.safety_stats["reasons"].get("hard_oversized") == 1


def test_filesystem_hard_oversize_rejected_before_read(tmp_path):
    """filesystem:超硬上限文件在 read 之前被路径检查排除(内容嗅探在管线层)。"""
    from backend.connectors.filesystem import FilesystemConnector

    (tmp_path / "big.txt").write_bytes(b"x" * 300)
    (tmp_path / "ok.txt").write_text("hello\n")
    cfg = SourceConfig(
        id="t-fs",
        type="filesystem",
        product="t",
        enabled=True,
        config={"root_path": str(tmp_path), "file_types": [".txt"], "hard_size_ceiling": 128},
        sync_interval="24h",
    )
    conn = FilesystemConnector(cfg)
    docs = list(conn.fetch_all())
    assert [d.metadata["path"] for d in docs] == ["ok.txt"]
    assert conn.safety_stats["excluded"] == 1
    assert conn.safety_stats["reasons"].get("hard_oversized") == 1


@pytest.mark.parametrize("ext", [".onnx", ".npy", ".so", ".elf", ".wasm"])
def test_model_artifact_ext_class_covers_family(ext):
    assert _policy().check_path(f"m/model{ext}", 10).safe is False
