"""技术性能聚合端点 —— router 装配模块(Wave 0B 结构预备,IF-6 拆分落位)。

v1.6.3 Wave 0B(remediation plan §3.0.1/§3.2 item 2):实现按自然边界拆分至
子模块,本模块保留既有 FastAPI router 挂载入口(backend/api/admin/router.py
``from backend.api.admin.tech import tech_router`` 零改动)与路由注册序。
全部路由路径/方法/参数/响应形状逐字节不变;零新端点、零新参数语义。

子模块 → 轨所有权(IF-6 附录):
- tech_performance.py        —— S1 性能聚合(窗口面 = Track A,BC 前端接线);
- tech_generation_events.py  —— S4 生成级事件流(§3.5 例外面冻结);
- tech_answer_gaps.py        —— S5 缺口队列(窗口面=Track A/BC-1、
                                cause/分类面=Track D、status 面=Track E)
                                + S6 归属会话证据(例外面冻结)。

Wave 1 轨专属空 router(本 Wave 结构完备落位,零端点):tech_observation.py /
tech_export.py(E)、tech_evidence.py(F)已挂载;Wave 1 各轨在各自模块内
新增路由即可暴露端点,无需再编辑本文件(本文件此后仅 Integration 仲裁)。
"""

from fastapi import APIRouter

from backend.api.admin.tech_answer_gaps import router as _answer_gaps_router
from backend.api.admin.tech_evidence import router as _evidence_router
from backend.api.admin.tech_export import router as _export_router
from backend.api.admin.tech_generation_events import router as _generation_events_router
from backend.api.admin.tech_observation import router as _observation_router
from backend.api.admin.tech_performance import router as _performance_router

tech_router = APIRouter(prefix="/tech", tags=["技术性能"])

# 注册序 = 7e3e71c 原文件内路由序(performance → generation-events →
# answer-gaps → answer-gaps/{gap_id}/conversations),保证路由表逐字节不变;
# 其后为 Wave 0B 结构完备追加的三个空 router(E/F 专属挂载点,
# 零端点 → 零 OpenAPI path/术语变化)。
tech_router.include_router(_performance_router)
tech_router.include_router(_generation_events_router)
tech_router.include_router(_answer_gaps_router)
tech_router.include_router(_observation_router)
tech_router.include_router(_export_router)
tech_router.include_router(_evidence_router)
