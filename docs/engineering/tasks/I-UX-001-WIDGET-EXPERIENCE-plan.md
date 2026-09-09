# I-UX-001 — Widget Discovery → Contextual Engagement → Trusted Conversation

Status: FROZEN PRODUCT CONTRACT
Authority: Product / UX
Planning branch: `plan/i-ux-001-widget-experience`
Planning anchor: `26de2b6e4b713e0e23ebf80fecfd6b045adeff66`

> Important: the planning anchor is the accepted v1.2.1 production corrective commit. GitHub `main` was still observed on `fbbf6530935d917c7729c58e2c4c9f6e109ebb70`. The executor MUST reconcile the authoritative implementation baseline before changing code. This document freezes product semantics; it does not authorize treating stale `main` as the implementation baseline.

## 1. Objective

Transform ASK-AI from a passive traditional website chatbot into a contextual, trustworthy, high-discoverability AI assistant.

Target journey:

`Page visit → discover ASK-AI → understand what it can help with → one interaction starts a real conversation → receive a trustworthy, citable answer → continue naturally.`

Principle:

`HIGH DISCOVERABILITY + LOW ANNOYANCE + TRUSTED FIRST VALUE`

This is not a generic visual refresh and not an Answer Intelligence redesign.

## 2. Frozen Product Decisions

### 2.1 Entry presentation modes

ASK-AI SHALL support all three entry presentation modes:

- `A — MINIMAL_PILL`: minimal textual Ask AI entry.
- `B — CONTEXTUAL_NUDGE`: lightweight page-aware nudge such as `Questions about NE503?`.
- `C — MINI_CONVERSATION_ENTRY`: compact interactive surface with contextual greeting, trusted actions and direct input.

Default for NEW sites:

`C — MINI_CONVERSATION_ENTRY`

Existing legacy sites without explicit presentation configuration SHALL preserve their existing entry behavior after upgrade. Admin configuration is always authoritative. Existing sites may explicitly opt into C.

### 2.2 Desktop proactive expansion

Default NEW-site desktop lifecycle:

1. Widget/page becomes ready.
2. Compact launcher appears first.
3. After approximately 6 seconds, C auto-expands.
4. C remains visible until explicit user action.

Frozen defaults:

- Auto-expand: ON
- Timing preset: Balanced ≈ 6 seconds
- Auto-collapse: OFF
- Repeated proactive expansion: NO; once per site session
- User minimize/dismissal SHALL be respected for the remainder of that session.

The full chat panel SHALL NOT auto-open merely because the page loaded.

### 2.3 Mobile proactive behavior

Mobile SHALL NOT default to auto-expanding full C.

Default mobile proactive presentation:

`B — CONTEXTUAL_NUDGE`

Full mobile chat opens only after explicit user interaction.

### 2.4 Launcher identity, motion and size

Launcher icon identity and motion are independent configuration dimensions.

Motion presets SHALL include at least:

- Static
- Subtle Glow
- Soft Pulse
- Sparkle

Default motion: `Subtle Glow`.

Motion is an attention cue, not permanent decorative animation. First implementation SHOULD prefer SVG + CSS motion rather than GIF. `prefers-reduced-motion` SHALL preserve state semantics while removing unnecessary decorative motion.

Launcher size SHALL be configurable by safe presets:

- Small
- Medium
- Large

Default: `Medium`.

Ordinary Admin configuration does not need arbitrary pixel-level geometry. Internal glyph sizing should scale proportionally.

### 2.5 C — Mini Conversation Entry

Desktop design target:

- Width ≈ 340 px
- Height ≈ 180–210 px
- Bottom-right anchored
- Approx. 24 px page offsets on ordinary desktop layout

These are design targets, not mandatory implementation constants.

C SHALL remain compact. Its default information architecture is:

1. ASK-AI identity / minimal header
2. One-line contextual greeting
3. Maximum 2 Trusted Actions
4. Direct text input
5. Minimize / Not-now control

C SHALL NOT contain long AI introductions, page summaries, large welcome copy, or large starter inventories.

### 2.6 C → Floating Chat

A Trusted Action click or direct input submission from C SHALL start the real conversation immediately.

Required interaction:

`C → same bottom-right anchor → smooth expansion → Floating Chat → real request/stream starts immediately`

The user MUST NOT need an additional click after selecting a Trusted Action or submitting text.

The transition should feel like the same surface growing, not a separate unrelated window appearing elsewhere.

### 2.7 Floating Chat

Desktop design target:

- Width ≈ 420 px
- Height ≈ 640 px
- Max height ≈ 80–85 vh
- Bottom-right anchored

