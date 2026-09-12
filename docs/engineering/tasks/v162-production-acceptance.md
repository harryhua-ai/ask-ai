# v1.6.2 PRODUCTION ACCEPTANCE — DEPLOYED / ACCEPTED / COMPLETE

Final verdict: **V1.6.2 = DEPLOYED / PRODUCTION ACCEPTED / COMPLETE**

- Pre-merge main:`0590a82`;**final main:`ed71be7`**(ff-only,三通道一致)
- Release:**v1.6.3** @ `ed71be7`(tag `2f0a26a` annotated);部署 run **34698697272 = success**
- 生产身份:`/health = {"ok","1.6.3","ed71be77…"}`,backend healthy,restarts=0,
  三服务全 v1.6.3,PG/Weaviate 未动(Up 3 weeks);部署桥迁移双条目幂等 NO-OP
- 证据:`~/Documents/ask-ai-acceptance/v162-integration-20260912/`
  (prod-b3-gpu-runtime.png / prod-b2-incidents.png / prod-b1-detail-drilled.png
  + 集成期 3 张)

---

## 0. 发布工程事故与矫正(如实记录)

1. **v1.6.2 tag 构建失败(build 34697762577/34697762573)**:CI 在干净树上
   `tsc` 抓到 `DataSourceDetail.tsx` TS2345——整合期该类型修复
   (`ReasonInput.current_version_seq` → optional)发生在 `9892ebb` 提交之后
   **被遗漏提交**,本地验证测的是脏树(执行事故;该修复实质本就在 Role A
   批准的窄加固清单内,仅提交遗漏)。test job 绿、build-and-push 止于 SPA
   类型检查,无镜像产出,零下游消费。
2. **矫正(不动既有 tag)**:`ed71be7` 提交修复 → main ff → **v1.6.3**
   (v1.6.2 tag/Release 依不重写纪律原样冻结保留;v1.6.3 Release 注明
   delta = 1 commit +3/−1)→ build 34698126440 双绿 → 部署。
3. 干净树全量 tsc 0 error + vite build ✓ + 定向 40 绿后出 tag。

## 1. #50 生产验收 —— PASS(真实 Admin 面,wiki-data.camthink.ai/admin)

- **wiki-documents-local**:详情路由生产可用;账本 **467 篇·在服 467**
  (与生产 DB 真值精确一致);三桶 当前在服 467/需要关注 0/已退役 0;
  计数真相诚实注记;**索引生成区显式"该源尚无索引生成记录(后端无此
  记录)"**(该源生产从未重建——缺席语义正确,不虚构);
- **woocommerce-mall**:41 篇全在服(真值一致);真实产品行 canonical ID
  (`woocommerce-mall/4271|5883|1984`)+ 搜索/过滤/分页在位;
- 既有数据源功能完好(列表/同步/健康面板,回归套件全绿)。

## 2. #51 生产验收 —— PASS

- 事件区渲染 **四条真实生产事件**:含 TB-P1 reindex 缺陷真实审计行
  「生成失败 neomind-dashboard-local 第 1 代 488>16」+ 三条真实 embed
  失败(wiki 21>16 / sdks 20>16),severity/来源/时间/原因齐备;
- **跨轨下钻真实点击**:事件行 → `/admin/data-sources/neomind-dashboard-local`
  正确来源详情面,索引生成表显 #1 失败代 + 488>16 failure 原文
  (TB-P1 §17 审计行现已运营可见);
- 缺口→对话下钻(冻结 `?q=` 语法)在组合树与生产面语法一致;
- 非重叠:洞察页无源清单/配置控件;既有 TechPerf/KnowledgeGaps 面板完好。

## 3. #7 生产验收 + 强制 GPU gate —— PASS(真实 GPU 主机逐项比对)

生产 `/admin/system` 系统运行时 vs 独立 SSH 真值(`nvidia-smi`/`uptime`/`df`,只读):

| 项 | UI/API 显示 | 独立真值 | 判定 |
| --- | --- | --- | --- |
| GPU 身份 | Tesla T4 · GPU 0 | Tesla T4 | ✅ |
| UUID | GPU-3caad314-5735-d4c2-64ce-e82bb88a11ba | 同(逐字符) | ✅ |
| 利用率 | 0% | 0% | ✅ |
| 显存 | 12499 / 16384 MiB | 12499 / 16384 MiB | ✅ 精确 |
| 温度 | 41°C | 41 | ✅ |
| 驱动 | 575.64.03 | 575.64.03 | ✅ |
| CUDA | 12.9 | (driver 575 系) | ✅ |
| 主机 uptime | 402 天 12 小时 | up 402 days | ✅ |
| 内核 | 5.15.0-151-generic | 同 | ✅ |
| 磁盘 | 1279.5GB/305.9 用/23.9% | 1.3T/306G/25%(舍入口径) | ✅ |
| 服务 | 1.6.3(production)+ 三 workload loaded·Tesla T4 | healthy | ✅ |

- no-GPU 不可得语义:测试双态覆盖(两态 fixture)+ 开发主机 live 已证
  (集成报告 §5);生产 Linux /proc 全可得(CPU 型号/利用率/内存真实渲染);
- 只读边界:刷新=全页唯一按钮;零控制/零 secret。
- 注:主机名显示为 backend 容器 ID(合同裁定=容器内进程内采集;
  uptime/内核经共享 /proc 反映宿主——部署拓扑预期语义)。

## 4. Final Product Gate

- 生产身份 = 部署接受树:`1.6.3 @ ed71be77` ✓(tag peel/Release/镜像
  RELEASE.json/Deployment run/health 五方同源);
- #50/#51/#7 生产可见面与接受语义一致(§1–3);#51→#50 真实下钻 ✓;
- GPU gate PASS(§3);
- 健康/回归:restarts=0,部署后 backend 零 ERROR/Traceback,storefront
  www.camthink.ai 200,widget 经 backend vhost 200 且有真实流量;
- 无未解释回归。

**观察项(非回归,正交)**:`https://www.camthink.ai/widget/widget.js`
现 404(backend vhost 同路径 200、278KB、真实流量正常;widget/ 代码自
v1.6.1 **零变更**)——www 边缘代理层行为,属 www 站点自身配置域,建议
知会站点负责人另行核查;不影响本 release 任何验收 gate。

## 5. GitHub Closure 与 PA 对账

- **#50 CLOSED/completed**、**#51 CLOSED/completed**、**#7 CLOSED/completed**,
  全部保留 `iteration:v1.6.2` 标签;关闭评论附生产证据;
- Project Automation 收敛:3 条关闭事件触发 **Project Sync ×3 全 success**
  (run 34699164705/34699166343/34699168113),Issue 终态 CLOSED/COMPLETED
  与标签核验一致。

## 6. Unresolved Risks

1. www 边缘 widget 路径 404(正交观察项,§4);
2. reindex 缺陷(RemoteSyncEmbedder 切批矫正候选 trace-b/remote-embedder-
   batch-corrective-20260912 @ d269312,已 Role A 待审)——生产重建路径
   仍不可用,事件区已如实呈现该事实(本迭代范围外);
3. 本地 dev 种子数据与本地栈进程已清理/无权威影响;
4. `documents` 清单端点在数十万级源上的聚合查询模式与 `/sync-health`
   同口径,超大源后续可做索引/游标调优(非当前生产规模问题)。

---

V1.6.2 = DEPLOYED / PRODUCTION ACCEPTED / COMPLETE
