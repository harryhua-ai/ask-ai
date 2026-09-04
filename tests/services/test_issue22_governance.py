"""#22 Source Center 统一发现治理验收(Execution Contract §19-§21)。

覆盖:
- 仓库聚合 R1-R8:§9.3 冻结聚合规则(多数决/平票/L3 唯一性)、components
  案件、编译含组决策覆盖、规则继承 + L1 压过规则、scope_confirmed 机械确认;
- 网站 W1-W7:证据化分类(族群一致/冲突/无票兜底),unknown path 本身永远
  不是 include/review 理由;规则继承不再重复询问;
- 策略 P1-P7:discovery_rules 解析(畸形跳过)、既有 config 向后兼容、
  编译单桥、ingest 权威不被绕过(本套件全部零 connector/sync 触碰)。

零网络、零 DB:全部纯函数 + 注入式 fetch。
"""

import pytest

from backend.connectors.safety import TechnicalSafetyPolicy
from backend.services import repo_discovery as rd
from backend.services import website_discovery as wd
from backend.services.source_discovery import (
    ORIGIN_REASON_ZH,
    annotate_scope,
    apply_discovery_rules,
    build_discovery_result,
    member_in_scope,
    origin_reason_text,
    parse_discovery_rules,
    summarize_candidates,
)

_policy = TechnicalSafetyPolicy()

# ============================================================
# 仓库聚合(R1-R4;§9.3 冻结规则)
# ============================================================


def _adm(path: str, size: int = 100, rec: str | None = None):
    a = _policy.admission(path, size)
    if rec is not None:
        a.recommendation = rec
    return a


def _key(p: str) -> str:
    return p.split("/", 1)[0] if "/" in p else "(根目录)"


def test_r1_pure_include_group_stays_include():
    _by, groups = summarize_candidates(
        [_adm("src/a.py"), _adm("src/b.py")], group_key=_key
    )
    assert groups[0].recommendation == "include"
    assert groups[0].member_excluded == 0


def test_r2_pure_exclude_group_stays_exclude():
    _by, groups = summarize_candidates(
        [_adm("vendor/a.js"), _adm("vendor/b.js")], group_key=_key
    )
    assert groups[0].recommendation == "exclude"


def test_r3_mixed_group_majority_not_wholesale_review():
    """强 include 证据不得被少数派整组抬进 review(§9.3 核心)。

    少数派成员取 producer L1 印章后的 exclude 结论(§9.2:二进制资产
    确定性排除),聚合层只看推荐结论。
    """
    members = [_adm(f"components/f{i}.ts") for i in range(13)]
    members.append(_adm("components/preview.png", rec="exclude"))  # L1 印章后
    _by, groups = summarize_candidates(members, group_key=_key)
    g = groups[0]
    assert g.recommendation == "include"
    assert g.member_excluded == 1
    # 少数派排除由编译语义机械保证:png 扩展名不进 file_types 白名单
    compiled = rd.compile_recommended_config(members)
    assert ".ts" in compiled["file_types"]
    assert ".png" not in compiled["file_types"]
    assert "components" not in compiled["exclude_dirs"]


def test_r3b_exclude_minority_majority_exclude():
    members = [
        _adm("docs/a.md"),
        _adm("docs/x.test.ts"),
        _adm("docs/y.test.ts"),
    ]
    _by, groups = summarize_candidates(members, group_key=_key)
    assert groups[0].recommendation == "exclude"
    assert groups[0].member_excluded == 2


def test_r4_genuine_conflict_tie_group_is_review():
    members = [_adm("misc/a.md"), _adm("misc/b.bin", rec="exclude")]
    _by, groups = summarize_candidates(members, group_key=_key)
    assert groups[0].recommendation == "review"


def test_r4b_all_review_group_is_review():
    _by, groups = summarize_candidates(
        [_adm("big/x.iso", 2_000_000), _adm("big/y.iso", 3_000_000)], group_key=_key
    )
    assert groups[0].recommendation == "review"


