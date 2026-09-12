# v1.6.2 INTEGRATION B 执行报告

Final verdict: **V1.6.2 INTEGRATION = CANDIDATE READY**

- Integration 分支:**`integration/v162-20260912`**(已推送)
- Starting main SHA:**`0590a82`**(执行期间 origin/main 未移动,fresh fetch 复验,零漂移)
- **组合树最终候选 SHA:`9892ebb`**
- 证据目录:`~/Documents/ask-ai-acceptance/v162-integration-20260912/`(3 截图)

---

## 1. 组合拓扑(零改写)

```
0590a82 (origin/main)
  └─ f076b42 merge --no-ff  B1 #50  @ 9dc74c6 (4 commits 保全)
       └─ 3f35e3f merge --no-ff  B2 #51  @ 9218528 (保全)
            └─ ae75ca7 merge --no-ff  B3 #7  @ b762f2b (保全)
                 └─ 9892ebb hardening(integration): Role A 窄加固 9 项(组合树自身增量提交)
```

三次 merge **零冲突**(与 Role A 评审的零文件交集结论一致);三个候选的全部
提交 SHA 原样保留(merge 不改写);无 cherry-pick。

## 2. Role A 窄加固落地(独立提交 9892ebb,零语义变更)

| Track | 项 | 落地 |
| --- | --- | --- |
| B1 | `/documents/detail` 405 守卫 | `test_document_detail_and_generations_endpoints_are_read_only`(POST+DELETE × 2 路由) |
| B1 | `/generations` 405 守卫 | 同上 |
| B1 | %/_ LIKE 转义回归 | `test_inventory_like_wildcards_are_escaped_not_interpreted`(通配符字面匹配 = 0 命中 + 真实子串命中)+ `test_inventory_wildcard_source_id_does_not_leak_cross_source`(跨源隔离) |
| B1 | retired 行内联原因 | `DataSourceDetail.tsx` 行内原因条件从 `bucket==="attention"` 放宽为 `bucket!=="current"`(retired 行现显示 已接替/墓碑 原因;runtime 截图可见) |
| B2 | failed `event_at` 精确断言 | `test_generation_events_event_at_semantics` 补 `items["failed"]["event_at"] == failed_updated_at.isoformat()` |
| B2 | 共享库 total 断言范围 | 范围注记写入 docstring(共享库无其他 failed/retired 播种;未来需收窄为前缀断言) |
| B3 | 事件循环卸载 | `GET /system/runtime` 改经 `run_in_threadpool(collect_system_runtime)`(subprocess/0.1s 双采样/文件 IO 不再阻塞 loop;nvidia-smi 卡死上限 = 10s 超时 × 线程池 worker) |
| B3 | `os.cpu_count() is None` | 显式不可得四元组(维持 available=True ⇒ value 非空 不变量) |
| B3 | loadavg 5m/15m | **决定:渲染**(SystemInfo 资源组三值齐显;采集已有、类型已有,渲染消除歧义) |
| B3 | 微测试缺口 ×2 | `test_platform_facts_raise_degrades_not_raises`(platform 抛错 → 整体形状完整 + os/kernel 显式不可得)+ `test_smi_int_not_supported_field_is_none`(`[Not Supported]`/N/A/空 → None) |

加固过程中发现并修复一个 B1 类型缝隙(评审 tsc 噪声下暴露):
`ReasonInput.current_version_seq` 改 optional(`notServingReason` 不引用该
字段;兼容清单行/真相两种输入形状)——修后非 widget tsc error = **0**
(widget 子项目缺自身 node_modules 的既有噪声,B1/B3 报告已记录,main 同样存在)。

## 3. 组合树回归(全部在 `9892ebb` 上执行)

| 套件 | 结果 |
| --- | --- |
| **后端全量 `pytest tests/`** | **2481 passed / 8 skipped / 0 failed**(114.6s;HF_HUB_OFFLINE=1 + MODEL_CACHE_DIR,首跑因缺此环境卡模型下载已重跑) |
| Project Automation | **114 passed** |
| admin vitest | **362 passed / 49 files**(含 9 项加固相关) |
| tsc(非 widget) | **0 error**;`vite build` **✓ built** |
| ruff(全部改动后端文件) | All checks passed |
| 定向(加固影响面 5 套件) | 58 passed |

继承失败分类:**无**——零失败,无需分类。(注:2481 vs B1 单轨 2448 的差 =
B2/B3 新测试 + 加固新测试在同一库上的合计;无冲突。)

## 4. 强制跨轨验收:#50 → #51 冻结接口 gate —— PASS(真实交互)

本地全栈(集成树 backend uvicorn:8000 + admin vite:5174 + docker
PG/Weaviate;种子数据:wiki-documents-local 源 × 6 文档全 L 轴状态 ×
gen7 ready/gen8 failed×422 证据 × failed sync_run × 未回答对话/缺口簇):

