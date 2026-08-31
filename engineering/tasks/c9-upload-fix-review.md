# C9-UPLOAD-FIX Review(独立验收,按 DUAL_AGENT_PROTOCOL 五 Gate)

- 任务:C9 文件夹上传流程修复(创建卡死 0/175 / 重复数据源 / 目录不存在空源)+ 扩展波 2 编辑流 + 波 3 默认全选
- 审查人:Planner / Reviewer(产品窗口)| 审查日期:2026-08-31
- 审查范围:波 1 `76d75e7 → d893bb1`(含搭车 949b0bc);波 2/3 `d893bb1 → 4db4c41`(a815306 + 4db4c41)
- **Final Verdict:FINAL PASS(全任务:波 1 创建流 + 波 2 编辑流 + 波 3 默认全选)**

> v2.0 协议生效后按新状态词重述:波 1 原判 PASS 视同 FINAL PASS;波 2/3 审查见文末追加节。

## 0. Baseline / Final Commit

- Baseline:`76d75e7`(main = origin/main,审查前复核一致)
- Final:`d893bb1`(main;未推送,待本次 PASS 后放行)
- 范围内提交恰好 2 个:`949b0bc`(供应商弹窗,搭车)+ `d893bb1`(本任务)

## Gate 1 — Contract Compliance:**PASS(含已记录生命周期偏差)**

本任务无 plan.md(源自用户直接 bug 报告,先于 DUAL_AGENT_PROTOCOL 正式化,执行端已如实披露并在报告追溯固化边界)。事实契约 = 用户 bug 报告三项症状 + 用户直接授权("请重新修正,并完成实际的 e2e 测试")。逐项对照:

| 契约项 | 结果 | 审查证据 |
|---|---|---|
| 创建卡死 0/175(整批 400 冻结进度) | 满足 | Gate 4/5 独立 E2E A/B 组 |
| 重复数据源(连点每点新建一源) | 满足 | B4:双击提交后 API 计数恰好 +1 |
| 空源残留(上传失败不回滚) | 满足 | A4:kept=0 回滚后 API 计数不变;B 组失败回滚为执行端 E2E 证据(25MB 超限触发) |
| 真实 e2e(用户明示前置) | 满足 | 执行端 3 项 + 审查端独立 16 项,见 Gate 4/5 |

生命周期偏差按协议属流程瑕疵非产物缺陷:边界自推导合理(仅前端上传流程),报告已按 §15 补齐,且无越界改动(见 Gate 2)。**处置:记录在案,不追溯追责;此后所有任务一律先 plan.md 后执行。**

## Gate 2 — Scope Compliance / Change Audit:**PASS**

真实 diff 审计(`git diff --stat 76d75e7..d893bb1` = 6 文件 +294/-32,全部 admin 前端,后端零改动):

| 文件 | 分类 | 说明 |
|---|---|---|
| `admin/src/utils/upload.ts`(+44) | EXPECTED | `isJunkPath` + `filterByWhitelist`,归一化逻辑与契约语义一致 |
| `admin/src/pages/DataSources.tsx`(+84/-21) | EXPECTED | 预览与提交共用同一过滤函数(无两套逻辑漂移)、失败 toast、回滚、按钮禁用 |
| `admin/tests/upload.test.ts`(+89) | EXPECTED | 10 用例 |
| `admin/src/components/ProviderCredentialDialog.tsx`(+53) | **搭车·已披露** | 949b0bc,独立缺陷(嵌入式浏览器拦截 window.prompt),与本任务文件零耦合 |
| `admin/src/pages/LLMProviders.tsx`(+19) | **搭车·已披露** | 同上,onSuccess/onError toast |
| `admin/tests/ProviderCredentialDialog.test.tsx`(+37) | **搭车·已披露** | 同上 |

- 无 UNEXPECTED production change;`useDataSources.ts` 的 `{saved}` 返回结构系基线既有,d893bb1 解构类型安全。
- 代码审查两条非阻塞备忘:①回滚分支 `deleteDs.mutateAsync` 自身失败时无兜底提示(罕见路径,留给后续统一错误处理);②无后缀文件的扩展名提取经 `lastIndexOf(".")` 返回单字符,白名单非空时恰好落入 skipped(行为正确但属巧合式正确)。
- 搭车提交处置:949b0bc 亦无 plan.md(同批次生命周期偏差),文件域不相交、披露完整、审查端已真机验证(见 C 组),随本 review 一并收编审计,**不阻断 PASS**。

