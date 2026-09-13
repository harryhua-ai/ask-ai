# Track D Contract — B2 原因分类学扩展(GAP-B2-1 + GAP-B1-2)(Planning 终轮 review fix 修订:Wave 0A/0B + PREP_BASE_SHA + D/E 依赖合同 §3.6)

- **目标**:矩阵 TI-09、DS-P2-10 清零。
- **参考需求(精确 ID)**:TI-09(原因词表:知识缺失/服务知识不完整/内容过期/检索异常/生成异常/引用异常/内容冲突/内容缺失)、DS-P2-10(banner 原因句含「引用需要重新验证」类)。
- **冻结产品语义**:U-14:**实现参考要求的扩展词表;每类需证据规则;禁止 keyword-only 前端分类**。原因分类是诊断结论的唯一真相;每个 depicted 原因词必须有会话级权威证据规则;扩展仅限参考词表,不再发明。
- **权威数据源**:会话级证据真相(内容时间/检索异常/生成失败/引用一致性/多源冲突);分类结果必要时落列以保稳定。
- **变更边界**:前端 Analytics 拆分后原因面板文件(IF-6;拆分前不得与他人冲突)、DataSourceDetail banner 文案映射;后端 `backend/api/admin/analytics.py` classify_gap_miss_types 扩展、独立词表常量模块(IF-2:gap_taxonomy.py,投影/前端引用同一常量)、tech_answer_gaps.py 投影透传;不改既有 4 类(reject/low/召回空/召回不足)语义。
- **后端数据要求**:新分类判定规则(内容过期=内容时间真相;检索异常=检索异常证据;生成异常=generation failure 真相;引用异常=引用一致性;内容冲突=多源冲突真相;内容缺失=知识缺失变体)——规则冻结稿(IF-2)随合同交付。
- **前端行为**:filter 选项=权威全集+未分类;chips tone 语义着色;data-gap-type 机器值恒存。
- **运行时状态要求**:本地栈复核队列 chips/filter/banner 文案;分类证据可经真实 DB→API→UI 回放。
- **视觉证据**:队列原因列全词表截图(1536×1024 @1x)。
- **功能 E2E**:按新原因过滤→行集=该分类权威行集;点开诊断详情分布一致。
- **禁止捷径**:keyword-only 前端分类(无证据合同);前端自造分类或映射到近义词;无证据规则的分类上线;hard-coded 词表字面量复制(必须引用 IF-2 常量);旧 4 类回归零破坏。
- **验收**:每个新词至少 1 行真实分类证据(fixture 构造经真实 DB→API→UI);旧 4 类+未分类回归;pytest+vitest。
- **交付物**:分支 `track/v163-d-taxonomy`、分类规则冻结稿(IF-2)、执行报告、截图、测试日志、fixture SQL 全文。
- **前置**:Wave 0A(IF-2 冻结)+ Wave 0B 完成;**从 PREP_BASE_SHA 分支(强制共同基线,禁止混合基线,remediation plan §3.0.2)**;可立即(Wave 1)。**D/E 依赖(§3.6,冻结):实现依赖 D→E = NONE——本轨不阻塞 Track E 开工,E 依 IF-2 冻结合同并行实现;但 D candidate(本分支 IF-2 实际实现达验收就绪)是 Track E joined runtime FINAL PASS 的前置,E 须对 D 实际词表实现联测——故 D candidate 必须及时移交**。backend 合并序推荐 D→E→F(拆分到位后冲突面趋零)。
- **Issue 映射**:落地后关闭 #59 原因词表/分布部分、贡献 #54 banner 部分。
- **B 级提示词要点**:worktree=实现授权树;**分支基线=PREP_BASE_SHA**;branch `track/v163-d-taxonomy`;冻结合同=本文件+IF-2+remediation plan §3.6 D/E 依赖合同+§6 授权包;范围=U-14 六新类+证据规则;验收=逐类证据+回归+candidate 及时移交 E joined 联测;交付物含 IF-2 冻结稿与 fixture SQL 全文。