1. Admin 真实登录(admin@camthink.ai);
2. `技术洞察` → **同步/索引/生成事件**区渲染两条真实事件:
   「生成失败 wiki-documents-local batch embed failed: … 488 > 16 · 第 8 代」+
   「同步失败 … @ embed」(severity 红点/来源/原因/时间齐备);
3. **真实点击**「生成失败」事件行 → URL 变为
   `/admin/data-sources/wiki-documents-local`(encoded source_id 直达);
4. **B1 详情工作面为正确来源完整渲染**(见 §5)。

冻结接口在 B2 孤立分支无法证明的部分(实际点击到达 B1 面)在组合树
**以真实浏览器交互证明**。

## 5. 各轨 runtime 证据(组合树,真实数据)

**B1(#50)**:详情工作面四区齐备——源身份与配置/五维健康面板(复用)/
内容清单(权威账本):三桶徽章 当前在服 3 · 需要关注 1 · 已退役 2,
账本 6 篇·在服(含宽限)3 篇,计数真相诚实注记(已索引计数不由账本直接
证明);清单表 6 行全 L 轴状态,**全部非 Current 行内联权威原因**
(源中缺失宽限期/已接替(接替者:后端无此记录)/已删除(墓碑));搜索框+
生命周期过滤+分页控件在位;「索引生成」表:#8 构建失败 + 失败证据原文
(error + stage)、#7 构建完成·在服代(active_generation 权威口径)。
单文档真相端点独立验证(battery:active/serving/gen7/ver1)。截图 ×2。

**B2(#51)**:事件区真实数据渲染(§4);缺口下钻:知识缺口表「NE101 的
价格是多少?」行真实点击 → `/admin/conversations?q=NE101%20…`,**搜索框
预填 + 过滤生效 + 命中 1 条**种子未回答对话;既有 ServiceHealthBanner →
`/conversations?failure=true` 链接保持。截图 ×1。

**B3(#7)**:系统信息页「系统运行时」四组渲染——主机(真实
harrymac.local/Darwin 24.6.0 arm64/uptime 50 天)、资源(loadavg
1m/5m/15m 三值齐显【加固项可见】、磁盘 3721.9GB/33.3%)、加速器
**显式不可得 + 真实原因**(nvidia-smi 未安装 + torch CUDA 不可见)、
服务状态(/health ok + 版本 0.0.0-dev(development) + 模型运行时三
workload);独立真值比对:**kernel 24.6.0 = `uname -r` ✓;uptime 与
`kern.boottime`(7/24)一致 ✓;磁盘总量 ≈ 3.6TiB = `df -h` ✓**;刷新为
全页唯一按钮。截图 ×1。

**GPU-capable 环境:RUNTIME ACCEPTANCE BLOCKED(如实报告,不伪造)**——
本机无 NVIDIA GPU;GPU 主机走查(B3 报告 §6 脚本:利用率/显存/温度 vs
`nvidia-smi` 独立真值)按合同保留为**部署验收 gate**。

## 6. Scope Audit

- 零检索/排序/引用语义变更(组合 diff 无 retrieval/ranking/citation 文件);
- 零 lifecycle/generation 语义变更(`backend/services/*` 零 diff;只读观察面);
- 零破坏性数据源控件(新面只读;405 守卫测试加固);
- 零 TB-P1 scope(migrations/scripts/migrate_* 零触碰);
- 零 Project Automation 语义变更(PA 114 绿为既有套件);
- 零部署/零生产触碰(全程本地 dev 栈;进程已清理,后端/vite 已停);
- 加固全部为 Role A 预批清单内(§2 表),无 scope 扩大。

## 7. Unresolved Risks

1. GPU 主机 runtime 验收未执行(BLOCKED,部署 gate;脚本就绪);
2. 生产可见面核验与 #50/#51/#7 关闭 = 部署后 gate(三 Issue 已各留
   implementation-state 评论,均保持 OPEN);
3. 本地 dev 栈种子数据留在本地库(可随时 `TRUNCATE` 或重建 schema,不影响
   任何权威环境);
4. widget 子项目 tsc 噪声(缺自身 node_modules)为既有环境项,与组合树无关。

## 8. 交付物

- 组合候选:`integration/v162-20260912` @ **`9892ebb`**(基线 `0590a82`,
  4 merge/1 hardening 提交,全部已推送);
- 证据:`~/Documents/ask-ai-acceptance/v162-integration-20260912/`
  (b1-detail-inventory-buckets.png / b2-insights-incidents-drilldown.png /
  b3-system-runtime-nogpu.png);
- GitHub:#50/#51/#7 各 +1 条 implementation-state 评论(未关闭)。

---

V1.6.2 INTEGRATION = CANDIDATE READY
(就此停止,待 Role A 最终集成评审;未合并 main,未部署)
