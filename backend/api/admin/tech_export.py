"""技术性能端点 —— 缺口导出子模块(Wave 0B 结构完备,IF-6 拆分落位)。

**Ownership(IF-6 附录):本文件 = Track E(观察与导出)Wave 1 专属。**
对应 remediation plan §3.2 item 2 拆分地图中的 tech_export.py
(CSV 流式 + 审计;U-16;导出列集/隐私字段排除清单 = IF-5 冻结合同)。

Wave 0B 状态:**空 router 模块 —— 零端点、零 schema、零行为。**
本模块已由 tech.py ``include_router`` 挂载(挂载序在既有三路由之后,
空 router 不产生任何 OpenAPI path/术语变化)。Wave 1 Track E 在本文件内
新增路由即可暴露未来导出端点,**无需编辑 backend/api/admin/tech.py**。

硬边界(§3.0.1 四零约束):本 Wave 禁止任何端点/参数/CSV 列/行为实现;
一切产品语义归 Wave 1 Track E。
"""

from fastapi import APIRouter

# 子 router 无 prefix/tags:由 tech.py 的 tech_router(prefix="/tech",
# tags=["技术性能"])统一装配,保证 OpenAPI 逐字节不变(同 tech_answer_gaps.py)。
router = APIRouter()
