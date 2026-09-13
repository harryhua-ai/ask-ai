"""技术性能端点 —— 证据聚合子模块(Wave 0B 结构完备,IF-6 拆分落位)。

**Ownership(IF-6 附录):本文件 = Track F(证据聚合)Wave 1 专属。**
对应 remediation plan §3.2 item 2 拆分地图中的 tech_evidence.py
(用户聚合/归因/topic;U-17/U-18/U-19;U-17 聚合窗 = IF-7 所选分析窗)。

Wave 0B 状态:**空 router 模块 —— 零端点、零 schema、零行为。**
本模块已由 tech.py ``include_router`` 挂载(挂载序在既有三路由之后,
空 router 不产生任何 OpenAPI path/术语变化)。Wave 1 Track F 在本文件内
新增路由即可暴露未来证据聚合端点,**无需编辑 backend/api/admin/tech.py**。

硬边界(§3.0.1 四零约束):本 Wave 禁止任何端点/参数/聚合投影/行为实现;
一切产品语义归 Wave 1 Track F。
"""

from fastapi import APIRouter

# 子 router 无 prefix/tags:由 tech.py 的 tech_router(prefix="/tech",
# tags=["技术性能"])统一装配,保证 OpenAPI 逐字节不变(同 tech_answer_gaps.py)。
router = APIRouter()
