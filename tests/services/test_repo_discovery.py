"""#16 Code Repository Discovery producer 测试(Simple Mode)。

冻结纪律(与 S0 website_discovery 同款):
- 全部组合逻辑离线可测(fetch 注入,零真实 GitHub 调用);
- 逐候选 = S0 FileAdmission(path+size 层;内容层秘密嗅探仍属 ingest,不前移);
- envelope/聚合/文案 = S0 build_discovery_result,零新合同;
- recommended_config = 既有 config 词表(file_types/exclude_dirs),PD-2:
  不创建第二套 ingestion authority;编译结果必须能被既有 connector 语义
  (file_types 白名单 + ExclusionPolicy + TechnicalSafetyPolicy)忠实执行。
"""

import pytest

from backend.connectors.exclusion import ExclusionPolicy
from backend.connectors.safety import TechnicalSafetyPolicy
from backend.services import repo_discovery as rd
from backend.services.repo_discovery import (
    ROOT_GROUP_KEY,
    RepoDiscoveryError,
    admission_from_tree_entry,
    compile_recommended_config,
    discover_repository,
    parse_repo_url,
    top_level_group,
)


def _blob(path: str, size: int = 100) -> dict:
    return {"path": path, "type": "blob", "size": size}


def _tree_payload(entries: list[dict], truncated: bool = False) -> dict:
    return {"tree": entries, "truncated": truncated}


def _fake_api(payload_by_url: dict[str, dict]):
    def api_get(url: str) -> dict:
        if url in payload_by_url:
            return payload_by_url[url]
        raise AssertionError(f"意外请求: {url}")

    return api_get


def _discover(entries: list[dict], *, branch: str | None = "main", truncated: bool = False):
    url = "https://github.com/o/r.git"
    payloads = {"/repos/o/r/git/trees/main?recursive=1": _tree_payload(entries, truncated)}
    if branch is None:
        payloads["/repos/o/r"] = {"default_branch": "main"}
    return discover_repository(url, branch, _fake_api(payloads))


# ------------------------------------------------------- repo_url 解析


def test_parse_repo_url_variants():
    assert parse_repo_url("https://github.com/camthink-ai/ne301.git") == ("camthink-ai", "ne301")
    assert parse_repo_url("https://github.com/camthink-ai/ne301") == ("camthink-ai", "ne301")
    assert parse_repo_url("https://github.com/camthink-ai/ne301/") == ("camthink-ai", "ne301")


def test_parse_repo_url_invalid_raises_discovery_error():
    with pytest.raises(RepoDiscoveryError):
        parse_repo_url("https://gitlab.com/o/r")


# ------------------------------------------------------- 逐候选准入


def test_admission_blob_only_and_path_layer():
    assert admission_from_tree_entry({"path": "x", "type": "tree"}) is None
    a = admission_from_tree_entry(_blob("docs/quickstart.md"))
    assert a is not None and a.technical_safe and a.recommendation == "include"


def test_admission_secret_is_technical_unsafe_even_if_admin_wants_it():
    """PD-1:发现层的秘密文件必须 technical_unsafe,绝不进 include 推荐。"""
    a = admission_from_tree_entry(_blob("deploy/id_rsa", 10))
    assert a is not None
    assert not a.technical_safe
    assert a.technical_reason == "secret_file"
    assert a.recommendation == "exclude"


def test_admission_model_artifact_and_oversized():
    so = admission_from_tree_entry(_blob("lib/core.so", 2_000_000))
    assert so is not None and not so.technical_safe
    big = admission_from_tree_entry(_blob("docs/huge.md", 64 * 1024 * 1024 + 1))
    assert big is not None and not big.technical_safe
    assert big.technical_reason == "hard_oversized"


def test_admission_image_is_review_not_include():
    """图片:文本管线不支持 → 角色 binary → review(待确认),默认不纳入。"""
    png = admission_from_tree_entry(_blob("assets/logo.png", 5_000))
    assert png is not None
    assert png.knowledge_role == "binary"
    assert png.recommendation == "review"


# ------------------------------------------------------- 分组键


def test_top_level_group_root_files_share_one_group():
    assert top_level_group("README.md") == ROOT_GROUP_KEY
    assert top_level_group("src/main.py") == "src"


# ------------------------------------------------------- 编译推荐 config


def test_compile_includes_only_safe_include_extensions():
    candidates = [
        admission_from_tree_entry(_blob("README.md")),
        admission_from_tree_entry(_blob("src/main.py")),
        admission_from_tree_entry(_blob("conf/app.yaml")),
        admission_from_tree_entry(_blob("assets/logo.png")),  # review
        admission_from_tree_entry(_blob("tests/test_main.py")),  # exclude(test)
        admission_from_tree_entry(_blob("deploy/id_rsa", 10)),  # unsafe
    ]
    cfg = compile_recommended_config(candidates)
    assert cfg["file_types"] == [".md", ".py", ".yaml"]
    assert "tests" in cfg["exclude_dirs"]
    # review/unsafe 类型绝不进白名单(三层准入:TECHNICALLY_SAFE ∧ ELIGIBLE ∧ POLICY)
    assert ".png" not in cfg["file_types"]
    assert ".key" not in cfg["file_types"]


