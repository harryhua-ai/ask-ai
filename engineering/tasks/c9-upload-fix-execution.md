# C9-UPLOAD-FIX Execution Report(按 DUAL_AGENT_PROTOCOL §15 重写版)

- 任务:C9 文件夹上传流程修复(创建卡死 0/175 / 重复数据源 / 目录不存在)
- 报告版本:v4(2026-08-31;v3 追加编辑流契约 §10,v4 追加"上传后默认全选"契约 §11)
- 状态:**PASS**(Executor Self-assessment;最终验收权属 Planner / Reviewer)

## 1. Baseline Commit

`76d75e7`(feat(website): C8 官网爬取数据源 web_crawl connector)

## 2. Final Commit

`d893bb1`(fix(admin): C9 上传流程客户端白名单过滤+系统文件剔除,失败 toast+空源回滚,上传中禁用创建按钮防重复源)

关联提交 `949b0bc`(供应商弹窗内联新增)为同一工作会话内另一用户报告缺陷的修复,与本任务无代码耦合,单独提交、单独归类。

## 3. Files Changed(全部 EXPECTED)

| Commit | File | 变更 |
|---|---|---|
| d893bb1 | admin/src/utils/upload.ts | +`isJunkPath`、+`filterByWhitelist` |
| d893bb1 | admin/src/pages/DataSources.tsx | 创建流程过滤/回滚/toast、预览计数、自动填白名单剔除系统文件、上传中禁用按钮 |
| d893bb1 | admin/tests/upload.test.ts | 新增 10 个单元用例 |
| 949b0bc | admin/src/components/ProviderCredentialDialog.tsx | window.prompt → 内联输入(嵌入浏览器 prompt 静默失效) |
| 949b0bc | admin/src/pages/LLMProviders.tsx | 新增供应商 onSuccess/onError toast |
| 949b0bc | admin/tests/ProviderCredentialDialog.test.tsx | 新增用例 |

后端零改动;docs/ 零提交(本地化策略)。Change Audit:两提交各 3 文件,无 UNEXPECTED production change。

## 4. Implementation Summary

根因链:前端把全部选中文件(含 `.DS_Store`)原样上传 → 后端对白名单外文件整批 400 → `uploadSourceFiles` 抛错后 `closeForm()` 不执行、`uploadProgress` 冻结 0/175、无 toast → 表单残留诱发连点 → 每点一次新建一个源(列表中 ed455da8 与 0aa5b846 创建时间差 0.8s 为实证)。

修复(HOW,Frozen Boundary=前端上传流程行为):
1. 客户端过滤:`filterByWhitelist`(后缀白名单,归一化大小写/前导点,空=全部)+ `isJunkPath`(.DS_Store/AppleDouble `._*`/Thumbs.db/desktop.ini/__MACOSX 永久剔除);
2. 失败可见:创建失败/上传失败 toast 透出后端 detail;kept=0 或上传失败 → 回滚删除刚建的源(消灭空源与重复源诱因);
3. 防连点:上传进行中创建按钮 disabled,文案"上传中 d/t…";
4. 选择即预览:"已选择 N 个,将上传 K 个(跳过 M 个…)",自动填白名单不再纳入系统文件后缀;
5. 服务端整批拒收保留(纵深防御),后端零改动。

## 5. Actual Verification(全部实际执行,无 skipped)

单元/静态:
- `admin/tests/upload.test.ts` 10/10(TDD:先红 7 failed → 后绿);
- admin 全量 vitest:29 文件 **110/110 通过**;
- `tsc --noEmit` 干净。

