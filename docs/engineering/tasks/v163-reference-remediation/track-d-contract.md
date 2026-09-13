# Track D Contract — B2 原因分类学扩展(GAP-B2-1 + GAP-B1-2)

- **目标**:矩阵 TI-09、DS-P2-10 清零。
- **参考需求**:TI-09(原因词表:知识缺失/服务知识不完整/内容过期/检索异常/生成异常/引用异常/内容冲突/内容缺失)、DS-P2-10(banner 原因句含「引用需要重新验证」类)。
- **产品语义**:原因分类是诊断结论的唯一真相;每个 depicted 原因词必须有会话级权威证据规则;扩展仅限参考词表,不再发明。
- **变更边界**:前端 Analytics.tsx(GAP_CAUSE_OPTIONS/徽章 tone)、DataSourceDetail banner 文案映射;后端 `backend/api/admin/analytics.py` classify_gap_miss_types 扩展、tech.py 投影透传;不改既有 4 类(reject/low/召回空/召回不足)语义。
- **后端数据要求**:新分类判定规则(内容过期=内容时间真相;检索异常=检索异常证据;生成异常=generation failure 真相;引用异常=引用一致性;内容冲突=多源冲突真相;内容缺失=知识缺失变体)——规则冻结稿随合同交付;必要时分类结果落列以保稳定。
- **前端要求**:filter 选项=权威全集+未分类;chips tone 语义着色;data-gap-type 机器值恒存。
- **禁止捷径**:禁止前端自造分类或映射到近义词;禁止无证据规则的分类上线;旧 4 类回归零破坏。
- **验收**:每个新词至少 1 行真实分类证据(fixture 构造经真实 DB→API→UI);旧 4 类+未分类回归;pytest+vitest。
- **运行时状态**:本地栈复核队列 chips/filter/banner 文案。
- **视觉证据**:队列原因列全词表截图。
- **功能 E2E**:按新原因过滤→行集=该分类权威行集;点开诊断详情分布一致。
- **交付物**:分支 `track/v163-d-taxonomy`、分类规则冻结稿、执行报告、截图、测试日志。
- **前置**:U-14 User 决定;**先于 Track E**(观察核验依赖分类稳定);tech.py 与 E/F 共享→合并序 D→E→F。
