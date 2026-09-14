"""Answer Gap 状态词表常量(单一真相源;IF-1 挂载点)。

Ownership: Track E (observation) — Wave 1(IF-1:observing 状态、观察元数据与
流转事件只允许 Track E 在本模块/E 子模块扩展;其余轨不得新增状态词表值)。

Wave 1 扩展(U-15 / track-e-contract):状态词表 open|observing|resolved
三态。pattern 为纯字符串拼接常量,analytics.py / tech_answer_gaps.py 等既有
消费方 import 本模块常量即零 diff 自动生效(词表单一真相源)。
观察状态机的转移语义与持久化见 backend/services/gap_observation.py。
"""

# 权威三态词表(IF-1;open=需要处理 / observing=观察中 / resolved=已解决)。
GAP_STATUSES: tuple[str, ...] = ("open", "observing", "resolved")

# API 校验 pattern(既有消费方 analytics.py / tech_answer_gaps.py 同源消费)。
GAP_STATUS_PATTERN = "^(open|observing|resolved)$"