# ============================================================
# 组件验收案件(R5/R6;neomind-dashboard components 场景)
# ============================================================


def _components_tree():
    return {
        "tree": [
            {"path": "README.md", "type": "blob", "size": 200},
            *[
                {"path": f"components/comp{i}.tsx", "type": "blob", "size": 900}
                for i in range(13)
            ],
            {"path": "components/preview.png", "type": "blob", "size": 4096},
        ],
        "truncated": False,
    }


def _fake_api(payload):
    def api_get(path: str) -> dict:
        if path == "/repos/o/r":
            return {"default_branch": "main"}
        if path == "/repos/o/r/git/trees/main?recursive=1":
            return payload
        raise rd.RepoDiscoveryError("not found")

    return api_get


def test_r5_components_group_directly_recommended_include():
    """components 案件:逐文件源代码建议纳入的组,必须直呈「建议纳入」。

    组内 png 预览图在 producer 层按 §9.2 L1 确定性排除(不再是「待确认」
    常态组成员),组内多数决 = include。
    """
    result = rd.discover_repository(
        "https://github.com/o/r", None, _fake_api(_components_tree())
    )
    g = {x.key: x for x in result.groups}["components"]
    assert g.recommendation == "include"
    assert g.member_excluded == 1  # preview.png 少数派如实呈现
    assert g.scope_confirmed is True  # .tsx 在编译白名单内,范围机械确认


def test_r6_apply_strategy_components_enter_effective_scope():
    """采用推荐策略:components 纳入 scope(编译产物),少数派二进制不进。"""
    result = rd.discover_repository(
        "https://github.com/o/r", None, _fake_api(_components_tree())
    )
    compiled = result.recommended_config
    assert ".tsx" in compiled["file_types"]
    assert "components" not in compiled["exclude_dirs"]
    # 逐成员 scope 机械确认(§13:显示纳入 = 实际进范围,可测)
    assert all(
        member_in_scope(c.path, compiled, "github")
        for c in result.candidates
        if c.recommendation == "include"
    )


# ============================================================
# 组决策覆盖编译(§17 compile 第二参;向后兼容)
# ============================================================


def test_compile_with_group_decisions_override():
    """§17 第二参:组决议即该组裁决(含把平票 review 组决议 include/exclude);
    L1 安全边界不可被覆盖(unsafe 成员即使组决议 include 也不进白名单)。"""
    members = [
        _adm("src/a.py"),
        _adm("docs/x.md"),
        _adm("docs/y.test.ts"),  # docs 组:1 include + 1 exclude → 平票 review
        _adm("tests/t.py"),
        _adm("misc/note.md"),
        _adm("misc/blob.iso", rec="exclude"),
    ]
    base = rd.compile_recommended_config(members)
    # 组界门控:docs/misc 平票未决 → .md 零编译;仅 src 组 include 编译
    assert base["file_types"] == [".py"]
    assert "docs" not in base["exclude_dirs"] and "misc" not in base["exclude_dirs"]
    assert "tests" in base["exclude_dirs"]
    overridden = rd.compile_recommended_config(
        members, {"docs": "include", "misc": "include", "tests": "exclude"}
    )
    # 决议 include:docs/misc 的安全成员扩展名进白名单(blob.iso unsafe 仍排除)
    assert sorted(overridden["file_types"]) == [".md", ".py"]
    assert overridden["exclude_dirs"] == ["tests"]
    resolved_exclude = rd.compile_recommended_config(members, {"misc": "exclude"})
    assert "misc" in resolved_exclude["exclude_dirs"]
    assert ".md" not in resolved_exclude["file_types"]  # misc 决议排除后 .md 不编译
    # L1 安全边界:unsafe 成员即使组决议 include 也不进白名单
    assert ".iso" not in rd.compile_recommended_config(members, {"misc": "include"})["file_types"]


def test_compile_default_none_is_backward_compatible():
    members = [_adm("src/a.py"), _adm("tests/t.py")]
    assert rd.compile_recommended_config(members) == rd.compile_recommended_config(
        members, None
    )


