# I-UX-001 — Widget Experience Implementation Contract

Status: AUTHORIZED FROZEN IMPLEMENTATION CONTRACT
Repository: `harryhua-ai/ask-ai`
Product contract: `docs/engineering/tasks/I-UX-001-WIDGET-EXPERIENCE-plan.md`
Product contract commit: `9ba8aff9da19b7f5106a615bac05df496e9e174e`
Implementation branch source: `plan/i-ux-001-widget-experience`
Accepted production ancestor: `26de2b6e4b713e0e23ebf80fecfd6b045adeff66`

## 1. Objective

Implement the frozen I-UX-001 product contract: evolve the current passive launcher/full-height drawer into a configurable, contextual, trustworthy Widget experience covering discovery, proactive engagement, Mini Conversation Entry, Floating Chat, site-adaptive theme, Trusted Actions and Admin live preview.

B owns implementation HOW, engineering investigation, code-level design, migrations, test design and debugging inside this frozen contract.

B MUST NOT silently change product semantics, migration policy, acceptance, scope or non-goals.

## 2. Authoritative Product Semantics

The complete Product/UX semantics are frozen in:

`docs/engineering/tasks/I-UX-001-WIDGET-EXPERIENCE-plan.md`

The executor MUST read that file in full before planning implementation.

Key frozen requirements include:

- A/B/C entry modes all supported.
- NEW sites default to C — Mini Conversation Entry.
- Existing legacy sites without explicit presentation configuration preserve their existing entry behavior.
- Desktop default: compact launcher first, delayed C expansion at Balanced ≈ 6s, once per site session, no idle auto-collapse.
- Mobile default proactive state is B, not full C.
- C contains one-line contextual greeting + max 2 Trusted Actions + direct input.
- Trusted Action click or C text submit immediately starts a real ASK-AI request while the same bottom-right surface expands into Floating Chat.
- Desktop full chat becomes a floating bottom-right surface rather than the current full-height drawer.
- Inline citations remain; duplicate visitor-facing Sources inventory is removed by default.
- Contextual greeting is deterministic, confidence-bounded, page-aware, not person-aware, and adds zero LLM calls.
- Trusted Actions use controlled semantic identities and `DRAFT → TEST → VERIFIED → PUBLISHED` lifecycle.
- Trusted Action Test must execute real ASK-AI and expose real Answer + Citations/Evidence to Admin.
- Only VERIFIED + PUBLISHED actions are eligible for proactive display.
- Chat theme supports Match Website / Light / Dark / Custom; Match Website derives safe signals and ASK-AI-owned theme tokens rather than inheriting arbitrary host CSS.
- Launcher branding remains independently configurable; default launcher remains ASK-AI-branded for discoverability.
- Launcher size supports Small / Medium / Large.
- Admin uses the real Widget rendering path for Desktop/Mobile preview and engagement-context simulation where practical.
- Accessibility, reduced-motion, host-page isolation and current functional capabilities must not regress.

## 3. Baseline Gate

The execution worktree MUST be created from the commit containing this implementation contract on `plan/i-ux-001-widget-experience`.

Before editing production code, B MUST:

1. confirm the exact worktree HEAD;
2. confirm `26de2b6e4b713e0e23ebf80fecfd6b045adeff66` is an ancestor;
3. inspect whether any later accepted engineering changes relevant to Widget/Admin/site-config must be integrated;
4. record the result in the execution report.

At contract formation time GitHub `main` was known to lag accepted production at `fbbf6530935d917c7729c58e2c4c9f6e109ebb70`; therefore do not replace this baseline with `main` merely because it is the default branch.

Routine non-conflicting baseline integration is B-owned HOW. A material product-semantic conflict is a BLOCKER / `SCOPE EXPANSION REQUIRED`.

## 4. Required Scope

Implement the smallest coherent architecture that satisfies the frozen product contract across the existing Widget + Admin + required supporting config/persistence surfaces.

Expected product surfaces:

- Widget entry/presentation state model
- A/B/C renderings
- proactive timing/session behavior
- launcher motion and size presets
- C Mini Conversation Entry
- C → Floating Chat transition
- desktop floating panel
- mobile responsive behavior
- contextual greeting resolution
- Trusted Action semantic catalog/config/lifecycle
- real ASK-AI Trusted Action test flow
- site-adaptive theme resolution/tokens
- visitor evidence presentation cleanup
- Admin Widget Experience controls
- real Widget live preview
- i18n/config/API/schema support required by the above

B decides exact component boundaries, state management, schemas, migration mechanics and testing approach.

## 5. Migration Contract

Do not silently make proactive C the default for existing legacy sites that lack explicit presentation configuration.

Required semantics:

- existing legacy site + no explicit presentation config → preserve legacy entry behavior;
- new site → C default;
- explicit Admin/site/embed config → authoritative;
- floating-chat redesign and other globally accepted Widget improvements may apply as required by the Product Contract, but proactive-entry migration policy above must hold.

