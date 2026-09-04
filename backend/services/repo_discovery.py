"""Code Repository Discovery producer(#16 Simple Mode;S0 共享契约消费)。

PD 冻结(#16 Discovery):推荐生成走**保存前远程 tree scan**——GitHub
trees API 只读枚举,不 clone、不落盘、不触发同步;用户确认后由 Admin 把
``recommended_config`` 写入既有 config 词表(file_types/exclude_dirs),
真实抓取仍由既有 connector clone 流程执行,**零新 ingestion authority**(PD-2)。

与 S0 的关系(复用纪律,不建第二套):
- 逐候选 = ``connectors.safety.FileAdmission``;发现阶段只有 path+size,
  走 ``TechnicalSafetyPolicy.check_path`` 廉价层——**内容层**私钥嗅探
  (``check_content``)仍发生在 ingest,发现层不替代也不放宽;
- envelope/聚合/人读文案 = ``services.source_discovery.build_discovery_result``
  (同一合同,Git/Website 共用);
- ``api_get(path) -> dict`` 注入使全部组合逻辑离线可测(与
  website_discovery 的 fetch_fn 同纪律);默认实现附带 GITHUB_TOKEN。

诚实边界(冻结文案,capability_notes):
- 图片/音视频/无扩展名文件:当前文本 ingestion 不支持或无法被扩展名
  白名单匹配 → 待确认且默认不纳入,绝不因仓库存在而声明支持;
- 树截断/超量:显式告警,绝不把「没扫到」当「没内容」。
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from backend.connectors.safety import KnowledgeRole, TechnicalSafetyPolicy
from backend.services.source_discovery import (
    DiscoveryResult,
    annotate_scope,
    apply_discovery_rules,
    build_discovery_result,
    parse_discovery_rules,
    summarize_candidates,
)

if TYPE_CHECKING:
    from backend.connectors.safety import FileAdmission

GITHUB_API_BASE = "https://api.github.com"

# 顶层/根目录分组的根文件组键(根目录散文件不冒充目录名)
ROOT_GROUP_KEY = "(根目录)"

# 单次发现候选上限:超过即截断并显式告警(保护 Admin 面板与 API payload)
MAX_TREE_ENTRIES = 20000

# https://github.com/{owner}/{repo}[.git](与 connectors/github.py 同语义)
_REPO_URL_RE = re.compile(r"github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", re.IGNORECASE)


class RepoDiscoveryError(Exception):
    """发现失败(repo_url 非法 / 远端不可达 / 分支不存在 / 速率受限)。"""


ApiGet = Callable[[str], dict]


def parse_repo_url(repo_url: str) -> tuple[str, str]:
    """repo_url → (owner, repo);不合法抛 :class:`RepoDiscoveryError`。"""
    m = _REPO_URL_RE.search(repo_url or "")
    if not m:
        raise RepoDiscoveryError(
            f"无法解析 repo_url(期望 https://github.com/<owner>/<repo>): {repo_url}"
        )
    return m.group(1), m.group(2)


def top_level_group(path: str) -> str:
    """分组键:嵌套路径取首段;根目录散文件归入 :data:`ROOT_GROUP_KEY`。"""
    return path.split("/", 1)[0] if "/" in path else ROOT_GROUP_KEY


def admission_from_tree_entry(
    entry: dict, policy: TechnicalSafetyPolicy | None = None
) -> FileAdmission | None:
    """单个 trees API 条目 → FileAdmission(path+size 廉价层;非 blob 返回 None)。

    发现阶段**无内容**:``check_content`` 不在此发生(内容层秘密嗅探由
    ingest 执行);安全结论因此只覆盖 path/尺寸类证据,这一边界由
    capability_notes 向管理员如实说明。
    """
    if entry.get("type") != "blob":
        return None
    path = str(entry.get("path") or "")
    if not path:
        return None
    size = int(entry.get("size") or 0)
    return (policy or TechnicalSafetyPolicy()).admission(path, size)


def compile_recommended_config(
    candidates: list[FileAdmission],
    group_decisions: dict[str, str] | None = None,
) -> dict:
    """S0 候选 → 既有 config 词表(纯函数;PD-2 不建第二套 authority)。

    **组界门控(Planner REV2,阻断性修正)**:逐候选扩展名只有在其**所属组**
    已被安全判定为 include(或经 ``group_decisions`` 决议为 include)时才进
    ``file_types``;未决 review 组**零编译**——成员扩展名不进白名单、目录也
    不进排除(L3 保持完全未决,防止「review 组的部分内容经扩展名碰撞或
    成员级收集被静默摄入」)。exclude 组目录进 ``exclude_dirs``(connector
    语义:目录排除胜过白名单)。

    - ``file_types``:技术安全 ∧ include 推荐 ∧ **所属组已安全判定 include**
      的候选扩展名(排序去重);
    - ``exclude_dirs``:组推荐/组决议为 exclude 的目录(根文件组不进);
    - ``group_decisions``(§17):组键 → include|exclude 的管理员组决议,
      即该组的裁决(含把平票 review 组决议为 include/exclude 的路径);
      缺省 None 时按聚合推荐,行为向后兼容。
    """
    decisions = group_decisions or {}
    _, groups = summarize_candidates(candidates, group_key=top_level_group)
    group_rec = {g.key: g.recommendation for g in groups}
    for key, decision in decisions.items():
        if decision in ("include", "exclude"):
            group_rec[key] = decision

    def _group_decided(c: FileAdmission) -> bool:
        """组界门控 + 成员级推荐:组已安全判定 include 且该成员自身推荐 include。

        组门控解除 L3 歧义(未决组零编译);成员级推荐保护混合组内的
        排除少数派(组 include 不抬举成员级 exclude 结论,如二进制资产)。
        """
        return (
            group_rec.get(top_level_group(c.path)) == "include"
            and c.recommendation == "include"
        )

    file_types = sorted(
        {
            PurePosixPath(c.path).suffix.lower()
            for c in candidates
            if _group_decided(c) and c.technical_safe and PurePosixPath(c.path).suffix
        }
    )
    exclude_dirs = sorted(k for k, rec in group_rec.items() if rec == "exclude" and k != ROOT_GROUP_KEY)
    return {"file_types": file_types, "exclude_dirs": exclude_dirs}


def discover_repository(
    repo_url: str,
    branch: str | None,
    api_get: ApiGet,
    *,
    policy: TechnicalSafetyPolicy | None = None,
    discovery_rules: list[dict] | None = None,
) -> DiscoveryResult:
    """Repo URL(+可选分支)→ S0 :class:`DiscoveryResult`(纯编排;IO 全注入)。

    Args:
        repo_url: 仓库地址(https://github.com/<owner>/<repo>[.git])。
        branch: 分支;None 时经 ``/repos/{owner}/{repo}`` 解析默认分支。
        api_get: 注入的 GitHub API 读取函数,入参为 API path(如
            ``/repos/o/r/git/trees/main?recursive=1``),失败/不存在抛
            :class:`RepoDiscoveryError`。
        policy: 技术安全策略(缺省默认阈值;仅允许更严的配置语义不变)。
        discovery_rules: 既有源的持久发现策略(#22;治理记忆——由调用方从
            ``config.discovery_rules`` 读出传入;命中组继承决策并带
            admin_decision 呈现,L1 技术安全结论永不被规则翻转)。
    """
    owner, repo = parse_repo_url(repo_url)
    if not branch:
        meta = api_get(f"/repos/{owner}/{repo}")
        branch = str(meta.get("default_branch") or "")
        if not branch:
            raise RepoDiscoveryError(f"无法确定 {owner}/{repo} 的默认分支,请显式指定分支")
    payload = api_get(f"/repos/{owner}/{repo}/git/trees/{branch}?recursive=1")

    warnings: list[str] = []
    entries = list(payload.get("tree") or [])
    if payload.get("truncated"):
        warnings.append("仓库文件树过大,远端结果已截断,统计可能不完整(建议缩小范围或使用高级模式)")
    if len(entries) > MAX_TREE_ENTRIES:
        entries = entries[:MAX_TREE_ENTRIES]
        warnings.append(f"仓库文件超过 {MAX_TREE_ENTRIES} 个,发现结果已截断,统计可能不完整")

    candidates: list[FileAdmission] = []
    for entry in entries:
        admission = admission_from_tree_entry(entry, policy)
        if admission is not None:
            candidates.append(admission)
    if not candidates:
        warnings.append(f"未发现任何文件:分支 {branch} 上没有可统计的文件,请核对仓库与分支")

    # §9.2 L1 冻结(producer 层分类默认值;KnowledgeRole 词表与
    # recommendation_for 映射零改动——connectors/safety.py 禁触碰):
    #   技术不安全结论(模型工件/超大/密钥形态)→ 确定性排除
    #     (§9.1 冻结「unsafe → exclude,不可翻转」;v1.0.0 曾因 BINARY
    #      角色映射呈现为 review,与冻结语义不符,此处对齐);
    #   二进制资产后缀 / 无扩展名(按构造不可能被扩展名白名单匹配)
    #     → 确定性排除,不再是「待确认」常态组成员。
    # 这是 #22「Human Review 是例外路径」的 L1 落地,能力注记如实说明。
    for a in candidates:
        if not a.technical_safe:
            a.recommendation = "exclude"
        elif a.knowledge_role == KnowledgeRole.BINARY.value or not PurePosixPath(a.path).suffix:
            a.recommendation = "exclude"

    has_media = any(
        PurePosixPath(c.path).suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".wav", ".mp3", ".mp4", ".mov"}
        for c in candidates
    )
    has_extless = any(not PurePosixPath(c.path).suffix for c in candidates)
    capability_notes: list[str] = []
    if has_media:
        capability_notes.append(
            "图片/音视频资产:当前 ingestion 管线为文本抽取,不支持图片理解——此类文件"
            "已确定性排除(#22 L1),不会因仓库中存在而默认声明支持"
        )
    if has_extless:
        capability_notes.append(
            "无扩展名文件(如 LICENSE/Makefile):文件类型白名单按扩展名匹配,此类文件"
            "已确定性排除(#22 L1);如需纳入请使用高级选项在技术安全边界内核对"
        )
    capability_notes.append(
        "发现阶段仅基于路径与大小判定;内容层安全检查(如私钥材料嗅探)在同步灌入时执行,"
        "管理员配置不可绕过"
    )

    result = build_discovery_result(
        kind="github",
        target={"owner": owner, "repo": repo, "branch": branch},
        candidates=candidates,
        group_key=top_level_group,
        recommended_config=compile_recommended_config(candidates),
        warnings=warnings,
        capability_notes=capability_notes,
    )
    # #22:持久规则继承 → 重编译(规则决策进词表)→ scope_confirmed 机械确认。
    # 组级规则裁决(admin_decision)作为 compile 的 group_decisions 入参——
    # §11.1「既有 admin 规则编译进持久化词表」的显式通道:规则裁决解除组的
    # 平票歧义后,组内成员级推荐(安全 include)才进入白名单。
    rules = parse_discovery_rules(discovery_rules)
    result = apply_discovery_rules(result, rules)
    rule_decisions = {
        g.key: g.admin_decision for g in result.groups if g.admin_decision is not None
    }
    result.recommended_config = compile_recommended_config(result.candidates, rule_decisions)
    result.warnings = list(result.warnings) + annotate_scope(result)
    return result


def default_api_get(path: str) -> dict:
    """默认 GitHub API 读取(同步 httpx;GITHUB_TOKEN 可选,匿名受限速)。

    只在 route 的线程池中运行,不阻塞事件循环(504 事故纪律)。
    """
    import httpx

    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {
        "Accept": "application/vnd.github+json",
        **({"Authorization": f"Bearer {token}"} if token else {}),
    }
    try:
        with httpx.Client(timeout=30, headers=headers) as client:
            resp = client.get(f"{GITHUB_API_BASE}{path}")
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (401, 403, 429):
            raise RepoDiscoveryError(
                "GitHub API 拒绝访问(速率限制或 token 权限不足);私有仓库请配置只读 GITHUB_TOKEN"
            ) from exc
        if status == 404:
            raise RepoDiscoveryError(
                "仓库或分支不存在(或无权访问);请核对 URL 与分支,私有仓库需配置 GITHUB_TOKEN"
            ) from exc
        raise RepoDiscoveryError(f"GitHub API 错误(HTTP {status})") from exc
    except httpx.HTTPError as exc:
        raise RepoDiscoveryError(f"GitHub API 不可达: {type(exc).__name__}") from exc