## Gate 3 — Engineering Verification(独立复跑):**PASS**

- `npx vitest run`(admin 全量):**29 文件 110/110 通过**(2.36s),与执行端报告一致;
- `npx tsc --noEmit`:**exit 0**;
- 未采信执行端数字,均为审查端本机实际执行。

## Gate 4 — Runtime Verification(真实运行链路):**PASS**

审查端独立 E2E(剧本独立设计,Playwright 驱动真实 Chromium,本地栈 admin:5174 + backend:8000,夹具 = 2 有效 .md + .DS_Store + ._notes.md):

| # | 检查 | 结果 |
|---|---|---|
| A1 | 预览"已选择 4,将上传 2(跳过 2)" | PASS |
| A2 | 白名单改 .xyz → 预览"将上传 0(跳过 4)" | PASS |
| A3 | 提交 → toast"没有符合文件类型白名单的可上传文件,已回滚该数据源" | PASS |
| A4 | API 计数 7→7,无空源残留 | PASS |
| A5 | 回滚后无新建空目录 | PASS |
| B1 | 白名单自动填 `.md`(垃圾文件后缀不计入) | PASS |
| B2 | 预览 4 选 2 跳 2 | PASS |
| B3 | 连点两次提交 → 成功 toast"已上传 2/2(已跳过 2 个)" | PASS |
| B4 | 恰好新增 1 源(双击不重复) | PASS |
| B5 | 成功后表单关闭、按钮恢复 | PASS |
| B6 | 磁盘落盘恰 2 文件零垃圾 | **实质 PASS**¹ |
| C1-C3 | 供应商弹窗内联输入、零原生 dialog、创建 toast | PASS |

¹ B6 脚本断言误差:实际落盘 `docs-review/README.md`、`docs-review/nested/guide.md`(顶层文件夹名计入相对路径,与"保留嵌套结构"的后端契约一致);关键断言——恰 2 文件、零 `.DS_Store`/`._*`——成立。

**审查端补强价值**:A 组(kept=0 回滚)是执行端自报"仅单元覆盖、未做独立 E2E"的分支,本次补齐真实运行证据。

## Gate 5 — Real-World Validation:**PASS**

真实浏览器 + 真实文件上传 + 真实 API/磁盘双重核对;对抗路径含双击提交(重复源诱因)与 kept=0(空源诱因)。执行端另已覆盖服务端 400 失败回滚(25MB 超限真触发)与 150 文件上传全程按钮禁用(40ms 采样),证据采信。

## Regression Assessment

- 全量 vitest 110/110、tsc 干净;非上传路径(服务器路径模式、github 源)代码未触碰;
- 服务端整批拒收语义保留(纵深防御未削弱);
- 审查端 E2E 后环境清理:测试源/探针供应商/磁盘目录均已删,数据源终态 7 个(与执行前一致)。

## Remaining Risks / 遗留分流

1. **(执行端披露,审查端核实)后端两行为超出本任务边界**,已入 roadmap backlog 候选:
   - 上传端点批量校验前建目录 → 失败后残留目录(L2 候选);
   - 数据源 DELETE 不清理磁盘内容目录 → **产品语义待用户拍板**(不可逆删除用户数据)。审查端实证:d341da15 目录确存 **174 个文件**。
2. 网络级断连(非 4xx)回滚分支未真实演练(与 4xx 共用同一代码路径);
3. 数据侧三个空源(knowledge-0aa5b846 / 0fbd344b / ed455da8)与 d341da15 目录复用:用户持有,待处置;
4. admin 种子默认密码(既有项,继续跟踪)。

## Final Verdict

**PASS** —— 五 Gate 全过。放行推送 `949b0bc + d893bb1` 至 origin/main。

---

# 追加审查:波 2/3(编辑流 a815306 + 默认全选 4db4c41,2026-08-31 午间)

