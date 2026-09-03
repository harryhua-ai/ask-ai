"""Shared Discovery Result Contract 测试(S0 / 验收 E)。

Git 路径候选与 Website URL 候选共用同一个 FileAdmission 模型与 envelope;
聚合器确定性;人读理由为冻结文案。
"""

from backend.connectors.safety import TechnicalSafetyPolicy
from backend.services.source_discovery import (
    REASON_TEXT_ZH,
    build_discovery_result,
    reason_text,
)

_policy = TechnicalSafetyPolicy()


def _admit(path: str, size: int, content: str | None = None):
    return _policy.admission(path, size, content)


# ------------------------------------------------------- 共用模型(验收 E)


def test_git_and_website_candidates_share_one_model():
    """路径候选与 URL 候选都落到 FileAdmission + 同一 envelope。"""
    git_candidate = _admit("docs/quickstart.md", 4_000, content="# quickstart\n")
    web_candidate = _admit("https://x.test/products/ne301/", 0)  # URL 候选:paths 字段承载规范 URL
    for c in (git_candidate, web_candidate):
        assert hasattr(c, "knowledge_role")
        assert c.recommendation in {"include", "exclude", "review"}
    result = build_discovery_result(
        kind="web_crawl",
        target={"base_url": "https://x.test"},
        candidates=[git_candidate, web_candidate],
    )
    assert result.kind == "web_crawl"
    assert result.totals["files"] == 2


# ------------------------------------------------------- 聚合器


def test_build_result_aggregates_by_role_and_totals():
    candidates = [
        _admit("docs/a.md", 100),
        _admit("docs/b.md", 300),
        _admit("src/main.py", 1_000),
        _admit("vendor/lib/x.hpp", 2_000),
        _admit("deploy/.env", 50),  # secret:unsafe
    ]
    result = build_discovery_result(
        kind="github",
        target={"owner": "o", "repo": "r", "branch": "main"},
        candidates=candidates,
        group_key=lambda p: p.split("/")[0],
    )
    assert result.totals == {
        "files": 5,
        "safe_files": 4,
        "unsafe_files": 1,
        "total_size": 3_450,
    }
    assert result.by_role["technical_doc"]["count"] == 2
    assert result.by_role["vendor"]["recommendation"] == "exclude"
    assert result.by_role["secrets"]["count"] == 1

    group_by_key = {g.key: g for g in result.groups}
    assert set(group_by_key) == {"docs", "src", "vendor", "deploy"}
    assert group_by_key["docs"].recommendation == "include"
    assert group_by_key["vendor"].recommendation == "exclude"
    assert group_by_key["docs"].samples == ["docs/a.md", "docs/b.md"]  # 确定性排序


def test_group_tie_breaks_conservative():
    """include/exclude 平票 → review(宁可让管理员多看一眼)。"""
    candidates = [
        _admit("mixed/a.md", 10),  # include
        _admit("mixed/b.test.ts", 10),  # exclude(test)
    ]
    result = build_discovery_result(
        kind="github",
        target={},
        candidates=candidates,
        group_key=lambda p: p.split("/")[0],
    )
    assert result.groups[0].recommendation == "review"


# ------------------------------------------------------- 人读理由


def test_reason_text_frozen_copy():
    secret = _admit("deploy/.env", 50)
    assert reason_text(secret) == REASON_TEXT_ZH["secret_file"]
    vendor = _admit("vendor/lib/x.hpp", 10, content="#pragma once\n")
    assert reason_text(vendor) == "知识价值低(第三方依赖),建议排除"
    doc = _admit("docs/a.md", 10)
    assert reason_text(doc) == "属于技术文档,建议纳入"


def test_reason_text_covers_all_machine_reasons():
    """机器 reason 枚举全部有人读文案(文案冻结的完整性)。"""
    from backend.connectors.safety import KnowledgeRole, TechnicalSafetyPolicy

    for reason in REASON_TEXT_ZH:
        assert REASON_TEXT_ZH[reason]
    # 二进制内容与解码失败走 admission 全链也有文案
    p = TechnicalSafetyPolicy()
    binary = p.admission("weird/out.txt", 100, content="\x00\x01" * 100)
    assert reason_text(binary) == REASON_TEXT_ZH["binary_content"]
    assert KnowledgeRole.SECRETS.value in [r.value for r in KnowledgeRole]


# ------------------------------------------------------- wire schemas


def test_wire_schemas_roundtrip_from_result():
    """DiscoveryResult → API wire 形态(候选带人读理由;分组保持)。"""
    from backend.api.admin.source_center_schemas import (
        DiscoveryResultOut,
        SourceLifecycleOut,
    )

    candidates = [_admit("docs/a.md", 100), _admit("deploy/.env", 50)]
    result = build_discovery_result(
        kind="github",
        target={},
        candidates=candidates,
        group_key=lambda p: p.split("/")[0],
    )
    out = DiscoveryResultOut.from_result(result)
    assert out.totals["files"] == 2
    assert all(c.reason for c in out.candidates)
    assert {c.recommendation for c in out.candidates} <= {"include", "exclude", "review"}
    assert out.groups[0].samples  # 采样可序列化

    lifecycle = SourceLifecycleOut(lifecycle_state="deleting")
    assert lifecycle.lifecycle_state == "deleting"
