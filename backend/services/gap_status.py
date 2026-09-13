"""Answer Gap 状态词表常量(单一真相源;Wave 0B 仅迁移既有值)。

Ownership: Track E (observation) — Wave 1(IF-1 挂载点:observing 状态、
观察元数据与流转事件只允许 Track E 在 Wave 1 于本模块/其子模块扩展;
其余轨不得新增状态词表值)。

Wave 0B 边界(remediation plan §3.0.1):本模块仅含 7e3e71c 既有两态词表
(open / resolved)的逐字迁移;question_clusters.status 的 DB 列语义、
Query 校验 pattern 与投影行为逐字节不变。零 observing 语义(禁止提前实现)。
"""

# 权威两态词表(既有值逐字迁移;仅 gap 聚类;Wave 1 Track E 扩展处)。
GAP_STATUSES: tuple[str, ...] = ("open", "resolved")

# 既有 API 校验 pattern 逐字迁移(analytics.py / tech.py 同源消费)。
GAP_STATUS_PATTERN = "^(open|resolved)$"