# ============================================================
# 持久规则继承(R7/R8;§9.4)
# ============================================================


def _rules(*pairs):
    return [{"pattern": p, "decision": d, "kind": "github"} for p, d in pairs]


def test_r7_apply_strategy_does_not_consume_unresolved_review():
    """L3 未决组不被部分消费(Planner REV2 组界门控):review 组**零编译**——
    组内 include 成员的扩展名不进白名单、目录也不进排除;组级保持待确认。"""
    result = rd.discover_repository(
        "https://github.com/o/r",
        None,
        _fake_api(
            {
                "tree": [
                    {"path": "src/a.py", "type": "blob", "size": 100},
                    {"path": "docs/manual.md", "type": "blob", "size": 100},  # include
                    {"path": "docs/legacy.test.ts", "type": "blob", "size": 100},  # exclude
                ],
                "truncated": False,
            }
        ),
    )
    g = {x.key: x for x in result.groups}["docs"]
    assert g.recommendation == "review"  # 平票=真歧义,组级 L3 维持人工(PD-2)
    # REV2 组界门控:未决组的成员级 include 证据只用于呈现,不进编译产物
    assert result.recommended_config["file_types"] == [".py"]
    assert "docs" not in result.recommended_config["exclude_dirs"]  # 也不被静默吞掉


def test_rev2_majority_group_with_l3_member_visible_not_compiled():
    """多数决组内含 L3 成员:member_review 显式呈现;L3 成员自身扩展名不进编译。"""
    members = [
        _adm("src/a.ts"),
        _adm("src/b.ts"),
        _adm("src/c.ts"),
        _adm("src/d.bin", rec="review"),  # L3 成员(唯一扩展名,防碰撞判定)
    ]
    _by, groups = summarize_candidates(members, group_key=_key)
    g = groups[0]
    assert g.recommendation == "include"  # 多数决
    assert g.member_review == 1  # L3 歧义不被聚合隐藏
    compiled = rd.compile_recommended_config(members)
    assert ".ts" in compiled["file_types"]  # 安全多数成员正常编译
    assert ".bin" not in compiled["file_types"]  # L3 成员扩展名零编译


def test_rev2_admin_include_resolution_compiles_review_group():
    """管理员对 review 组决议 include(组决策)→ 该组范围进入编译产物。"""
    members = [
        _adm("src/a.py"),
        _adm("docs/manual.md"),
        _adm("docs/legacy.test.ts"),
    ]
    base = rd.compile_recommended_config(members)
    assert base["file_types"] == [".py"]  # docs 平票未决:零编译
    resolved = rd.compile_recommended_config(members, {"docs": "include"})
    assert sorted(resolved["file_types"]) == [".md", ".py"]  # 决议后 docs 进范围
    assert "docs" not in resolved["exclude_dirs"]


def test_rev2_admin_exclude_resolution_compiles_review_group_out():
    """管理员对 review 组决议 exclude → 目录进排除(connector 语义:目录排除胜过白名单)。"""
    members = [
        _adm("docs/manual.md"),
        _adm("docs/legacy.test.ts"),
        _adm("sandbox/x.md"),
        _adm("sandbox/y.test.ts"),
    ]
    resolved = rd.compile_recommended_config(
        members, {"docs": "exclude", "sandbox": "exclude"}
    )
    assert resolved["exclude_dirs"] == ["docs", "sandbox"]
    assert resolved["file_types"] == []  # 两组均决议排除:无任何 include 编译


