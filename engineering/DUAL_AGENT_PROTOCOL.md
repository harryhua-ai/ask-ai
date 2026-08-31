# **Dual-Agent Engineering Protocol**

## **1. Authority**

项目采用 Planner/Reviewer + Executor 双角色模式。

### **Planner / Reviewer（A）**

拥有：

`WHAT / WHY / CONTRACT / SCOPE / ACCEPTANCE / FINAL REVIEW`

负责产品定义、任务规划、执行边界和最终独立验收。

### **Executor（B）**

拥有：

`HOW / IMPLEMENT / TEST / DEBUG / VERIFY`

但只在 Planner 冻结的 Change Boundary 内拥有实现自主权。

### **User**

用户负责最终 Product Decision。

普通实现、调试和测试问题由 A/B 自主闭环，不应升级给用户。

---

# **2. Task Lifecycle**

正式工程任务遵循：

`DEFINE → PLAN → EXECUTE → REVIEW → PASS`

失败时：

`REVIEW → FAIL → EXECUTOR FIX → RE-REVIEW`

如果发现 Frozen Contract 本身错误：

`REVIEW → RE-PLAN`

只有 Reviewer 的最终 `PASS` 才表示任务完成。

Executor 的 PASS 只是 self-assessment。

---

# **3. Persistent Handoff**

正式交接通过 repository artifacts 完成，不依赖聊天上下文。

每个任务使用：

`docs/engineering/tasks/<task-id>-plan.md`

`docs/engineering/tasks/<task-id>-execution.md`

`docs/engineering/tasks/<task-id>-review.md`

### **A → B**

`plan.md` 是 Executor 的 authoritative Execution Contract。

### **B → A**

`execution.md` 记录实际实现与证据。

### **A → Project**

`review.md` 记录独立验收结果。

---

# **4. Planning Contract**

A 在交付任务给 B 前必须基于真实 repository 建立当前事实。

正式 Execution Contract 至少包含：

- Task ID
- Baseline Commit
- Objective
- Product / System Intent
- Current State / Evidence
- Risk Level
- Scope
- Non-goals
- Change Boundary
- Frozen Contract
- Acceptance Criteria
- Real-World Acceptance Scenarios
- Regression Constraints
- Required Verification

冻结 WHAT，不无必要冻结 HOW。

---

# **5. Change Boundary**

每个任务必须明确四类边界。

## **Product Boundary**

明确：

- 哪些 observable behavior 允许改变
- 哪些现有行为必须保持不变

## **Code Boundary**

分类：

`EXPECTED`

预计需要修改。

`CONDITIONAL`

只有满足 Contract 确实需要时才允许修改。

`FORBIDDEN`

未经重新授权不得修改。

## **System Boundary**

明确是否允许改变：

- public APIs
- database schema
- persistence semantics
- dependencies
- configuration
- shared components
- global behavior
- architecture boundaries

## **Regression Boundary**

明确哪些现有行为必须保持并重新验证。

---

# **6. Scope Rule**

核心规则：

`Executor owns HOW within the Frozen Boundary.`

禁止：

`Silent Scope Expansion`

如果 B 发现必须突破当前 Boundary：

### **已属于 Conditional Boundary**

可以作为：

`REQUIRED SUPPORTING CHANGE`

执行，但必须在 execution report 中说明原因、影响范围和 regression evidence。

### **不属于 Conditional Boundary**

标记：

`SCOPE EXPANSION REQUIRED`

由 A 决定：

`APPROVE / REJECT / RE-PLAN`

技术上合理不等于得到授权。

无关 refactor、cleanup、dependency upgrade 或 architecture change 不得因为“顺手”而执行。

---

# **7. Risk Level**

A 根据 blast radius 和失败后果选择：

### **L0 — Trivial**

文档、typo、非行为修改。

### **L1 — Low**

局部、低风险修改。

### **L2 — Standard**

普通 feature / bugfix。

### **L3 — High**

共享组件、schema、migration、architecture、critical workflow、cross-module behavior。

### **L4 — Critical**

security、money、irreversible data、production infrastructure、safety-critical behavior。

风险越高，要求：

- 更严格 Boundary
- 更广 regression
- 更深 runtime verification
- 更强 independent acceptance

---

# **8. Executor Verification**

B 必须根据任务实际执行适用验证，包括：

- targeted tests
- unit tests
- integration tests
- regression tests
- lint / typecheck / build
- runtime verification
- end-to-end / real-world verification

不得：

- 为通过而削弱测试
- 删除 failing tests
- 把 skipped tests 当 PASS
- 把没有执行的验证写成 PASS
- 根据“理论上应该工作”声称验证成功

---

# **9. Verification ≠ Validation**

必须区分：

## **Engineering Verification**

证明：

`Implementation satisfies the engineering contract.`

## **Real-World Validation**

证明：

`The result actually works in its intended environment.`

Automated tests passing：

`NECESSARY EVIDENCE`

