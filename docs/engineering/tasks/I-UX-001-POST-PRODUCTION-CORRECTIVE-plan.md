# I-UX-001 POST-PRODUCTION CORRECTIVE — Widget Production Polish & Integration Readiness

Status: FROZEN PRODUCT / UX CONTRACT
Authority: Product Owner + Role A
Design Review: V2.3 ACCEPTED
Planning branch: `plan/i-ux-001-post-production-corrective`
Planning anchor: `9343e65d302570ac2e943d6450507a54cfee44b2`
Production release reference: `v1.3.0` / `8bec1c0251d25630b5e2d461a9a5671cb2841b34`

## 1. Purpose

This is a post-production corrective for the accepted I-UX-001 Widget experience. It does not rewrite the historical v1.3.0 acceptance. It closes observed fidelity, Admin integration, authorization-management and waiting-state gaps while preserving accepted answer/evidence semantics.

Target:

`one coherent Widget workspace + faithful visitor entry + contextual engagement + safe embed authorization + truthful waiting/streaming + real-widget preview`

## 2. Scope Matrix

IN SCOPE:

- #6 Authorized Websites / allowed origins management
- #33 Initial Theme Flash — reconciliation / runtime corrective only
- #36 Admin Preview launcher fidelity
- #37 Admin Test Widget theme/context simulation
- #38 unify Widget Experience + Widget Appearance into one Widget workspace
- #39 launcher + Mini Conversation + Full Chat fidelity
- #40 waiting / first-token / streaming visual experience

DUPLICATE:

- #41 is duplicate of #6.

RELATED BUT OUT OF SCOPE:

- #23 real TTFT / end-to-end answer latency optimization.

## 3. Global Hard Boundaries

This corrective MUST NOT change retrieval, reranking, embeddings, EvidencePlan, answer-generation semantics, ResponseStrategy, citation semantics, authentication model, unrelated Admin areas, or production deployment mechanics unless a separately authorized contract requires it.

Existing relevant behavior must remain: streaming, conversation state, attachments, feedback, language resolution, site-config, PageContext, embed/bootstrap, error/fail-safe behavior and actionable inline citations.

A separate default `Sources` list/cards section SHALL NOT be added when inline citations already expose evidence. Complete source inventories remain appropriate for Admin / Debug / Evaluation / explicit user demand.

No per-message `You` or `ASK-AI` role labels in active Full Chat. ASK-AI identity remains in the conversation header. Content hierarchy is:

`Question → Answer → Inline Evidence → Follow-up Input`

User questions should use restrained content treatment rather than strong Messenger-style bubbles.

## 4. #38 — Unified Admin Widget Workspace

The two existing top-level Admin entries `Widget 体验` and `Widget 外观` SHALL become one top-level `Widget` workspace.

This contract does NOT authorize redesigning the rest of the Admin global navigation. Existing unrelated navigation, grouping and product identity remain unchanged.

Widget workspace sections:

1. Entry & Engagement
2. Appearance
3. Authorized Websites
4. Preview & Test

Desktop target: configuration on the left, persistent Live Preview on the right where practical. Narrow/mobile Admin may stack configuration and preview.

State semantics are mandatory:

- Configuration edits = production configuration draft.
- Preview/Test controls = ephemeral simulation state.
- Preview/Test state MUST NOT silently persist production configuration.
- Only explicit production configuration save changes Site configuration.

Live Preview SHALL reuse the actual Widget rendering path, not a separately maintained fake Widget implementation.

## 5. #39 — Visitor Entry and Conversation Fidelity

### 5.1 Launcher

Default new-site launcher presentation is a branded compact pill:

`✦ Ask AI`

Target height approximately 40–44px. Use restrained rounded geometry/shadow. Default motion is `Subtle Glow`; hover may use slight elevation/brightness. Reduced-motion renders a static equivalent.

Product choices:

- Branded Pill — default for new configuration
- Compact Icon — optional

Legacy launcher/icon configurations remain compatible for existing sites; legacy visuals SHALL NOT define the new-site default.

Launcher size presets remain Small / Medium / Large; default Medium.

### 5.2 Mini Conversation Entry C