The current full-height right-side drawer behavior SHALL be replaced for desktop by a floating chat surface.

Motion SHOULD use a restrained shell morph / resize / fade in roughly the 220–280 ms class. Avoid aggressive bouncing, overshoot, flashing or promotional popup behavior.

Reduced-motion mode may use instant or minimal-fade state changes.

### 2.8 Cold start vs active conversation

Cold-start states may show contextual greeting and Trusted Actions.

Once a real conversation starts:

- cold-start greeting disappears;
- starter/Trusted Action chips disappear from the persistent conversation surface;
- the chat becomes message-first.

Full-chat header SHOULD remain minimal, e.g. ASK-AI identity plus necessary minimize/close controls.

### 2.9 Evidence presentation

Visitor-facing Widget:

- Inline citations remain visible and actionable.
- A separate default `Sources` section SHALL NOT be rendered when answer citations already expose the evidence path.
- Do not duplicate cited source titles/cards underneath every answer by default.
- Clicking a citation should reveal/open the corresponding source or evidence context as supported by the current product.

Complete source inventories remain appropriate for Admin / Debug / Evaluation / explicit user demand.

Principle:

`Evidence remains verifiable without becoming duplicate UI.`

### 2.10 Contextual greeting

I-UX-001 contextual greeting SHALL be deterministic and SHALL NOT add new LLM calls.

Authority order:

1. explicit Site/Admin override;
2. trusted Page Context;
3. safe page-type template;
4. generic fallback.

Confidence degradation:

- HIGH: product-specific wording, e.g. `Questions about NE503?`
- MEDIUM: category wording, e.g. `Questions about this product?`
- LOW/unknown: generic wording, e.g. `How can I help?`

Frozen principle:

`Wrong-specific is worse than correct-generic.`

Suggested deterministic templates include:

- Product: `Questions about {product}?`
- Documentation: `Questions about this guide?`
- Integration: `Need help with this integration?`
- Support: `Need help troubleshooting?`
- Pricing: `Questions about pricing or plans?`
- Comparison: `Need help comparing these options?`
- Unknown: `How can I help?`

Greeting resolution and Trusted Action selection SHALL derive from the same resolved engagement/page context.

### 2.11 SPA context behavior

SPA/page context updates may update:

- product/page context;
- contextual greeting;
- eligible Trusted Actions.

SPA navigation SHALL NOT trigger repeated proactive expansion in the same site session.

Once an active conversation has started, existing conversation content must not be retroactively rewritten due to navigation.

### 2.12 Page-aware, not person-aware

This increment is page-aware, not visitor-identity-aware.

Out of scope:

- CRM identity
- personal-name greeting
- lead identity
- email campaign continuity
- behavioral/person-level targeting

### 2.13 Trusted Actions

A Trusted Action is a controlled semantic capability that ASK-AI is allowed to proactively recommend only after it has been validated against the real system.

Trusted Actions are NOT arbitrary LLM-generated questions.

Initial controlled semantic catalog may include:

- `PRODUCT_SPECIFICATIONS`
- `SETUP_GUIDE`
- `EXPLAIN_PAGE`
- `TROUBLESHOOT`
- `FIND_DOCUMENTATION`
- `COMPARE_PRODUCTS`
- `COMPATIBILITY`
- `PRICING`

Initial recommended defaults:

Product page:

- Specifications
- Setup guide

Documentation page:

- Explain this page
- Troubleshoot

C displays at most 2 Trusted Actions. Empty full chat may display at most 3.

`PRICING` SHALL NOT be default-published unless the Site can establish sufficiently authoritative/current pricing truth.

`COMPARE_PRODUCTS` must not be treated as a universal default until comparison behavior is reliable under the accepted Comparison Gate contract.

### 2.14 Trusted Action semantics

Semantic identity SHALL be distinct from display wording and localization.

Example:

- Semantic action: `PRODUCT_SPECIFICATIONS`
- English label: `Specifications`
- Chinese label: `产品规格`

Current page/product context binds the semantic action to the active object.

I-UX-001 may select/rank from VERIFIED + PUBLISHED actions based on reliable context, but SHALL NOT use unrestricted LLM generation of proactive actions.

### 2.15 Trusted Action lifecycle

Admin lifecycle:

`DRAFT → TEST → VERIFIED → PUBLISHED`

Persisted semantic states may be:

- DRAFT
- VERIFIED
- PUBLISHED

Rules:

- DRAFT: production-ineligible
- VERIFIED: answer/evidence manually accepted
- PUBLISHED: eligible for proactive Widget exposure

