"""Source Center 共享 Discovery Result Contract(S0;#16/#17 消费)。

为 Git 与 Website 建立同一个 machine-readable 推荐模型(不建两套):

    candidate(path 或 URL)
      → technical safety(FileAdmission.technical_safe / technical_reason)
      → knowledge role(FileAdmission.knowledge_role,复用 KnowledgeRole)
      → source policy(FileAdmission.policy_result,#16/#18 的准入策略层)
      → recommendation(include | exclude | review)
      + reason(人读固定文案,枚举映射,非自由文本生成)

复用纪律:逐条候选就是 ``backend.connectors.safety.FileAdmission``
(阶段1 冻结结构,新增字段才允许扩展);本模块只提供 **envelope、
聚合与文案**,不做任何 IO——producer(GitHub trees API / sitemap 枚举)
由 #16/#17 各自实现后调用 :func:`build_discovery_result`。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from backend.connectors.safety import (
    RECOMMENDED_EXCLUDE_ROLES,
    RECOMMENDED_INCLUDE_ROLES,
    FileAdmission,
    KnowledgeRole,
)


def _role_recommendation(role: KnowledgeRole) -> str:
    """角色 → 推荐(与 safety.recommendation_for 同一冻结映射)。"""
    if role in RECOMMENDED_INCLUDE_ROLES:
        return "include"
    if role in RECOMMENDED_EXCLUDE_ROLES:
        return "exclude"
    return "review"


# 机器 reason → 人读文案(冻结枚举;Stage⑯ 文案纪律,单测锁定)
REASON_TEXT_ZH: dict[str, str] = {
    "model_artifact_ext": "模型/二进制工件,不可进入文本知识管线",
    "hard_oversized": "超过硬尺寸上限,不可进入管线",
    "binary_content": "二进制内容,不可作为文本知识",
    "poor_decode": "文本解码失败,不可作为知识",
    "secret_file": "疑似密钥/凭证文件,技术安全边界禁止纳入",
    "secret_content": "内容检出私钥材料,技术安全边界禁止纳入",
}

ROLE_LABEL_ZH: dict[str, str] = {
    role.value: label
    for role, label in {
        KnowledgeRole.PRODUCT_DOC: "产品文档",
        KnowledgeRole.TECHNICAL_DOC: "技术文档",
        KnowledgeRole.API_REFERENCE: "API 参考",
        KnowledgeRole.SOURCE_CODE: "源代码",
        KnowledgeRole.CONFIGURATION: "配置",
        KnowledgeRole.EXAMPLE: "示例",
        KnowledgeRole.TROUBLESHOOTING: "故障排查",
        KnowledgeRole.TEST: "测试代码",
        KnowledgeRole.BUILD_DEPLOYMENT: "构建/部署",
        KnowledgeRole.GENERATED: "生成物",
        KnowledgeRole.VENDOR: "第三方依赖",
        KnowledgeRole.BINARY: "二进制资产",
        KnowledgeRole.SECRETS: "密钥/凭证",
    }.items()
}


def reason_text(admission: FileAdmission) -> str:
    """单候选的人读理由(推荐排除/待审时必可解释;include 说明角色)。"""
    if admission.technical_reason:
        base = REASON_TEXT_ZH.get(admission.technical_reason)
        if base:
            return base
    if admission.recommendation == "exclude":
        role_label = ROLE_LABEL_ZH.get(admission.knowledge_role, admission.knowledge_role)
        return f"知识价值低({role_label}),建议排除"
    if admission.recommendation == "review":
        role_label = ROLE_LABEL_ZH.get(admission.knowledge_role, admission.knowledge_role)
        return f"需要人工确认({role_label})"
    role_label = ROLE_LABEL_ZH.get(admission.knowledge_role, admission.knowledge_role)
    return f"属于{role_label},建议纳入"


# ---------------------------------------------------------------------------
# #22 Discovery Governance(决策三层 + 持久策略继承 + 证据化分类)
#
# 冻结词表(Discovery §9.2-§9.5 + Planner REV 1):
#   L1 DETERMINISTIC_SAFE  技术安全结论 / URL 排除清单 / 二进制资产——永远压过规则;
#   L2 HIGH_CONFIDENCE     角色词表 / 持久规则继承 / 族群一致证据——可直接进推荐桶;
#   L3 TRULY_AMBIGUOUS     唯一进入待人工确认的例外集(尺寸带/密钥模板/平票/证据冲突)。
# 决策来源印章(decision_origins)记录 path → 证据来源,不触碰 FileAdmission
# 冻结结构(connectors/** 禁触碰纪律);L1 印章由 producer 预置,规则继承永不越 L1。
# ---------------------------------------------------------------------------

ORIGIN_RULE = "rule"
ORIGIN_FAMILY = "family"
ORIGIN_FAMILY_CONFLICT = "family_conflict"

# 决策来源 → 人读固定文案(冻结枚举;仅当来源结论与最终推荐一致时呈现)
ORIGIN_REASON_ZH: dict[str, str] = {
    "rule:include": "已按持久策略纳入(管理员既定决策)",
    "rule:exclude": "已按持久策略排除(管理员既定决策)",
    "family:include": "同族路径已有一致判定,按族群证据纳入",
    "family:exclude": "同族路径已有一致判定,按族群证据排除",
    "family_conflict": "同族路径判定冲突,需人工确认",
}


def origin_reason_text(admission: FileAdmission, origin: str | None) -> str | None:
    """来源印章 → 人读文案;印章结论与最终推荐不一致(如 L1 压过规则)时不呈现。"""
    if not origin:
        return None
    base = ORIGIN_REASON_ZH.get(origin)
    if base is None:
        return None
    if origin == ORIGIN_FAMILY_CONFLICT:
        return base if admission.recommendation == "review" else None
    expected = origin.rsplit(":", 1)[1]
    return base if admission.recommendation == expected else None


@dataclass
class CandidateGroup:
    """候选分组(顶层目录 / URL 路径前缀),供确认 UI 主视图。"""

    key: str
    count: int
    total_size: int
    recommendation: str  # include | exclude | review(规则见 summarize_candidates)
    samples: list[str] = field(default_factory=list)
    # #22 治理增量(§9.5 wire 只增字段):
    admin_decision: str | None = None  # 规则继承的既有决策(include | exclude | None)
    scope_confirmed: bool | None = None  # include 组的逐成员有效范围机械确认(§11.3)
    member_excluded: int = 0  # 组内被排除少数派数(多数决组内如实呈现,不隐藏)


@dataclass
class DiscoveryResult:
    """Discovery 统一 envelope(#16/#17 preview 端点的共同返回形态)。"""

    kind: str  # github | web_crawl
    target: dict  # {owner, repo, branch} / {base_url, sitemap_url?}
    totals: dict  # {files, safe_files, unsafe_files, total_size}
    by_role: dict  # {role: {count, size, recommendation}}
    groups: list[CandidateGroup]
    candidates: list[FileAdmission]
    recommended_config: dict  # 编译产物 = 既有 config JSONB 词表(file_types/exclude_dirs/…)
    warnings: list[str]
    capability_notes: list[str]
    # #22 治理:决策来源印章(path → "rule:include" / "l1:exclude" / …);不触碰候选冻结结构
    decision_origins: dict = field(default_factory=dict)
    # 分组键(producer 注入;规则继承/族群证据需重建分组视图;不参与 wire 序列化)
    group_key: Callable[[str], str] | None = field(default=None, repr=False, compare=False)


def _role_view(items: list[FileAdmission]) -> dict[str, dict]:
    """by_role 视图(角色 → 计数/尺寸/推荐;summarize 与重建共用)。"""
    by_role: dict[str, dict] = {}
    for a in items:
        entry = by_role.setdefault(
            a.knowledge_role, {"count": 0, "size": 0, "recommendation": None}
        )
        entry["count"] += 1
        entry["size"] += int(a.size or 0)
    for role, entry in by_role.items():
        try:
            entry["recommendation"] = _role_recommendation(KnowledgeRole(role))
        except ValueError:
            entry["recommendation"] = "review"
    return by_role


def summarize_candidates(
    candidates: Iterable[FileAdmission],
    *,
    group_key: Callable[[str], str] | None = None,
    max_groups: int = 100,
    samples_per_group: int = 3,
) -> tuple[dict, list[CandidateGroup]]:
    """聚合成 by_role + 分组视图(纯函数;确定性排序,可单测)。

    分组推荐规则(#22 §9.3 冻结,替换 v1.0.0「混合组整组 review」):

        review_count>0 且 include+exclude=0   → REVIEW(整组真歧义)
        include>0 且 exclude>0 且 include≠exclude → 多数决(混合组不再整组
                                                review;少数派成员计数进
                                                member_excluded,其不进范围由
                                                编译语义机械保证——include 白名单
                                                不收少数派扩展名/exclude 组照收)
        include == exclude(平票)             → REVIEW(真歧义,不可猜)
        其余                                   → 唯一多数派(v1.0.0 同序)

    强安全项决策保持强:分组只为呈现与策略压缩,不得把逐项 L1/L2 结论
    整体抬进人工确认(#22 冻结 Product Contract)。
    """
    items = list(candidates)
    by_role = _role_view(items)

    groups: list[CandidateGroup] = []
    if group_key is not None:
        buckets: dict[str, list[FileAdmission]] = {}
        for a in items:
            buckets.setdefault(group_key(a.path), []).append(a)
        for key in sorted(buckets)[:max_groups]:
            members = buckets[key]
            counts = Counter(m.recommendation for m in members)
            inc, exc = counts.get("include", 0), counts.get("exclude", 0)
            if inc and exc:
                if inc > exc:
                    best = "include"
                elif exc > inc:
                    best = "exclude"
                else:
                    best = "review"  # 平票=真歧义(§9.3 冻结;字典序偏向已废除)
            else:
                best = max(counts, key=lambda r: (counts[r], r))
            samples = [m.path for m in sorted(members, key=lambda m: m.path)][:samples_per_group]
            groups.append(
                CandidateGroup(
                    key=key,
                    count=len(members),
                    total_size=sum(int(m.size or 0) for m in members),
                    recommendation=best,
                    samples=samples,
                    member_excluded=exc,
                )
            )
    return by_role, groups


def build_discovery_result(
    kind: str,
    target: dict,
    candidates: Iterable[FileAdmission],
    *,
    group_key: Callable[[str], str] | None = None,
    recommended_config: dict | None = None,
    warnings: Iterable[str] = (),
    capability_notes: Iterable[str] = (),
) -> DiscoveryResult:
    """从逐条 FileAdmission 构建统一 envelope(纯函数)。"""
    items = list(candidates)
    by_role, groups = summarize_candidates(items, group_key=group_key)
    return DiscoveryResult(
        kind=kind,
        target=target,
        totals={
            "files": len(items),
            "safe_files": sum(1 for a in items if a.technical_safe),
            "unsafe_files": sum(1 for a in items if not a.technical_safe),
            "total_size": sum(int(a.size or 0) for a in items),
        },
        by_role=by_role,
        groups=groups,
        candidates=items,
        recommended_config=recommended_config or {},
        warnings=list(warnings),
        capability_notes=list(capability_notes),
        group_key=group_key,
    )


# ---------------------------------------------------------------------------
# #22 持久发现策略(discovery_rules;治理记忆,不是第二套摄取权威)
# ---------------------------------------------------------------------------


def parse_discovery_rules(raw: object) -> list[dict]:
    """config JSONB ``discovery_rules`` → 规范规则列表(防御式;畸形条目跳过)。

    冻结形态(§9.4):: ``[{"pattern": str, "decision": "include"|"exclude",
    "kind"?: str, "origin"?: str, "decided_at"?: str, "note"?: str|null}]``。
    """
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        pattern = item.get("pattern")
        decision = item.get("decision")
        if not isinstance(pattern, str) or not pattern.strip():
            continue
        if decision not in ("include", "exclude"):
            continue
        out.append(
            {
                "pattern": pattern.strip(),
                "decision": decision,
                "kind": item.get("kind") if isinstance(item.get("kind"), str) else None,
                "origin": item.get("origin") if isinstance(item.get("origin"), str) else None,
                "decided_at": item.get("decided_at")
                if isinstance(item.get("decided_at"), str)
                else None,
                "note": item.get("note") if isinstance(item.get("note"), str) else None,
            }
        )
    return out


def _rule_matches(rule: dict, path: str, kind: str) -> bool:
    """规则匹配(§9.4 冻结):github=首段目录前缀(对齐 top_level_group);
    web=路径子串前缀(对齐 classify_url 匹配风格)。匹配大小写不敏感。"""
    pattern = str(rule.get("pattern", "")).strip().rstrip("/").lower()
    if not pattern:
        return False
    p = (path or "").lower()
    if kind == "github":
        top = p.split("/", 1)[0] if "/" in p else p
        return top == pattern
    return pattern in p


def rules_matching(result: DiscoveryResult, rules: list[dict]) -> list[dict]:
    """命中 ≥1 候选的规则子表(保持规则顺序;透明度与网站排除编译共用)。"""
    matched = []
    for idx, rule in enumerate(rules):
        if any(_rule_matches(rule, a.path, result.kind) for a in result.candidates):
            matched.append(rules[idx])
    return matched


def _rebuild_views(result: DiscoveryResult) -> None:
    """候选推荐被规则/族群证据改写后,重建 by_role + 分组视图并重derive
    admin_decision / member_excluded(单一重建通道,避免两处聚合语义)。"""
    if result.group_key is None:
        return
    result.by_role, result.groups = summarize_candidates(
        result.candidates, group_key=result.group_key
    )
    for group in result.groups:
        decisions = {
            result.decision_origins[m.path].split(":", 1)[1]
            for m in result.candidates
            if result.group_key(m.path) == group.key
            and result.decision_origins.get(m.path, "").startswith(f"{ORIGIN_RULE}:")
        }
        group.admin_decision = decisions.pop() if len(decisions) == 1 else None


def apply_discovery_rules(result: DiscoveryResult, rules: object) -> DiscoveryResult:
    """持久规则继承(§9.4;producer 级纯函数,Git/Website 共用)。

    - 规则按序先匹配先胜;命中成员的推荐改写为规则决策并盖 ``rule:*`` 印章;
    - **L1 永远压过任何规则**:技术不安全(producer 预置 ``l1:*`` 印章或
      ``technical_safe=False``)的成员只记印章不改推荐(D3 冻结:安全高于策略);
    - 命中的组经 :func:`_rebuild_views` 呈现 ``admin_decision``;命中规则数写入
      ``target["inherited_rules"]``(透明度)。
    """
    rule_list = rules if isinstance(rules, list) else parse_discovery_rules(rules)
    rule_list = [r for r in rule_list if isinstance(r, dict) and r.get("pattern")]
    origins = dict(result.decision_origins)
    matched: list[int] = []
    for idx, rule in enumerate(rule_list):
        hit = False
        for a in result.candidates:
            if not _rule_matches(rule, a.path, result.kind):
                continue
            hit = True
            existing = origins.get(a.path, "")
            if existing.startswith("l1:") or not a.technical_safe:
                continue  # L1 压过规则:只记来源不改结论
            origins[a.path] = f"{ORIGIN_RULE}:{rule['decision']}"
            a.recommendation = rule["decision"]
        if hit:
            matched.append(idx)
    result.decision_origins = origins
    result.target = {**result.target, "inherited_rules": len(matched)}
    _rebuild_views(result)
    return result


def member_in_scope(path: str, compiled_config: dict, kind: str) -> bool:
    """逐成员有效范围判定(§11.3 scope_confirmed 机械确认;纯函数)。

    github:扩展名 ∈ file_types ∧ 顶层目录段 ∉ exclude_dirs ∧ 不中
    exclude_patterns(正则);web:不中 URL 排除词表 ∪ 用户 exclude_patterns
    (子串)∧ 非二进制资产后缀。与既有连接器消费语义同视野——这是
    「显示建议纳入却静默不进范围」变为不可通过测试缺陷的判据。
    """
    cfg = compiled_config or {}
    if kind == "github":
        import re as _re

        from pathlib import PurePosixPath

        suffix = PurePosixPath(path).suffix.lower()
        file_types = {str(t).strip().lower() for t in cfg.get("file_types") or [] if str(t).strip()}
        if not suffix or suffix not in file_types:
            return False
        top = path.split("/", 1)[0] if "/" in path else "(根目录)"
        if top in {str(d).strip() for d in cfg.get("exclude_dirs") or []}:
            return False
        for pat in cfg.get("exclude_patterns") or []:
            try:
                if _re.search(str(pat), path):
                    return False
            except _re.error:
                continue
        return True
    if kind == "web_crawl":
        from urllib.parse import urlparse

        from backend.services.website_discovery import (
            BINARY_ASSET_SUFFIXES,
            URL_EXCLUDE_PATTERNS,
        )

        path_only = urlparse(path).path.rstrip("/")
        last_dot = path_only.rsplit(".", 1)
        ext = f".{last_dot[1].lower()}" if len(last_dot) == 2 and last_dot[1] else ""
        if ext in BINARY_ASSET_SUFFIXES:
            return False
        p = path.lower()
        patterns = [str(x) for x in cfg.get("exclude_patterns") or []]
        for pat in [*URL_EXCLUDE_PATTERNS, *patterns]:
            if str(pat).lower() in p:
                return False
        return True
    return False


def annotate_scope(result: DiscoveryResult) -> list[str]:
    """逐 include 组 scope_confirmed 机械确认(§11.3;返回追加告警文案)。

    对每个建议纳入组,按编译产物逐成员执行 :func:`member_in_scope`;
    任一 include 成员不在范围 → 组 scope_confirmed=False 且显式告警。
    """
    scope_warnings: list[str] = []
    if result.group_key is None:
        return scope_warnings
    for group in result.groups:
        if group.recommendation != "include":
            group.scope_confirmed = None
            continue
        members = [
            m
            for m in result.candidates
            if result.group_key(m.path) == group.key and m.recommendation == "include"
        ]
        out_of_scope = [
            m.path
            for m in members
            if not member_in_scope(m.path, result.recommended_config, result.kind)
        ]
        group.scope_confirmed = not out_of_scope
        if out_of_scope:
            scope_warnings.append(
                f"组「{group.key}」有 {len(out_of_scope)} 个建议纳入文件当前不在生效范围内"
                "(scope_confirmed=false;请核对文件类型白名单/排除清单)"
            )
    return scope_warnings
