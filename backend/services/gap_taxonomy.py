"""Answer Gap 原因分类词表常量 + 单会话证据规则(单一真相源;IF-2)。

Ownership: Track D (taxonomy) — Wave 1(IF-2 挂载点:六新类+证据规则只允许
Track D 在 Wave 1 于本模块扩展;其余轨不得新增词表值)。

Wave 0B 边界(remediation plan §3.0.1):本模块原仅含 7e3e71c 既有 4 类词表
(reject / low / 召回空 / 召回不足)与 未分类 兜底值的逐字迁移。
Wave 1 U-14(track-d-contract,已冻结):在本模块扩展参考要求(TI-09)的
六新类词表与**每类后端证据规则**,并承载单会话分类纯函数
``classify_conversation_miss_type``(可从真实证据确定性复现;禁 keyword
猜测、禁 label-only)。批量分类器仍在 analytics.classify_gap_miss_types
(证据 IO + 聚类主导归并),消费方同源(tech_answer_gaps.py 投影透传)。

分类语义(v1.6.3 Wave 1 全词表;权威来源 =
backend/api/admin/analytics.py:classify_gap_miss_types,消费方必须同源):

既有 4 类(语义逐字不变;无新类证据时原判不变):
- reject:is_answered=False(拒答,用户未获回答;无生成失败/零候选证据)
- low:answered, sources 非空, 最新 trace confidence<0.6(低相关)
- 召回空:answered, sources 空(已回答但未检索到任何知识来源)
- 召回不足:answered, sources 非空, confidence>=0.6 或无 trace

U-14 六新类(每类=后端证据规则,参考词表 TI-09,不再发明):
- 生成异常  = generation failure 真相:最新 Trace.type=generation_error
  (PC-06 结构化失败持久化;config_snapshot.failure_kind 记
  empty_generation/provider_error/stream_interrupted)。
  失败会话 NA-05 强制 is_answered=False,故本规则优先于 reject,
  否则该真相永不可见;无此 trace 证据的未回答会话仍判 reject。
- 内容缺失  = 知识缺失变体:is_answered=False + sources 空 + 最新 rag
  trace 检索阶段 hybrid_count==0(知识库对该内容零候选,拒答因内容缺失)。
  召回空(answered+零来源)空间不变。
- 引用异常  = 引用一致性违例:answered + sources 非空 + 答案含 [N] 引用
  标记且 N 越界(N=0 或 N>len(sources);标记形状契约同
  backend.pipeline.citation:1-3 位数字、非 Markdown 链接形态)。
  召回空(answered+零来源)空间不变(本规则要求 sources 非空)。
- 内容冲突  = 多源冲突真相:同一会话同时引用 superseded 文档与其接替者
  (documents.superseded_by 链上两端均出现在 sources 的 source_id 集)。
- 内容过期  = 内容时间真相:所引文档(第一方 source_id→documents)内容
  最后更新时间早于会话时间超过 GAP_STALE_CONTENT_DAYS 天。
- 检索异常  = 检索异常证据:answered + sources 非空 + 最新 trace 检索阶段
  未达最低有效召回(stages.retrieve.min_results_met=False,或
  hybrid_count<effective_min)。

优先级(IF-2 冻结):生成异常 > 内容缺失 > reject;
引用异常 > 内容冲突 > 内容过期 > 检索异常 > low/召回不足;
召回空 空间不变(六新类中仅内容缺失/生成异常落未回答侧,其余要求
sources 非空)。新类=更具体的确定性证据,优先于置信度代理(low/召回不足);
旧 4 类谓词在无新类证据时逐字保持(spec 冻结「不改既有 4 类语义」)。
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

# 权威 miss_type 词表(既有 4 类,逐字迁移)。
GAP_MISS_REJECT = "reject"
GAP_MISS_LOW = "low"
GAP_MISS_RECALL_EMPTY = "召回空"
GAP_MISS_RECALL_INSUFFICIENT = "召回不足"

# U-14 六新类(TI-09 参考要求扩展;字面=参考词表逐词,即权威机器值)。
GAP_MISS_STALE_CONTENT = "内容过期"
GAP_MISS_RETRIEVAL_ANOMALY = "检索异常"
GAP_MISS_GENERATION_FAILURE = "生成异常"
GAP_MISS_CITATION_ANOMALY = "引用异常"
GAP_MISS_CONTENT_CONFLICT = "内容冲突"
GAP_MISS_CONTENT_MISSING = "内容缺失"

GAP_MISS_TYPES: tuple[str, ...] = (
    GAP_MISS_REJECT,
    GAP_MISS_LOW,
    GAP_MISS_RECALL_EMPTY,
    GAP_MISS_RECALL_INSUFFICIENT,
    GAP_MISS_STALE_CONTENT,
    GAP_MISS_RETRIEVAL_ANOMALY,
    GAP_MISS_GENERATION_FAILURE,
    GAP_MISS_CITATION_ANOMALY,
    GAP_MISS_CONTENT_CONFLICT,
    GAP_MISS_CONTENT_MISSING,
)

# 无任何会话证据/未知分类的兜底值(既有字面量逐字迁移)。
GAP_MISS_UNCLASSIFIED = "未分类"

# ---- IF-2 证据规则冻结常量 --------------------------------------------- #

# 内容过期阈值(天):所引文档内容最后更新早于会话超过该值 → 内容时间真相。
GAP_STALE_CONTENT_DAYS = 180

# low 分类置信度阈值(既有 0.6 字面量收编为常量,语义逐字不变)。
GAP_MISS_LOW_CONFIDENCE = 0.6

# 生成失败 trace 类型(PC-06 持久化真值;routes.py 落列)。
GAP_TRACE_GENERATION_ERROR = "generation_error"

# 引用标记形状契约(与 backend.pipeline.citation 一致):
# [N] N 为 1-3 位数字;后随 "(" 为 Markdown 链接形态,不按引用处理。
_GAP_CITATION_MARKER_RE = re.compile(r"\[(\d{1,3})\](?!\()")


@dataclass(frozen=True)
class CitedDocEvidence:
    """被引用第一方文档的确定性证据快照(documents 行投影)。"""

    updated_at: datetime | None = None
    superseded_by: str | None = None


def extract_cited_source_ids(sources: Any) -> list[str]:
    """从 Conversation.sources(JSONB)提取第一方来源身份(source_id)。

    仅取 dict 形态且带非空字符串 source_id 的条目(第一方知识案例投影;
    公开 url 来源无 source_id,不参与 documents 证据规则)。
    """
    if not isinstance(sources, list):
        return []
    out: list[str] = []
    for entry in sources:
        if isinstance(entry, dict):
            sid = entry.get("source_id")
            if isinstance(sid, str) and sid:
                out.append(sid)
    return out


def has_dangling_citation(answer: Any, n_sources: int) -> bool:
    """引用一致性违例真相:答案含越界 [N] 引用标记(N=0 或 N>n_sources)。

    n_sources<=0 时恒 False(该形态属召回空冻结空间,不在此判)。
    """
    if n_sources <= 0 or not isinstance(answer, str):
        return False
    for m in _GAP_CITATION_MARKER_RE.finditer(answer):
        n = int(m.group(1))
        if n == 0 or n > n_sources:
            return True
    return False


def _trace_retrieve_stage(trace_stages: Any) -> dict[str, Any] | None:
    """取 trace.stages 的 retrieve 阶段(非 dict 形态安全回退)。"""
    if not isinstance(trace_stages, dict):
        return None
    stage = trace_stages.get("retrieve")
    return stage if isinstance(stage, dict) else None


def _retrieval_below_minimum(retrieve_stage: dict[str, Any]) -> bool:
    """检索异常证据:检索未达最低有效召回(min_results_met=False 或
    hybrid_count<effective_min;两种持久化形态等价判定)。"""
    if retrieve_stage.get("min_results_met") is False:
        return True
    hybrid = retrieve_stage.get("hybrid_count")
    effective_min = retrieve_stage.get("effective_min")
    if isinstance(hybrid, int) and isinstance(effective_min, int):
        return hybrid < effective_min
    return False


def _has_superseded_conflict(
    cited_source_ids: list[str], cited_docs: dict[str, CitedDocEvidence]
) -> bool:
    """内容冲突真相:同会话同时引用 superseded 文档与其接替者。"""
    cited_set = set(cited_source_ids)
    for sid in cited_source_ids:
        doc = cited_docs.get(sid)
        if doc is not None and doc.superseded_by and doc.superseded_by in cited_set:
            return True
    return False


def _has_stale_content(
    cited_source_ids: list[str],
    cited_docs: dict[str, CitedDocEvidence],
    conversation_at: datetime | None,
) -> bool:
    """内容过期真相:任一所引文档内容更新早于会话超过冻结阈值。"""
    if conversation_at is None:
        return False
    cutoff = conversation_at - timedelta(days=GAP_STALE_CONTENT_DAYS)
    for sid in cited_source_ids:
        doc = cited_docs.get(sid)
        if doc is not None and doc.updated_at is not None and doc.updated_at < cutoff:
            return True
    return False


def classify_conversation_miss_type(
    *,
    is_answered: bool,
    sources: Any,
    answer: Any,
    trace_type: str | None,
    trace_stages: Any,
    trace_confidence: float | None,
    cited_docs: dict[str, CitedDocEvidence] | None,
    conversation_at: datetime | None,
) -> str:
    """单会话证据 → 权威原因分类(纯函数,IF-2 冻结;可确定性复现)。

    优先级 = 证据具体性(见模块 docstring);无新类证据时旧 4 类谓词
    逐字保持。输入均为从真实行构造的证据快照(Conversation/Trace/
    documents),禁 keyword 文本猜测。
    """
    docs = cited_docs or {}
    source_list = sources if isinstance(sources, list) else []
    cited_source_ids = extract_cited_source_ids(source_list)
    retrieve_stage = _trace_retrieve_stage(trace_stages)

    # 1. 生成失败真相(generation failure;失败会话强制未回答,优先于 reject)
    if trace_type == GAP_TRACE_GENERATION_ERROR:
        return GAP_MISS_GENERATION_FAILURE

    if not is_answered:
        # 2. 内容缺失(知识缺失变体):未回答 + 零来源 + 检索零候选
        if (
            not source_list
            and retrieve_stage is not None
            and retrieve_stage.get("hybrid_count") == 0
        ):
            return GAP_MISS_CONTENT_MISSING
        # 旧类:拒答(语义逐字不变)
        return GAP_MISS_REJECT

    # 旧类:召回空(answered + sources 空;六新类其余规则要求 sources 非空,
    # 本冻结空间不侵入)
    if not source_list:
        return GAP_MISS_RECALL_EMPTY

    # 3. 引用一致性违例(答案引用编号越界)
    if has_dangling_citation(answer, len(source_list)):
        return GAP_MISS_CITATION_ANOMALY
    # 4. 多源冲突真相(superseded 与其接替者同被引用)
    if _has_superseded_conflict(cited_source_ids, docs):
        return GAP_MISS_CONTENT_CONFLICT
    # 5. 内容时间真相(所引文档内容过期)
    if _has_stale_content(cited_source_ids, docs, conversation_at):
        return GAP_MISS_STALE_CONTENT
    # 6. 检索异常证据(未达最低有效召回)
    if retrieve_stage is not None and _retrieval_below_minimum(retrieve_stage):
        return GAP_MISS_RETRIEVAL_ANOMALY

    # 旧类(谓词语义逐字不变):
    if trace_confidence is not None and trace_confidence < GAP_MISS_LOW_CONFIDENCE:
        return GAP_MISS_LOW
    return GAP_MISS_RECALL_INSUFFICIENT