Migration/fallback behavior must be deterministic and test-covered.

## 6. Trusted Actions Contract

Initial controlled semantic catalog may include:

- PRODUCT_SPECIFICATIONS
- SETUP_GUIDE
- EXPLAIN_PAGE
- TROUBLESHOOT
- FIND_DOCUMENTATION
- COMPARE_PRODUCTS
- COMPATIBILITY
- PRICING

Initial recommended published defaults:

- Product page: Specifications + Setup guide
- Documentation page: Explain this page + Troubleshoot

Constraints:

- C max visible = 2
- empty full chat max visible = 3
- PRICING is not universally default-published
- COMPARE_PRODUCTS is not universally default-published unless the accepted comparison behavior is present and reliable
- no unrestricted LLM-generated proactive actions
- no new LLM call for greeting/action generation

Semantic changes invalidate verification; presentation-only label changes need not.

Do not implement source-aware automatic verification invalidation in this increment.

## 7. Evidence UX Contract

Visitor-facing answer rendering MUST preserve actionable inline citations while removing redundant default source inventory beneath the answer.

Do not weaken evidence traceability.

Do not remove complete source data from Admin/Debug/Evaluation surfaces merely to simplify visitor UX.

## 8. Theme Contract

Required modes:

- Match Website (default)
- Light
- Dark
- Custom

Match Website must resolve safe host signals into ASK-AI-owned theme tokens. Do not import arbitrary host styles or allow CSS leakage.

Preserve readable contrast and focus visibility.

## 9. Accessibility / Interaction Contract

Preserve existing semantic launcher button behavior and improve the new states as needed.

Required behavior includes:

- keyboard operability
- accessible names
- appropriate dialog semantics for full chat
- visible focus
- sensible focus transfer/restoration
- Escape close where appropriate
- reduced-motion behavior
- no unreachable input/controls

## 10. Hard Non-goals

Do NOT expand this increment into:

- Answer Intelligence redesign
- retrieval/reranker/embedding changes
- EvidencePlan or claim-evidence validation changes
- ResponseStrategy changes
- LLM/model/provider changes
- new LLM calls for engagement copy/actions
- CRM/person-aware visitor identity
- lead qualification / meeting scheduling
- voice/video/avatar
- new analytics architecture
- new evaluator architecture
- full Pinned Agent mode
- custom CSS editor
- arbitrary animation designer
- new contextual Answer Action Engine
- production deployment
- benchmark rerun solely for this UI increment

## 11. Verification Requirements

B must use RED/GREEN discipline for new behavior where practical and run actual verification, not code inspection only.

At minimum run and report:

- relevant Widget unit/component tests
- Admin/config/persistence tests
- integration tests for site-config / Trusted Action lifecycle
- typecheck
- build
- lint where applicable
- relevant existing regression suites
- browser-rendered visual verification

Verify modern Chromium and at least practical WebKit/Safari + Firefox coverage where the repository harness allows it, plus desktop/mobile responsive states.

Required visual evidence is enumerated in the Product Contract and must include A/B/C, delayed C, high-confidence/fallback greeting, C→Floating Chat, active conversation, no duplicate Sources section, light/dark/Match Website, launcher sizes, and mobile B/open chat.

## 12. Acceptance Invariants

Candidate is not ready unless all are proven:

- A/B/C configurable
- new-site C default
- legacy-site entry preservation
- desktop delayed C expansion once/session
- no idle auto-collapse by default
- user minimize/dismiss respected
- mobile defaults to B proactive state
- C Action/input starts real request immediately
- floating desktop chat remains bottom-right anchored
- cold-start actions disappear after conversation start
- inline citations remain actionable
- duplicate default Sources section absent
- deterministic safe greeting fallback
- SPA context update without repeated proactive expansion
- theme modes functional
- launcher size presets functional
- only VERIFIED + PUBLISHED Trusted Actions proactively visible
- Test uses real ASK-AI output/evidence
- Admin live preview reflects actual Widget config/context
- existing streaming/attachments/feedback/site-config/language/pageContext/citations/embed behavior does not regress
- first-visible launcher appearance correctness does not regress
- no host layout reflow or CSS leakage

## 13. Delivery

Execution report:

`docs/engineering/tasks/I-UX-001-WIDGET-EXPERIENCE-execution.md`

Report must include:

- baseline/worktree evidence
- changed files
- implementation architecture summary
- actual test commands/results
- visual/browser artifacts
- acceptance matrix
- scope audit
- known limitations/risks
- final commit hash

Use clean selective staging; do not use `git add -A`.

Executor status must be one of:

- CANDIDATE READY
- PARTIAL
- FAIL
- BLOCKED

B does not grant FINAL PASS. Final Product/Engineering acceptance belongs to A after independent review.