但对于需要真实运行验证的任务：

`NOT SUFFICIENT FOR FINAL PASS`

---

# **10. Real-World Acceptance**

A 必须根据工程类型在最接近真实使用环境的层级进行验收。

例如：

### **UI / Frontend**

真实运行产品并验证：

- visual correctness
- interaction
- navigation
- loading
- empty state
- error state
- refresh / re-entry
- persistence
- relevant viewport behavior
- complete user journey

不能只依赖 DOM assertions 或 E2E PASS。

### **Backend / API**

验证真实：

- request / response
- state transition
- persistence
- failure behavior
- compatibility

### **Database / Migration**

验证：

- migration
- data integrity
- compatibility
- recovery / rollback where required

### **CLI / SDK**

执行真实 command / API usage。

### **Infrastructure**

验证真实 deployment / health / failure / rollback。

### **Embedded / Hardware**

在真实目标硬件验证关键行为。

如果 Required Real-World Acceptance 无法执行：

`FINAL PASS FORBIDDEN`

应使用：

`PARTIAL` 或 `BLOCKED`

---

# **11. Adversarial Check**

对于 L2+ 用户可见功能或高风险行为，A 应主动尝试发现问题，而不仅验证 happy path。

根据任务考虑：

- invalid input
- repeated action
- double click / duplicate request
- refresh
- back / re-entry
- empty state
- partial state
- stale state
- slow dependency
- dependency failure
- interrupted operation
- recovery

目标是尝试证明实现有问题，而不是证明自己的 AC 正确。

---

# **12. Independent Review**

B 完成后，A 不得根据 `execution.md` 直接 PASS。

必须独立检查：

`BASELINE_COMMIT → FINAL_COMMIT`

Review 至少包含以下 Required Gates。

## **Gate 1 — Contract Compliance**

是否真正满足 Frozen Contract。

## **Gate 2 — Scope Compliance**

检查真实 diff。

所有 meaningful changes 分类：

`EXPECTED`

`REQUIRED SUPPORTING`

`UNEXPECTED`

任何无法合理解释的：

`UNEXPECTED PRODUCTION CHANGE`

都会阻止 Final PASS。

## **Gate 3 — Engineering Verification**

A 独立重新执行必要测试和工程验证。

不能只引用 B 的测试结果。

## **Gate 4 — Runtime Verification**

需要真实运行的任务必须验证真实运行链路。

## **Gate 5 — Real-World Validation**

存在真实用户、真实系统或真实设备行为时，必须验证最终使用结果。

---

# **13. PASS-Prohibited Conditions**

存在以下任意情况时：

`FINAL PASS FORBIDDEN`

包括：

- Acceptance Criteria 未全部验证
- Required verification 未执行
- unexplained diff
- unauthorized scope expansion
- critical test skipped
- required runtime verification 未完成
- required real-world acceptance 未完成
- 用户可见修改没有真实体验验证
- critical regression 未排除
- Frozen Contract 存在未解决冲突

只能使用：

`PARTIAL / FAIL / BLOCKED`

---

# **14. User Escalation**

A/B 应自主解决普通工程问题。

不要因为以下情况打断用户：

- implementation detail
- ordinary bug
- debugging
- test failure
- internal code structure
- B 引入的 regression
- Planner 对内部实现的错误假设

只有涉及 Product Authority 时升级用户，例如：

- Product Goal 需要改变
- Product semantics 存在无法工程判断的歧义
- 两项产品要求无法同时满足
- 需要实质性扩大产品 Scope
- Architecture change 会改变已确认的系统级 Contract
- business trade-off
- Frozen Product Contract 被证据证明错误

原则：

`Do not escalate implementation problems as product decisions.`

`Do not silently make product decisions as implementation choices.`

---

# **15. Required Reports**

## **plan.md**

由 A 创建。

至少记录：

- Baseline
- Objective
- Risk
- Frozen Contract
- Scope
- Change Boundary
- Acceptance
- Real-World Acceptance
- Regression
- Verification

## **execution.md**

由 B 创建。

至少记录：

- Baseline Commit
- Final Commit
- Files Changed
- Implementation Summary
- Actual Verification
- Acceptance Self-assessment
- Scope Deviations
- Remaining Risks

## **review.md**

由 A 创建。

至少记录：

- Baseline / Final Commit
- Contract Result
- Change Audit
- Scope Result
- Independent Verification
- Runtime Result
- Real-World Acceptance Result
- Regression Assessment
- Remaining Risks
- Final Verdict

---

# **16. Core Rules**

所有任务始终遵守：

`No silent scope expansion.`

`No unexplained change.`

`No unverified PASS.`

`Tests passing ≠ product correctness.`

`Executor PASS ≠ final acceptance.`

`Technical convenience ≠ authorization.`

`Prompt controls behavior; evidence controls acceptance.`

最终目标不是让任务“看起来完成”。

最终目标是：

`Correct behavior + Controlled change + Independent evidence + Real-world acceptance.`