def test_r8_persisted_rule_inherited_on_rediscovery():
    """持久决策 → 后续发现自动继承:组带 admin_decision,不再进待确认。"""
    tree = {
        "tree": [
            {"path": "media/report.md", "type": "blob", "size": 100},  # include
            {"path": "media/old.test.ts", "type": "blob", "size": 100},  # exclude
        ],
        "truncated": False,
    }
    fresh = rd.discover_repository("https://github.com/o/r", None, _fake_api(tree))
    g = {x.key: x for x in fresh.groups}["media"]
    assert g.recommendation == "review"  # 首次发现:media 组平票,L3
    assert g.admin_decision is None
    assert fresh.target["inherited_rules"] == 0

    inherited = rd.discover_repository(
        "https://github.com/o/r",
        None,
        _fake_api(tree),
        discovery_rules=_rules(("media", "include")),
    )
    g2 = {x.key: x for x in inherited.groups}["media"]
    assert g2.recommendation == "include"
    assert g2.admin_decision == "include"
    assert inherited.target["inherited_rules"] == 1
    assert ".md" in inherited.recommended_config["file_types"]
    # 印章文案(冻结枚举)
    member = next(a for a in inherited.candidates if a.path == "media/report.md")
    assert (
        origin_reason_text(member, inherited.decision_origins[member.path])
        == ORIGIN_REASON_ZH["rule:include"]
    )


def test_r8b_rule_exclude_compiles_into_exclude_dirs():
    tree = {
        "tree": [{"path": "sandbox/a.py", "type": "blob", "size": 100}],
        "truncated": False,
    }
    result = rd.discover_repository(
        "https://github.com/o/r",
        None,
        _fake_api(tree),
        discovery_rules=_rules(("sandbox", "exclude")),
    )
    assert result.recommended_config["exclude_dirs"] == ["sandbox"]


def test_l1_always_beats_rules():
    """技术不安全成员:规则说 include 仍排除(D3 冻结,红线)。"""
    tree = {
        "tree": [
            {"path": "keys/id_rsa", "type": "blob", "size": 50},
            {"path": "keys/README.md", "type": "blob", "size": 100},
        ],
        "truncated": False,
    }
    result = rd.discover_repository(
        "https://github.com/o/r",
        None,
        _fake_api(tree),
        discovery_rules=_rules(("keys", "include")),
    )
    secret = next(a for a in result.candidates if a.path.endswith("id_rsa"))
    assert secret.technical_safe is False
    assert secret.recommendation == "exclude"  # L1 胜(技术不安全 → L1 排除)
    assert result.decision_origins.get("keys/id_rsa") is None  # 规则不盖章不生效
    # 规则 include 的安全成员正常生效
    readme = next(a for a in result.candidates if a.path.endswith("README.md"))
    assert readme.recommendation == "include"
    assert ".md" in result.recommended_config["file_types"]


def test_rev2_rule_exclude_resolution_on_tie_group():
    """持久规则 exclude 决议平票组:组翻转 exclude、目录进编译排除、印章呈现。"""
    tree = {
        "tree": [
            {"path": "media/report.md", "type": "blob", "size": 100},
            {"path": "media/old.test.ts", "type": "blob", "size": 100},
        ],
        "truncated": False,
    }
    result = rd.discover_repository(
        "https://github.com/o/r",
        None,
        _fake_api(tree),
        discovery_rules=_rules(("media", "exclude")),
    )
    g = {x.key: x for x in result.groups}["media"]
    assert g.recommendation == "exclude"
    assert g.admin_decision == "exclude"
    assert "media" in result.recommended_config["exclude_dirs"]
    assert ".md" not in result.recommended_config["file_types"]


def test_rev2_scope_confirmed_gates_on_majority_group_l3_member():
    """多数决组含 L3 成员时,scope/聚合如实呈现:member_review>0。"""
    tree = {
        "tree": [
            {"path": "src/a.ts", "type": "blob", "size": 100},
            {"path": "src/b.ts", "type": "blob", "size": 100},
            {"path": "src/c.ts", "type": "blob", "size": 100},
        ],
        "truncated": False,
    }
    result = rd.discover_repository("https://github.com/o/r", None, _fake_api(tree))
    g = {x.key: x for x in result.groups}["src"]
    assert g.member_review == 0
    assert g.scope_confirmed is True


