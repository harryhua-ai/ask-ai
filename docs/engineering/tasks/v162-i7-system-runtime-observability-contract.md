# FROZEN TASK CONTRACT — #7 Admin Read-Only System & Hardware Runtime Observability(B3)

Iteration:v1.6.2;owner=B3;依赖:NONE(与 B1/B2 完全并行);报告:
docs/engineering/tasks/v162-i7-system-runtime-observability-execution.md
(B3 产出)。

## Objective

运营员在 `配置 → 系统信息` 页新增的只读"系统运行时"分区,不 SSH 即可
完成例诊:主机身份、资源水位、GPU/推理运行时状态、ASK-AI 服务状态。

## Product Semantics

- 展示的每一项都来自**真实采集**(进程内只读收集/既有运行时快照);
  平台不可得的项(无 GPU、非 Linux 无 /proc 等)显示显式"不可用"态
  +原因,**永不虚构/填充占位值**。
- 候选信息(按 issue #7,采集可得性由 B3 按 4. Current Truth 裁定):
  hostname/OS/内核/uptime;部署版本/SHA/环境(复用既有 release 身份);
  CPU 核数与利用率;内存/swap;磁盘容量与占用(部署卷);GPU 利用率/
  显存/温度(可得时);驱动/CUDA/运行时信息;核心服务状态
  (/health + model-runtime 快照:devices/policies/capacity/runtime_plan)。
- 采样语义:v1 为按需读取 + 手动刷新(轻轮询由 B3 权衡,无实时要求);
  每项标注采集时间(as_of)。

## UX Intent

- 追加为 SystemInfo 页一节(该组件注释已预留此扩展),发布身份区保留在上;
  分区网格布局:主机 → 资源(CPU/内存/磁盘)→ 加速器 → 服务状态;
  状态语义沿用 badge 变体(ok/warning/不可用);loading/error 沿用
  LoadError 纪律;零操作按钮。

## Current Truth

已有:/system 页 = 发布身份;/api/admin/system/release;model-runtime
快照(devices/policies/capacity/runtime_plan,GPU 内存事实)+
hardware.py(CPU/内存发现、nvidia-smi 显存查询)+ /health。
缺失:主机名/OS/uptime/磁盘/CPU 利用率采集;GPU 利用率/温度;任何
聚合的 system runtime 端点;前端分区。

## Change Boundary

- **EXPECTED**:新只读 GET 端点(挂 /system router,形状 B3 设计):
  一次返回上述可得事实 + 每项 unavailable 语义;SystemInfo 新分区 UI;
  后端 pytest(真实采集 mock/fixture + 无 GPU 降级态)+ 前端 vitest。
- **REQUIRED SUPPORTING**(允许而非强制,由 B3 按验收需要取舍):只读
  扩展 nvidia-smi 查询字段(利用率/温度,与既有内存查询同权限同方式);
  如需采集库(如 psutil)允许引入(pyproject 变更记录进执行报告);
  读权限沿用既有 admin 读约定。
- **FORBIDDEN**:任何操作控制(restart/kill/cache-clear/reindex/shell/
  任意命令执行);写端点;暴露 env/secrets/凭据;虚构或缓存过期的
  硬件值;改变 model-runtime 管理面语义(#7 只加观察,不改
  /model-runtime)。
- **BEHAVIORAL**:纯新增观察面;既有发布身份区与 model-runtime 管理页
  零回归;全端点 GET-only。

## Dependencies

- inbound:NONE;outbound:NONE。

## Acceptance Criteria

1. 端点返回:主机身份、CPU、内存、磁盘、服务状态;GPU 段在无 GPU
   环境返回显式 unavailable(非错误、非空壳);每项含 as_of;
   后端测试覆盖可得/不可得两态 + RBAC。
2. UI 分区完整渲染四组信息;不可得项显示不可用态与原因;刷新交互可用。
3. 只读证明:改动集无任何非 GET 端点、无命令执行类写操作(代码审查
   可证);model-runtime 页零回归。
4. 后端 pytest 新增覆盖 + 全量回归绿;ruff 0 error;admin vitest 全绿。

## Runtime / Real-World Acceptance(强制,Phase 5)

- **GPU 主机**(生产或生产等价):走查截图显示真实主机事实,并与 SSH
  取证(uptime/df -h/nvidia-smi)抽查一致(比对仅用于取证);全程页面
  操作零 SSH;
- **无 GPU/开发环境**:同页面显示显式不可用态(非崩溃/非骨架空值);
Issue 关闭前置:部署后生产可见面与本合同语义一致。