Testing MUST execute the real ASK-AI request path and show the actual Answer + Citations/Evidence to Admin. No fake answer preview or simple retrieval-presence check is sufficient.

First implementation uses real ASK-AI output + human approval. Automated evaluator gating is not required for I-UX-001.

Semantic changes to action intent/query/scope/applicability invalidate prior verification. Pure display-label/presentation changes do not necessarily invalidate semantic verification.

Knowledge refreshes SHALL NOT automatically invalidate every action in I-UX-001. Admin may see last-verified metadata and use `Test again`. More precise source-aware invalidation belongs to later Evidence Governance work.

### 2.16 Admin Widget Experience

Admin SHALL expose a focused high-level Widget Experience surface, not a CSS editor.

Required groups:

Entry:

- A Minimal Pill
- B Contextual Nudge
- C Mini Conversation Entry

Proactive expansion:

- On / Off
- Fast ≈ 3s
- Balanced ≈ 6s (default)
- Gentle ≈ 10s

Launcher:

- Icon
- Motion
- Size
- Color / branding mode

Chat Window:

- Theme
- Window size preset

Engagement:

- Contextual Greeting On / Off
- Trusted Actions
- Trusted Action lifecycle controls

Preview:

- Desktop / Mobile
- Page Type
- Product/context
- Language

Admin SHOULD reuse the real Widget rendering path for preview rather than creating a second fake implementation.

### 2.17 Theme system

Chat Window theme modes:

- Match Website
- Light
- Dark
- Custom

Default: `Match Website`.

`Match Website` SHALL NOT blindly inherit arbitrary host CSS.

Safe authority/signal order should favor:

1. explicit Site/Admin brand config;
2. embed override;
3. `<meta name="theme-color">`;
4. recognized root brand/primary/accent CSS variables;
5. safe page light/dark/background signal;
6. ASK-AI fallback.

The system should derive only trustworthy host visual signals such as brand accent and page light/dark character, then generate ASK-AI-owned safe tokens.

Recommended semantic model:

- Brand accent = site-level identity
- Light/dark character = page-level adaptive

ASK-AI theme tokens should cover primary/contrast/background/surface/text/muted/border/input/CTA/link/citation/focus as needed.

### 2.18 Launcher branding is independent from panel theme

Default:

- Launcher: ASK-AI brand for discoverability
- Chat Panel: Match Website

Admin may choose Match Website or Custom launcher branding when white-label integration is desired.

### 2.19 Contrast and accessibility guard

Derived/custom themes SHALL preserve readable contrast for text, buttons, links, inputs and focus states.

Existing accessible launcher semantics SHALL not regress.

Required accessibility includes:

- semantic button controls;
- meaningful accessible labels;
- keyboard operation;
- focus-visible;
- appropriate dialog semantics for full chat;
- Escape close where appropriate;
- reasonable focus movement/restoration;
- reduced-motion support;
- readable contrast.

### 2.20 Host isolation

Widget SHALL remain an isolated bottom/right overlay.

Hard rules:

- no host layout reflow;
- no CSS leakage into host page;
- no host-page style corruption;
- no Widget presentation dependent on mutating host layout.

## 3. Existing Functional Capabilities That Must Remain

This is a Widget Experience increment. Preserve existing product behavior including, where applicable:

- real streaming;
- messages/conversation state;
- attachments;
- feedback;
- citations;
- language resolution;
- site-config;
- pageContext;
- existing embed/bootstrap semantics;
- launcher icon/shape/theme compatibility;
- first-visible launcher appearance correctness;
- existing error/failure behavior unless explicitly changed by this contract.

## 4. Explicit Non-goals

I-UX-001 does NOT authorize:

- Voice
- Video
- Digital avatar
- CRM visitor identity
- Lead qualification engine
- Meeting scheduling
- Email continuity
- Person-aware behavioral targeting
- New retrieval architecture
- Reranker changes
- Embedding changes
- EvidencePlan changes
- Claim/Evidence validation redesign
- Answer generation semantic changes
- ResponseStrategy changes
- New LLM calls for greeting/actions
- PII model changes
- New analytics architecture
- New automated evaluator architecture
- Full Pinned Agent mode
- Arbitrary custom CSS editor
- Arbitrary animation editor
- New Contextual Answer Action Engine

Existing answer links/resources may continue to render. A richer answer-action engine should be a later increment, e.g. I-UX-002.

## 5. Change Boundary

### EXPECTED

- Widget presentation state machine
- launcher UX/motion/size presentation
- Mini Conversation Entry
- floating desktop chat presentation
- mobile responsive presentation
- theme/token resolution
- Admin Widget Experience
- Trusted Action configuration/lifecycle
- live preview
- accessibility improvements