def test_scope_confirmed_flags_out_of_scope_include_members():
    """include 组含白名单外扩展名成员 → scope_confirmed=False + 显式告警。"""
    tree = {
        "tree": [
            {"path": "docs/a.md", "type": "blob", "size": 100},
            {"path": "docs/makefile", "type": "blob", "size": 100},  # 无扩展名
        ],
        "truncated": False,
    }
    result = rd.discover_repository("https://github.com/o/r", None, _fake_api(tree))
    g = {x.key: x for x in result.groups}["docs"]
    if g.recommendation == "include":
        assert g.scope_confirmed is False
        assert any("scope_confirmed=false" in w for w in result.warnings)


# ============================================================
# 解析与防御(P1/P2)
# ============================================================


def test_parse_rules_malformed_entries_skipped():
    rules = parse_discovery_rules(
        [
            {"pattern": "components", "decision": "include"},
            {"pattern": "", "decision": "include"},  # 空 pattern 跳过
            {"pattern": "x", "decision": "maybe"},  # 非法决策跳过
            "not-a-dict",  # 非对象跳过
            {"decision": "include"},  # 缺 pattern 跳过
        ]
    )
    assert rules == [{"pattern": "components", "decision": "include", "kind": None,
                      "origin": None, "decided_at": None, "note": None}]
    assert parse_discovery_rules(None) == []
    assert parse_discovery_rules("oops") == []


# ============================================================
# 网站(W1-W7;证据化分类,Planner REV 1 修正)
# ============================================================

BASE = "https://site.test"


def _site_fetch(mapping):
    def fetch(url: str):
        return mapping.get(url)

    return fetch


def _sitemap(urls):
    items = "".join(f"<url><loc>{BASE}{u}</loc></url>" for u in urls)
    return (
        '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + items
        + "</urlset>"
    )


def _preview(urls, rules=None):
    return wd.build_website_preview(
        BASE,
        _site_fetch({f"{BASE}/sitemap.xml": _sitemap(urls)}),
        discovery_rules=rules,
    )


def _groups_by_key(result):
    return {g.key: g for g in result.groups}


def test_w1_known_deterministic_exclude():
    result = _preview(["/login", "/cart/item"])
    for c in result.candidates:
        assert c.recommendation == "exclude"
        assert result.decision_origins[c.path] == "l1:exclude"


def test_w2_known_hint_include():
    result = _preview(["/docs/quickstart"])
    assert all(c.recommendation == "include" for c in result.candidates)


def test_w3_unknown_path_with_family_evidence_included():
    """/life/ 家族已有 hint include 成员(guide-a 命中「guide」)→ 未知页按族群一致证据纳入。"""
    result = _preview(["/life/guide-a", "/life/setup", "/life/deep-dive"])
    # guide-a 命中 hint(guide)→ include;同族无 hint 命中的页面继承族群证据
    assert all(c.recommendation == "include" for c in result.candidates)
    assert _groups_by_key(result)["life"].recommendation == "include"
    # canonical_url 规范化补尾斜杠
    assert result.decision_origins[f"{BASE}/life/deep-dive/"] == "family:include"
    assert result.decision_origins[f"{BASE}/life/setup/"] == "family:include"
    # hint 成员自身无印章(它靠的是优先类别证据)
    assert result.decision_origins.get(f"{BASE}/life/guide-a/") is None


def test_w4_unknown_path_with_strong_irrelevant_evidence_excluded():
    result = _preview(
        ["/archive/2020"],  # /archive 命中 L1 排除清单
    )
    assert result.candidates[0].recommendation == "exclude"


def test_w5_unknown_path_conflicting_evidence_review():
    """/mix/ 家族规则冲突(include 与 exclude 并存)→ 未判定成员维持 review。"""
    result = _preview(
        ["/mix/alpha", "/mix/beta", "/mix/gamma"],
        rules=[
            {"pattern": "/mix/alpha", "decision": "include"},
            {"pattern": "/mix/beta", "decision": "exclude"},
        ],
    )
    origins = result.decision_origins
    assert origins[f"{BASE}/mix/alpha/"] == "rule:include"
    assert origins[f"{BASE}/mix/beta/"] == "rule:exclude"
    # 族群票冲突 → gamma(无判定)维持 review,盖冲突印章
    gamma = next(c for c in result.candidates if c.path.rstrip("/").endswith("gamma"))
    assert gamma.recommendation == "review"
    assert origins[f"{BASE}/mix/gamma/"] == "family_conflict"
    # 组内规则决策不一致 → admin_decision 不呈现
    assert _groups_by_key(result)["mix"].admin_decision is None