真实 UI E2E(Playwright 驱动 Chromium,http://localhost:5174/admin/data-sources,全程真实点击/上传):

Happy path(v1 已验):夹具 66 文件(63 .md 三层嵌套跨 50 批边界 + .DS_Store + ._report.md + logo.png),白名单手填 .md → 预览"66 选 63 传跳 3" → toast"创建成功,已上传 63/63(已跳过 3 个)" → 仅新增 1 源 knowledge-1db4e151 → 磁盘恰 63 文件 0 垃圾 → UI 点同步 success → Weaviate 63 chunks / 63 docs,路径完整。

对抗性验证(v2 补做,协议 §11):
- **重复动作/双击保护**:150 文件夹上传,40ms 采样器捕获提交按钮状态序列:`上传中 0/150…:D`、`上传中 50/150…:D`、`上传中 100/150…:D`(:D=disabled)——整个上传窗口按钮禁用,连点不可行;API 证实仅新增 1 源(knowledge-e2e-adv-5f317fb1);
- **依赖失败回滚**:夹具含 25MB 超限 .md(客户端扩展名过滤按设计放行,服务端 400 真实触发失败链)→ toast 完整透出"上传失败:文件超过 20MB 上限: huge.md,已删除该数据源,请重试" → 表单保留、按钮恢复"创建"可重试 → API 证实无新增源(回滚成功);
- **删除确认流**:UI 删除测试源经 window.confirm 确认生效。

E2E 后清理:测试源 e2e-adv 经 UI 删除;e2e-adv/e2e-b 磁盘目录已删;evidence 源 knowledge-1db4e151 留存供查看。

## 6. Acceptance Self-assessment

**PASS**(Executor 自评)。验收对照(用户指令:"请重新修正,并完成实际的 e2e 测试,在 e2e 没有通过之前,我不会手动测试"):
- 卡死 0/175 → 消灭(过滤+失败 toast)✓ 真实 UI 复验
- 重复数据源 → 消灭(上传期禁用+失败回滚)✓ 对抗 E2E 复验
- 目录不存在空源 → 不再产生(回滚)✓
- 真实 e2e → 已完成且含对抗路径 ✓

## 7. Scope / Contract Deviations

1. **生命周期偏差(如实记录)**:本任务源自用户直接 bug 报告,先于 DUAL_AGENT_PROTOCOL 正式化执行,**无 plan.md 冻结契约**,Change Boundary 由 Executor 自 derive 并在本报告追溯固化;若按新协议应 DEFINE→PLAN 后再 EXECUTE。已由用户以"请重新修正,并完成实际的 e2e 测试"直接授权范围。
2. **REQUIRED SUPPORTING 观察(未改代码,提请 Planner 决策)**:
   - 上传端点在批量校验前创建 base 目录 → 失败回滚/整批 400 后残留空目录或部分文件目录(Test B 实证:回滚后残留含 1 文件的 `knowledge-e2e-b-*` 目录);
   - 数据源 DELETE 不清理磁盘内容目录(Test A 实证:UI 删除后 150 文件目录残留;同时解释 knowledge-d341da15 孤儿目录——若用户曾 UI 删除该源,目录留存属预期)。
   两者均为后端行为,超出本任务 Boundary,未动;如需修复建议另立任务。
3. 949b0bc 为前一缺陷任务的补提交,非本任务范围扩展。

## 8. Remaining Risks

- 上传中途**网络级**断连(非服务端 4xx)的回滚分支未真实演练(仅服务端拒收路径实证);逻辑同分支,由代码评审覆盖;
- kept=0 回滚分支仅单元覆盖,未做独立 E2E(与 B 共用同一回滚代码路径);
- 数据侧遗留(遵"数据源用户自配",未动):空源 knowledge-0aa5b846 / ed455da8 / 0fbd344b 待用户处置;d341da15 目录(174 文件)无对应源,待用户确认是否曾手动删除;
- 本地 admin 种子密码 admin123 仍有效(既有安全隐患,另行跟踪)。

## 9. Execution Report Path

`docs/engineering/tasks/c9-upload-fix-execution.md`(本文件,仅本地,不进 git)

## 10. 扩展契约:编辑流(v3 追加,用户产品指令驱动)

用户指令:"编辑 filesystem 源报『目录加载失败』不合理;上传到服务器的文件夹应该显示出来让用户挑选。"

**根因(3 项,代码实证)**:
1. DirPicker 对缺失目录一律红色报错(preview-dirs 404 直出),对"从未成功上传"的源(幽灵源)无友好态;
2. **隐藏 bug:PATCH 会抹掉 root_path**——前端 buildConfig 对 upload_mode 发 `root_path: ""`,后端 update 端点整体替换 config,编辑保存即丢失同步根路径(创建时服务端强制回填,更新时没有);
3. 表单文案承诺"再次上传合并覆盖",但 onSubmit 编辑分支忽略 pickedFiles,承诺为空。

**修复(commit a815306,Baseline d893bb1)**:
- 后端 `update_data_source`:filesystem+upload_mode 源在 PATCH 后强制回写 `root_path=data/uploads/data-sources/<id>`(与创建同语义,服务端权威字段);TDD 红→绿,新测试 `tests/api/admin/test_data_sources_c9_edit.py` 2 例 + C10 回归 5 例 = 7/7;
- DirPicker 新增可选 `missingHint`:仅 404 且调用方传入时以灰字友好提示,其余错误仍红色报错(服务器路径模式需要真实报错);vitest 3 例;
- DataSources 编辑分支:接通再上传(过滤/进度/toast 与创建同一套;保存已生效,上传失败不回滚仅提示);上传模式"包含目录"文案改为"(勾选已上传内容的子目录)"并传友好提示;
- 前端全量 vitest 30 文件 113/113;tsc 干净;后端 black 仅限新增行(发现 black 波及既有无关格式后已回滚重植,diff 仅 4 行)。

**真实 UI E2E(编辑流,全程真实点击)**:
- 编辑 knowledge-1db4e151(有内容):目录树展示 `e2e-upload-fixture(2) → docs(2)、notes`,勾选顶层、另挂 2 文件夹再上传 → 保存 → 磁盘 65 文件 → 同步 success → Weaviate 65 chunks/65 docs(含 2 个新文件)→ root_path 由服务端回写保持;
- 编辑 knowledge-0aa5b846(幽灵源):**无报错**,显示"该源还没有上传过文件,上传后这里会显示服务器上的目录结构";
- 现场抓 bug:首次编辑保存时 root_path 仍被抹——原因是本地后端进程为修复前启动(无热重载);重启后 PATCH 保护生效(该过程本身证明 E2E 有真实发现能力)。

**Scope 定性**:后端 PATCH 改动为 REQUIRED SUPPORTING CHANGE——root_path 为服务端权威字段,仅靠前端无法保护;blast radius 仅 upload_mode 源的 PATCH 路径;回归证据 C10 7/7 + 真实同步 success。

## 11. 扩展契约:上传后包含目录默认全选(v4 追加,用户产品指令驱动)

用户指令:"上传的文件夹,点击保存并开始上传后,包含目录应该默认全选,而不是让用户一个一个文件夹勾选。"

**事实基础**:include_dirs 为空列表时同步语义=全部包含(knowledge-1db4e151 以空列表同步出全量 63 docs 为证);但勾选框界面把"空"渲染成"全不选",用户无法区分"全不包含"与"全部包含"。

**修复(commit 4db4c41,Baseline a815306,纯前端)**:
- 上传成功(创建流与编辑再上传流均适用)后,拉取上传根目录顶层子目录全集,写入 config.include_dirs(即"全部顶层目录已勾选"),toast 追加"已默认包含全部 N 个目录";
- 再上传时重算全集,勾选状态始终与当前服务器内容一致;目录回写失败不阻断上传主流程;
- **实现要点**:创建流的回写必须走 updateDs(内含 react-query 缓存失效)而非裸 apiFetch——否则列表缓存仍旧,用户立刻点编辑时表单预填不到 include_dirs,勾选框仍显示未选(E2E 现场抓到此问题并修正)。

**验证**:
- 真实 UI E2E 创建流:新源上传 8 文件(含 alpha/beta 子目录)→ config.include_dirs=['e2e-allsel'](顶层目录全集)→ 编辑打开该源,顶层勾选框为 checked ✓;
- 真实 UI E2E 编辑流:1db4e151 再上传新文件夹 → include_dirs 重算为全部 3 个顶层目录 ['e2e-edit-add','e2e-edit-add2','e2e-upload-fixture'] → root_path 保持 → 同步 success → Weaviate 67 chunks/67 docs,覆盖与空列表语义完全等价(零丢失);
- tsc 干净;vitest 30 文件 113/113;测试产物已清理(allsel 源 UI 删除+磁盘清理)。

**Scope 定性**:纯前端数据流修复,未动后端;勾选语义(勾=包含,父目录覆盖子树)与同步语义未变。

---

最终状态(Executor Self-assessment):**PASS**(v1 创建流 + v3 编辑流 + v4 默认全选)
最终验收:待 Planner / Reviewer 独立审查(创建流 76d75e7→d893bb1;编辑流 d893bb1→a815306;默认全选 a815306→4db4c41)后出具 review.md。
