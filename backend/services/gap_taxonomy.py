"""Answer Gap 原因分类词表常量(单一真相源;Wave 0B 仅迁移既有值)。

Ownership: Track D (taxonomy) — Wave 1(IF-2 挂载点:六新类+证据规则只允许
Track D 在 Wave 1 于本模块扩展;其余轨不得新增词表值)。

Wave 0B 边界(remediation plan §3.0.1):本模块仅含 7e3e71c 既有 4 类词表
(reject / low / 召回空 / 召回不足)与 未分类 兜底值的逐字迁移,消费方改
import(analytics.py 投影 / tech.py→tech_answer_gaps.py 同源消费);
零新增词表值,分类判定逻辑仍在原处(analytics.classify_gap_miss_types),
本模块不是分类器。

分类语义(spec D4,权威来源 = backend/api/admin/analytics.py:
classify_gap_miss_types,消费方必须同源):
- reject:is_answered=False(拒答,用户未获回答)
- low:answered, sources 非空, 最新 trace confidence<0.6(低相关)
- 召回空:answered, sources 空(已回答但未检索到任何知识来源)
- 召回不足:answered, sources 非空, confidence>=0.6 或无 trace
"""

# 权威 miss_type 词表(既有 4 类,逐字迁移;Wave 1 Track D 扩展处)。
GAP_MISS_REJECT = "reject"
GAP_MISS_LOW = "low"
GAP_MISS_RECALL_EMPTY = "召回空"
GAP_MISS_RECALL_INSUFFICIENT = "召回不足"

GAP_MISS_TYPES: tuple[str, ...] = (
    GAP_MISS_REJECT,
    GAP_MISS_LOW,
    GAP_MISS_RECALL_EMPTY,
    GAP_MISS_RECALL_INSUFFICIENT,
)

# 无任何会话证据/未知分类的兜底值(既有字面量逐字迁移)。
GAP_MISS_UNCLASSIFIED = "未分类"