def test_w6_unknown_path_alone_never_decides():
    """"无任何证据的未知路径 → 兜底 review(Planner REV 1:兜底保留)。"""
    result = _preview(["/some-random-page/"])
    c = result.candidates[0]
    assert c.recommendation == "review"
    assert result.decision_origins.get(c.path) is None


def test_w7_persisted_resolution_not_asked_again():
    """/blog/ 一次决定 → 后续发现继承(已按策略),不再进待确认。"""
    urls = ["/blog/post-1", "/blog/post-2"]
    first = _preview(urls)
    assert _groups_by_key(first)["blog"].recommendation == "review"
    assert _groups_by_key(first)["blog"].admin_decision is None

    second = _preview(urls, rules=[{"pattern": "/blog/", "decision": "include"}])
    g = _groups_by_key(second)["blog"]
    assert g.recommendation == "include"
    assert g.admin_decision == "include"
    assert second.target["inherited_rules"] == 1
    # 规则排除项并入编译清单(预览=同步视野)
    for c in second.candidates:
        assert c.recommendation == "include"


def test_website_rule_exclude_compiles_into_exclude_patterns():
    result = _preview(
        ["/forum/t1"],
        rules=[{"pattern": "/forum/", "decision": "exclude"}],
    )
    assert "/forum/" in result.recommended_config["exclude_patterns"]
    assert all(c.recommendation == "exclude" for c in result.candidates)
    assert _groups_by_key(result)["forum"].scope_confirmed is None  # 非 include 组


def test_website_scope_confirmed_true_for_clean_include():
    result = _preview(["/docs/a", "/docs/b"])
    g = _groups_by_key(result)["docs"]
    assert g.recommendation == "include"
    assert g.scope_confirmed is True


def test_no_rules_backward_compatible_no_origin_stamps():
    """旧源无 discovery_rules:零行为变化,除 wire 增量字段外与 v1.0.0 一致。"""
    result = _preview(["/docs/x", "/random-y"])
    assert result.target["inherited_rules"] == 0
    # hint include / 兜底 review 成员无治理印章(L1 除外)
    assert result.decision_origins.get(f"{BASE}/docs/x") is None
    assert result.decision_origins.get(f"{BASE}/random-y") is None
    assert result.candidates[0].recommendation == "include"
    assert result.candidates[1].recommendation == "review"


# ============================================================
# member_in_scope(§11.3 判据)
# ============================================================


def test_member_in_scope_github():
    cfg = {"file_types": [".py"], "exclude_dirs": ["tests"]}
    assert member_in_scope("src/a.py", cfg, "github") is True
    assert member_in_scope("src/a.ts", cfg, "github") is False
    assert member_in_scope("tests/a.py", cfg, "github") is False
    assert member_in_scope("Makefile", cfg, "github") is False


def test_member_in_scope_web():
    cfg = {"exclude_patterns": ["/private"]}
    assert member_in_scope("https://x.test/docs/a", cfg, "web_crawl") is True
    assert member_in_scope("https://x.test/private/a", cfg, "web_crawl") is False
    assert member_in_scope("https://x.test/login", cfg, "web_crawl") is False
    assert member_in_scope("https://x.test/a.png", cfg, "web_crawl") is False


# ============================================================
# 印章文案一致性(冻结枚举)
# ============================================================


def test_origin_reason_only_when_consistent():
    a = _adm("x/a.md")
    a.recommendation = "include"
    assert origin_reason_text(a, "rule:include") == ORIGIN_REASON_ZH["rule:include"]
    a.recommendation = "exclude"  # L1 压过规则时推荐与印章不一致 → 不呈现
    assert origin_reason_text(a, "rule:include") is None