Desktop target approximately 340px wide × 180–210px high at the same bottom-right anchor.

Content:

1. minimal header `✦ Ask AI`
2. contextual greeting, preferably one line and maximum two
3. maximum 2 eligible PUBLISHED Trusted Actions
4. direct input
5. weak `Not now` / minimize affordance

Trusted Actions are compact chips/secondary controls. Show exactly the applicable eligible actions: two, one, or none. Never show fake actions, disabled placeholders or empty slots.

Direct input is primary interaction. Enter sends; Shift+Enter may add a newline where supported; focus state must be visible.

### 5.3 Transition and Full Chat

`Launcher → Mini Conversation → Full Chat`

The same anchored surface grows rather than opening an unrelated UI. Target transition class: restrained ~220–260ms, no spring/bounce/fly-in.

Trusted Action or direct input:

`C → expand → exactly one real /api/ask request → waiting → streaming answer`

No redundant welcome or second click. Starter actions disappear once conversation begins.

Desktop Full Chat target approximately 420×640px, max-height about 82vh, with minimal header and sticky follow-up input.

### 5.4 Mobile

Mobile does not proactively expand C. For C-configured sites, proactive presentation uses a B-style contextual nudge; explicit interaction opens mobile Full Chat.

## 6. Contextual Greeting

Greeting remains deterministic and adds `NEW_LLM_CALLS = 0`.

Resolution authority:

1. explicit Site/Admin override
2. trusted PageContext
3. safe page-type template
4. generic fallback

Default Admin behavior is `Automatic (recommended)` using contextual resolution. Admin may choose `Custom template`.

Custom templates may use controlled variables such as:

- `{product_name}`
- `{page_title}`
- `{page_type}`

The Admin SHOULD show the template separately from its resolved preview value. Example:

- Template: `Questions about {product_name}?`
- Resolved preview on NE503 page: `Questions about NE503?`

A missing variable MUST NOT leak unresolved placeholders or malformed wording. Resolution degrades safely to a less-specific page/category template and ultimately `How can I help?`.

Frozen principle: `wrong-specific is worse than correct-generic`.

## 7. Trusted Actions

Preserve the accepted controlled semantic catalog and lifecycle from I-UX-001.

C shows maximum 2 PUBLISHED eligible actions. Product examples may resolve to Specifications / Setup guide; documentation examples may resolve to Explain this page / Troubleshoot.

Trusted Action selection and greeting derive from the same trusted engagement context.

Action click starts one real ASK-AI request immediately. No fake answer preview.

## 8. Appearance

Appearance belongs inside the unified Widget workspace.

Launcher controls:

- Style: Branded Pill / Compact Icon
- Motion: Static / Subtle Glow / Soft Pulse / Sparkle
- Size: Small / Medium / Large

Chat theme modes are exactly:

- Match Website — default/recommended
- Light
- Dark
- Custom

Do NOT introduce a separate `Automatic` chat-theme mode; `Match Website` owns adaptive host-site styling semantics.

Match Website derives safe semantic tokens from trustworthy host/site signals; it MUST NOT blindly inherit arbitrary host CSS. The implementation should preserve ASK-AI-owned tokens for surface, text, muted text, border, accent, focus, actions, inputs, citations and related states.

The V2.3 blue palette is illustrative only. It MUST NOT be hard-coded as the universal Widget appearance.

Custom theme may expose safe high-level controls such as accent; this corrective does not authorize arbitrary custom CSS or low-level design editing.

## 9. #37 — Preview & Test

Preview/Test uses the real Widget renderer.

Required simulation dimensions include where supported:

- Desktop / Mobile
- Page Context
- language
- preview theme

Preview Theme choices:

- Use Site Config — default
- Light
- Dark
- Match Website

Custom production theme is edited in Appearance; do not create a duplicate Custom Theme editor in Preview/Test.

Preview theme/context overrides are ephemeral and preview-only. They MUST NOT be persisted by production `Save Changes`.

When an override is active, the UI should clearly communicate that the preview is temporary and provide Reset / Use Site Config behavior.