def test_compile_exclude_dirs_from_exclude_groups_not_review():
    candidates = [
        admission_from_tree_entry(_blob("vendor/lib/x.py")),
        admission_from_tree_entry(_blob("docs/a.md")),
        admission_from_tree_entry(_blob("misc/unknown.bin")),  # review 组,不进 exclude_dirs
    ]
    cfg = compile_recommended_config(candidates)
    assert cfg["exclude_dirs"] == ["vendor"]
    assert "misc" not in cfg["exclude_dirs"]


def test_compile_deterministic_and_never_empty_keys():
    cfg = compile_recommended_config([admission_from_tree_entry(_blob("a/b.md", 10))])
    assert cfg["file_types"] == [".md"]
    assert cfg["exclude_dirs"] == []
    assert compile_recommended_config([]) == {"file_types": [], "exclude_dirs": []}


def test_compiled_config_executes_via_existing_connector_semantics():
    """编译产物必须被既有 connector 语义忠实执行(Simple Mode = 现有 policy 编译糖)。

    逐候选验证:compiled config 下 ``file_types 白名单 ∧ ExclusionPolicy ∧
    TechnicalSafetyPolicy.check_path`` 的最终结论 == 该候选的 include 推荐。
    """
    paths = [
        ("docs/guide.md", 1_000),
        ("src/main.py", 2_000),
        ("conf/app.yaml", 300),
        ("tests/test_main.py", 500),  # dir 级排除
        ("vendor/lib/core.c", 800),  # dir 级排除
        ("assets/logo.png", 4_000),  # 白名单外
        ("lib/core.so", 9_000),  # 技术不安全
    ]
    candidates = [admission_from_tree_entry(_blob(p, s)) for p, s in paths]
    cfg = compile_recommended_config(candidates)
    policy = ExclusionPolicy({**cfg, "max_file_size": None})
    safety = TechnicalSafetyPolicy()
    for path, size in paths:
        ext = "." + path.rsplit(".", 1)[-1]
        admitted = (
            ext in cfg["file_types"]
            and safety.check_path(path, size).safe
            and not policy.should_exclude(path, size)
        )
        expected = admission_from_tree_entry(_blob(path, size)).recommendation == "include"
        # tests/vendor 的 .py/.c 在白名单内,由 exclude_dirs 挡住;png/so 由白名单/安全层挡住
        assert admitted == expected, path


# ------------------------------------------------------- discover 编排


def test_discover_builds_s0_envelope_with_recommended_config():
    result = _discover(
        [
            _blob("README.md", 200),
            _blob("src/main.py", 1_000),
            _blob("src/util.py", 500),
            _blob("tests/test_main.py", 300),
            _blob("deploy/.env", 50),
        ]
    )
    assert result.kind == "github"
    # #22 有意更新:wire 增量字段 inherited_rules(无规则时为 0,§9.5)
    assert result.target == {"owner": "o", "repo": "r", "branch": "main", "inherited_rules": 0}
    assert result.totals["files"] == 5
    assert result.totals["unsafe_files"] == 1
    group_by_key = {g.key: g for g in result.groups}
    assert group_by_key["src"].recommendation == "include"
    assert group_by_key["tests"].recommendation == "exclude"
    assert result.recommended_config["file_types"] == [".md", ".py"]
    assert "tests" in result.recommended_config["exclude_dirs"]
    # 候选即 S0 wire 候选,人读理由由 source_discovery.reason_text 生成
    from backend.api.admin.source_center_schemas import DiscoveryResultOut

    out = DiscoveryResultOut.from_result(result)
    assert all(c.reason for c in out.candidates)


def test_discover_resolves_default_branch_when_absent():
    result = _discover([_blob("a.md")], branch=None)
    assert result.target["branch"] == "main"


def test_discover_truncated_tree_warns():
    result = _discover([_blob("a.md")], truncated=True)
    assert any("截断" in w for w in result.warnings)


def test_discover_zero_files_warns_not_silent():
    result = _discover([])
    assert any("未发现任何文件" in w for w in result.warnings)


def test_discover_capability_notes_are_honest():
    result = _discover([_blob("a.png"), _blob("b.md"), _blob("LICENSE")])
    notes = "\n".join(result.capability_notes)
    # 图片类:不虚假承诺能力(文本管线不支持 → 待确认且默认不纳入)
    assert "不支持" in notes
    # 无扩展名文件:扩展名白名单语义的诚实边界
    assert "无扩展名" in notes


def test_discover_api_failure_raises_discovery_error():
    def boom(url: str) -> dict:
        raise RepoDiscoveryError("远端不可达")

    with pytest.raises(RepoDiscoveryError):
        discover_repository("https://github.com/o/r", "main", boom)


def test_discover_caps_extreme_tree_with_warning():
    entries = [_blob(f"d{i}/f.md", 10) for i in range(rd.MAX_TREE_ENTRIES + 1)]
    result = _discover(entries)
    assert len(result.candidates) == rd.MAX_TREE_ENTRIES
    assert any("截断" in w or "过大" in w for w in result.warnings)
