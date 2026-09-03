"""Source Center 共享 API domain schemas(S0)。

仅 #16/#17/#18 后续共同消费的 request/response 模型;**不含任何端点**,
也不挂载进既有 router(避免与并行 W0 波的 schemas.py/data_sources.py
hunk 冲突)。三个 feature wave 实现端点时从这里 import。

 Discovery contract 与 ``backend/services/source_discovery.DiscoveryResult``
 一一对应;候选条目即 ``connectors.safety.FileAdmission`` 的 wire 形态。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.connectors.safety import FileAdmission
from backend.services.source_discovery import CandidateGroup, DiscoveryResult


class GitHubDiscoveryRequest(BaseModel):
    """#16 Git Discovery 请求(Simple UX:URL + 分支,clone_path 等下沉 Advanced)。"""

    repo_url: str = Field(min_length=1, description="如 https://github.com/<owner>/<repo>.git")
    branch: str | None = Field(default=None, description="缺省时由远端默认分支决定")


class WebsiteDiscoveryRequest(BaseModel):
    """#17 Website Discovery 请求(普通用户只填 base_url)。"""

    base_url: str = Field(min_length=1, description="站点根,如 https://www.camthink.ai")
    sitemap_url: str | None = Field(default=None, description="Advanced:显式 sitemap 地址")


class DiscoveryCandidateOut(BaseModel):
    """逐候选准入结论(wire 形态 = FileAdmission + 人读理由)。"""

    path: str  # 文件相对路径或规范 URL
    size: int
    technical_safe: bool
    technical_reason: str | None = None
    knowledge_role: str
    recommendation: str  # include | exclude | review
    policy_result: str = "not_applied"
    eligible: bool = True
    reason: str  # 人读固定文案(source_discovery.reason_text)

    @classmethod
    def from_admission(cls, a: FileAdmission) -> "DiscoveryCandidateOut":
        from backend.services.source_discovery import reason_text

        return cls(
            path=a.path,
            size=a.size,
            technical_safe=a.technical_safe,
            technical_reason=a.technical_reason,
            knowledge_role=a.knowledge_role,
            recommendation=a.recommendation,
            policy_result=a.policy_result,
            eligible=a.eligible,
            reason=reason_text(a),
        )


class DiscoveryGroupOut(BaseModel):
    key: str
    count: int
    total_size: int
    recommendation: str
    samples: list[str] = []

    @classmethod
    def from_group(cls, g: CandidateGroup) -> "DiscoveryGroupOut":
        return cls(
            key=g.key,
            count=g.count,
            total_size=g.total_size,
            recommendation=g.recommendation,
            samples=g.samples,
        )


class DiscoveryResultOut(BaseModel):
    """#16/#17 preview 端点统一 envelope。

    ``recommended_config`` 是推荐编译产物 = 既有 config JSONB 词表
    (file_types / exclude_dirs / …),PD-2:不建立第二套 sync semantics。
    """

    kind: str
    target: dict
    totals: dict
    by_role: dict
    groups: list[DiscoveryGroupOut]
    candidates: list[DiscoveryCandidateOut]
    recommended_config: dict
    warnings: list[str]
    capability_notes: list[str]

    @classmethod
    def from_result(cls, r: DiscoveryResult) -> "DiscoveryResultOut":
        return cls(
            kind=r.kind,
            target=r.target,
            totals=r.totals,
            by_role=r.by_role,
            groups=[DiscoveryGroupOut.from_group(g) for g in r.groups],
            candidates=[DiscoveryCandidateOut.from_admission(a) for a in r.candidates],
            recommended_config=r.recommended_config,
            warnings=r.warnings,
            capability_notes=r.capability_notes,
        )


class SourceLifecycleOut(BaseModel):
    """源生命周期 wire 形态(#18:DataSourceOut 扩展块)。

    ``lifecycle_state`` 为规范值(NULL 已归一为 ``active``),前端无需
    处理 NULL 语义。
    """

    lifecycle_state: str  # active | delete_requested | deleting | delete_failed
    lifecycle_since: str | None = None
    lifecycle_error: str | None = None


class DeletionActionOut(BaseModel):
    """#18 DELETE/retry 的 202 受理响应(非阻塞契约)。"""

    source_id: str
    state: str  # delete_requested | deleting
    detail: str | None = None