Admin Live Preview must not require adding the Admin application's own origin to production Authorized Websites. It uses an authenticated Admin preview boundary.

Preview activity MUST NOT accidentally create a real production visitor `/api/ask` unless the Admin explicitly performs a real Test action.

## 10. #6 — Authorized Websites

Product terminology: `Authorized Websites`. Technical helper copy may use `origin` where precision is useful.

The Admin manages which exact website origins may embed/use the Site Widget. It MUST NOT expose separate CORS and Site-authorization lists for administrators to maintain independently.

Required behavior:

- view current site-specific authorized origins
- add exact origin
- remove origin safely
- enable/disable when this maps cleanly to authoritative runtime semantics
- canonicalize scheme + host + optional port
- support http / https / non-default ports as valid exact origins where policy allows
- reject wildcard authorization
- reject path/query as authorization scope
- fail closed
- preserve existing official/production authorization during migration
- changes are user-visible/auditable

Do NOT invent a new Production/Development origin taxonomy unless repository/runtime discovery proves such semantics already exist and are required. The Product Owner has not authorized a new environment data model.

Removing the final effective production authorization requires a clear consequence warning before destructive persistence.

Public Widget authorization and Admin Preview authorization are distinct boundaries:

- Public Widget → Authorized Websites enforcement
- Admin Live Preview → authenticated preview boundary
- Admin explicit real Test → authenticated test boundary using real ASK-AI pipeline

B must discover and reconcile the authoritative runtime truth so CORS and site authorization cannot silently diverge.

## 11. #36 — Preview Fidelity

Admin Preview SHALL render the actual Widget implementation and the same resolved configuration semantics as production.

No preview-specific launcher implementation.

New/default configuration resolves to Branded Pill / `✦ Ask AI`. Explicit legacy configuration may preserve legacy icon appearance.

Preview and production given equivalent resolved configuration/context should produce materially equivalent Widget presentation.

## 12. #33 — First Visible Theme / Launcher Appearance

This is an engineering reconciliation/runtime corrective, not a new visual design.

Successful normal path:

`UNRESOLVED → no incorrect provisional Widget appearance visible → FINAL RESOLVED WIDGET visible`

First visible appearance must equal final resolved appearance.

Do NOT add:

- loading launcher
- skeleton launcher
- temporary neutral theme
- loading-theme copy
- stale/default → configured visual transition

Failure/bounded timeout may use a deterministic usable fallback; the Widget must not remain permanently invisible/broken.

Late authoritative config must not cause a second visible launcher/theme flash.

Current main already contains first-paint logic/tests apparently targeting this behavior. Executor MUST reconcile provenance and current runtime behavior before changing implementation; do not reimplement #33 blindly.

## 13. #40 — Waiting / First Token / Streaming

State model:

`Send → Request accepted → Waiting for first token → First token → Streaming → Complete`

Waiting state:

`✦ Preparing an answer…`

Only the branded sparkle may use a restrained breathing/luminance cue. Reduced-motion renders a static equivalent.

Explicitly forbidden:

- three bouncing typing dots
- spinner
- progress bar / percentage
- large skeleton
- invented backend stages such as Understanding / Searching / Evaluating / Generating
- rotating fake-progress copy such as Almost there

At first real token, waiting yields in place to actual answer with no layout jump; a restrained ~120–180ms crossfade is acceptable. Waiting animation stops immediately.

Streaming makes answer content dominant. Avoid toy-like typewriter animation and heavy typing indicators.

Complete state preserves normal answer + actionable inline citations, with no duplicate default Sources section.

Long TTFT keeps the stable truthful waiting state; actual latency optimization remains #23.

Errors terminate waiting and expose truthful error + Retry. Retry is an explicit new request. This corrective does not authorize a broader error architecture redesign.

## 14. Accessibility and Isolation

Preserve/improve semantic controls, accessible launcher name, keyboard operation, focus-visible, appropriate dialog semantics, Escape close, focus transfer/restoration, reduced motion and readable contrast.

Widget remains an isolated fixed overlay: no host layout reflow, no CSS leakage, no host-page corruption.

## 15. Visual Baseline V2.3

Product Owner accepted the V2.3 design review on 2026-09-10.

