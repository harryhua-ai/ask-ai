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


@dataclass
class CandidateGroup:
    """候选分组(顶层目录 / URL 路径前缀),供确认 UI 主视图。"""

    key: str
    count: int
    total_size: int
    recommendation: str  # include | exclude | review(规则见 summarize_candidates)
    samples: list[str] = field(default_factory=list)


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


def summarize_candidates(
    candidates: Iterable[FileAdmission],
    *,
    group_key: Callable[[str], str] | None = None,
    max_groups: int = 100,
    samples_per_group: int = 3,
) -> tuple[dict, list[CandidateGroup]]:
    """聚合成 by_role + 分组视图(纯函数;确定性排序,可单测)。

    分组推荐规则(冻结,保守):组内**同时含 include 与 exclude** 候选
    → review(混合目录交给人工);否则取组内多数(全 include → include、
    全 exclude → exclude、include+review → include、exclude+review → exclude)。
    """
    items = list(candidates)
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

    groups: list[CandidateGroup] = []
    if group_key is not None:
        buckets: dict[str, list[FileAdmission]] = {}
        for a in items:
            buckets.setdefault(group_key(a.path), []).append(a)
        for key in sorted(buckets)[:max_groups]:
            members = buckets[key]
            counts = Counter(m.recommendation for m in members)
            if counts.get("include") and counts.get("exclude"):
                best = "review"
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
    )