> 依据:执行报告 v4(状态 CANDIDATE READY,三波合一)。波 2/3 契约 = 用户两条产品指令(执行报告 §10/§11 追溯固化):①"编辑 filesystem 源报『目录加载失败』不合理;上传到服务器的文件夹应该显示出来让用户挑选" ②"上传后包含目录应该默认全选"。同样属先执行后补录的生命周期偏差,处置同波 1:记录在案,此后任务一律先 plan.md。

## Gate 1 — Contract Compliance(波 2/3):**PASS**

| 契约项(用户指令) | 结果 | 审查证据 |
|---|---|---|
| 编辑态展示已上传目录树可勾选 | 满足 | E1(树渲染 docs-review2(2))+ E2(勾选 checked) |
| 缺目录友好提示(不红色报错) | 满足 | G1/G2(真幽灵源 0fbd344b 灰字提示、零红色错误) |
| 编辑保存不得抹 root_path(隐藏 bug) | 满足 | E4(PATCH 后 root_path 保持,服务端权威回写) |
| 表单承诺的"再次上传合并覆盖"接通 | 满足 | F1/F3(合并 toast + 磁盘两目录并存) |
| 上传后 include_dirs 默认全选顶层 | 满足 | D2(创建流 ['docs-review2'])+ F2(再上传重算双顶层) |
| 勾选语义与同步语义不变 | 满足 | F4 同步 success items=4(与空列表=全包含语义等价,零丢失) |

## Gate 2 — Scope Compliance(波 2/3):**PASS**

`d893bb1..4db4c41` 真实 diff = 5 文件 +278/-3:后端 `data_sources.py` **+4 行**(PATCH 后 upload_mode 源强制回写 root_path)= 执行端已披露的 REQUIRED SUPPORTING CHANGE(服务端权威字段,前端无法保护;blast radius 仅 upload_mode PATCH 路径,采纳其定性);其余 4 文件(DirPicker missingHint / DataSources 编辑分支+默认全选 / 前后端测试)全部 EXPECTED。无 UNEXPECTED。代码审查无阻断项:编辑流上传失败不回滚源(源有存量内容,回滚反而毁数据——语义正确);全选回写失败不阻断主流程;全选走 updateDs 保缓存一致(E2E 现场抓到并修正的实现要点成立)。

## Gate 3 — Engineering Verification(独立复跑,波 2/3):**PASS**

- 后端:`test_data_sources_c9_edit.py + test_data_sources_c10.py` = **7 passed**(TEST_DATABASE_URL 已设,红线遵守);
- 前端:vitest 全量 **30 文件 113/113**;`tsc --noEmit` exit 0。均审查端本机实际执行,与执行端报告一致。

## Gate 4/5 — Runtime / Real-World(独立 E2E,波 2/3):**PASS**

审查端独立剧本(与执行端不同夹具与路径),本地真实栈,14 项检查全过:D1-D3 创建流(源创建/include_dirs 全选/root_path 权威)、E1-E5 编辑流(目录树+勾选+PATCH 双保持)、F1-F4 再上传(合并+重算+磁盘并存+**UI 行内同步 success items=4**)、G1-G2 幽灵源友好态。

**如实记录(审查端自身两次前提错误,非产品缺陷)**:首跑 8/14——①脚本假设 `GET /data-sources/{id}` 存在,实测该端点 405(仅 PATCH/DELETE),改列表查找后过;②G1 用 knowledge-0aa5b846 当幽灵源,实测其磁盘目录**已存在**(preview-dirs 200,含 ask-ai-local-data/* 内容),换真幽灵源 0fbd344b 复测通过。E2E 后环境清理:测试源+磁盘已删,数据源终态回到 7 个。

## 数据侧新发现(转用户)

- **knowledge-0aa5b846 不是空源**:磁盘目录存在且 config.include_dirs 已含 ask-ai-local-data/* 子树——此前"三空源"清单修正为:**真幽灵(目录缺失)= 0fbd344b / ed455da8 两个**;0aa5b846 有实内容,处置方式不同(若内容仍在用则保留)。

## 追加审查结论

**波 2/3 = FINAL PASS;C9-UPLOAD-FIX 全任务(波 1+2+3)= FINAL PASS。** 放行推送扩大至全部 4 提交:`949b0bc + d893bb1 + a815306 + 4db4c41` 至 origin/main。