### REQUIRED SUPPORTING

Allowed when necessary to satisfy the frozen contract:

- site-config fields
- persistence/schema
- API serialization
- i18n strings
- migration/default semantics
- tests
- Admin form/view model

### FORBIDDEN WITHOUT NEW AUTHORIZATION

- retrieval/reranker/embedding behavior
- EvidencePlan / Claim-Evidence validation semantics
- answer generation semantics
- ResponseStrategy semantics
- unrelated Admin areas
- authentication model
- production deployment
- benchmark rerun solely for this UI increment

## 6. Required Visual Acceptance

Browser-rendered evidence SHALL cover at least:

Desktop:

1. initial compact launcher
2. A Minimal Pill
3. B Contextual Nudge
4. C Mini Conversation Entry
5. C after delayed proactive expansion
6. high-confidence product greeting
7. generic fallback greeting
8. C → Floating Chat destination state
9. empty Floating Chat
10. active conversation
11. inline citations without duplicate Sources section
12. light host
13. dark host
14. Match Website theme
15. Small / Medium / Large launcher

Mobile:

16. compact launcher
17. B contextual nudge
18. opened mobile chat
19. long answer scrolling
20. keyboard/input usability

Implementation itself plus browser-rendered screenshots/artifacts serves as the prototype/visual acceptance artifact. A separate Figma prototype is not required.

## 7. Functional Acceptance

The implementation candidate SHALL prove at least:

- A/B/C are configurable.
- New-site default resolves to C.
- Existing legacy sites without explicit config preserve legacy entry behavior.
- Desktop delayed auto-expansion works at the default balanced timing.
- Proactive expansion occurs at most once per site session.
- C does not auto-collapse on idle by default.
- Minimize/dismissal is respected.
- Mobile does not default to full-C proactive expansion.
- Trusted Action click starts a real request immediately.
- Direct C text submit starts a real request immediately.
- Floating Chat stays spatially anchored bottom-right on desktop.
- cold-start greeting/starters disappear after the real conversation starts.
- inline citations remain actionable.
- separate duplicate default Sources section is absent.
- Greeting safely falls back when context confidence is insufficient.
- SPA context updates do not re-trigger proactive expansion in-session.
- Theme modes resolve and render correctly.
- Launcher size presets work.
- Only VERIFIED + PUBLISHED Trusted Actions are eligible for proactive exposure.
- Action Test executes real ASK-AI and exposes actual answer/evidence to Admin.
- Admin preview reflects actual Widget configuration/context.

## 8. Regression Acceptance

No regression in existing relevant behavior, including:

- streaming
- attachments/upload
- feedback
- site-config
- language
- launcher icon
- launcher shape
- launcher theme
- pageContext
- citations
- message rendering
- errors/fail-safe behavior
- embed/bootstrap
- first-visible launcher appearance correctness

## 9. Browser / Responsive Acceptance

Verify the repository's supported modern browser scope, with practical coverage of Chromium, Safari/WebKit and Firefox where available, plus common desktop/mobile viewports.

No off-screen panel, unreachable input/close control, broken keyboard navigation, host reflow or major overflow regression.

## 10. Engineering Verification

Executor owns HOW and exact test design, but must run real verification including relevant:

- unit tests
- Widget tests
- Admin/config tests
- integration tests
- build
- typecheck
- lint where applicable
- existing regression suite
- browser-rendered visual verification

Do not claim PASS from code inspection alone.

## 11. Execution Delivery

Execution report path:

`docs/engineering/tasks/I-UX-001-WIDGET-EXPERIENCE-execution.md`

Report must include:

- authoritative implementation baseline
- baseline-reconciliation evidence
- final commit
- changed files
- implementation summary
- actual test commands/results
- acceptance matrix
- browser/visual artifacts
- known limitations
- scope audit

Use clean selective staging; do not use `git add -A`.

Executor final status is one of:

- CANDIDATE READY
- PARTIAL
- FAIL
- BLOCKED

Final Product acceptance remains owned by A after independent review.

## 12. Baseline / Authorization Gate

This Product Contract is frozen and authoritative for WHAT / UX semantics / Scope / Acceptance.

Before implementation, B MUST inspect repository truth and establish an authoritative implementation baseline that includes all previously accepted production/corrective work relevant to the target branch. At the time this contract was frozen, `main` was known to lag accepted production at least for the v1.2.1 stream trace corrective.

If baseline reconciliation is routine engineering integration, B owns HOW. If reconciliation exposes a material product-semantic conflict, stop and report `SCOPE EXPANSION REQUIRED` / BLOCKER rather than silently changing this contract.