The design board is a visual/interaction semantic reference, not a pixel-level implementation specification. When a visual illustration conflicts with this written contract or accepted I-UX-001 semantics, the written contract and explicit frozen decisions control.

V2.3 specifically establishes:

- ASK-AI identity, not CamThink-specific Admin branding
- existing Admin global IA preserved except Widget Experience + Appearance consolidation
- no standalone Sources section
- no per-message role labels
- no three-dot waiting indicator
- Match Website as the adaptive default theme
- contextual Greeting Automatic/Custom-template model
- real Widget preview
- ephemeral Preview/Test state
- Authorized Websites as the single administrator-facing authorization concept

## 16. Change Boundary

### EXPECTED

- unified Widget Admin workspace
- launcher / Mini Conversation / Full Chat fidelity corrections
- deterministic contextual Greeting Admin model
- Appearance controls and semantic theme presentation
- Authorized Websites Admin surface
- real Widget preview/test integration
- waiting/streaming visual states
- first-visible appearance reconciliation
- accessibility improvements directly required by these surfaces

### REQUIRED SUPPORTING

Allowed when necessary:

- site-config fields/defaults/migrations
- persistence/schema/API serialization
- origin validation/canonicalization/runtime reconciliation
- i18n
- Admin view models/routes
- Widget presentation state
- tests and browser/runtime acceptance artifacts

### FORBIDDEN WITHOUT NEW AUTHORIZATION

- unrelated Admin IA redesign
- CamThink-specific hard-coded product branding
- retrieval/reranker/embedding changes
- EvidencePlan / answer-generation / ResponseStrategy changes
- citation semantic changes
- new default Sources inventory
- new LLM calls for greeting/actions
- arbitrary custom CSS editor
- new analytics/evaluator architecture
- real latency optimization (#23)
- production deployment

If implementation requires crossing this boundary, stop with `SCOPE EXPANSION REQUIRED`.

## 17. Acceptance Gates

### Contract Gate

Implementation matches this frozen contract and the still-authoritative non-conflicting I-UX-001 contract.

### Scope Gate

No unexplained changes outside EXPECTED / REQUIRED SUPPORTING boundaries.

### Engineering Gate

Relevant unit/integration/frontend tests pass. Existing relevant behavior remains intact. #33 and #6 require root-cause/runtime-authority reconciliation rather than speculative duplication.

### Runtime Gate

Browser-rendered evidence proves at minimum:

- Branded Pill launcher
- desktop C proactive Mini Conversation
- Automatic contextual greeting with safe fallback
- 0/1/2 Trusted Action behavior
- C → one real request → waiting → streaming → answer
- Full Chat without per-message role labels
- inline citation with no duplicate Sources inventory
- Light / Dark / Match Website / Custom presentation
- reduced-motion waiting behavior
- mobile contextual nudge → full chat
- all four Admin Widget workspace sections
- real Widget Live Preview
- ephemeral Preview Theme behavior
- Authorized Websites add/remove/validation behavior
- first-visible appearance has no stale/default flash

### Real-World Gate

Production-like integration proves:

- authorized exact origin succeeds
- unauthorized origin fails closed
- Admin Preview works without polluting production origin authorization
- Site configuration and runtime authorization cannot diverge silently
- representative host themes resolve safely
- real answer/citation behavior remains unchanged except approved presentation corrections

## 18. Executor Investigation Boundary

Role B owns engineering root-cause investigation, implementation architecture, migration strategy, test design and debugging inside this Frozen Product / UX Contract.

Role B MUST NOT silently change product semantics or invent new user-visible design. If repository reality makes a frozen requirement infeasible or materially unsafe, report evidence and stop with `SCOPE EXPANSION REQUIRED` or `PRODUCT DECISION REQUIRED` as appropriate.

## 19. Next Gate

This document freezes WHAT / UX / boundaries. It does not yet authorize implementation.

Next required artifact:

`I-UX-001-POST-PRODUCTION-CORRECTIVE-implementation-contract.md`

That contract must be grounded in current repository evidence and must define HOW-level engineering acceptance without changing this Product / UX contract.