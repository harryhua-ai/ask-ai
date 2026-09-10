# I-UX-001 POST-PRODUCTION CORRECTIVE — Frozen Implementation Contract

Status: FROZEN IMPLEMENTATION CONTRACT
Authority: Product / UX contract + repository evidence
Tracking: #43
Covers: #6, #33, #36, #37, #38, #39, #40
Planning branch: `plan/i-ux-001-post-production-corrective`
Implementation baseline: `9343e65d302570ac2e943d6450507a54cfee44b2`
Product / UX contract: `docs/engineering/tasks/I-UX-001-POST-PRODUCTION-CORRECTIVE-plan.md`
Accepted visual baseline: V2.3

## 1. Objective

Bring the accepted I-UX-001 experience to production fidelity without reopening already accepted product semantics.

The executor owns engineering root-cause investigation and implementation HOW inside this contract. The executor MUST NOT redefine user-visible design, answer semantics, evidence semantics, retrieval, or unrelated Admin information architecture.

## 2. Repository facts established before freeze

### 2.1 Site authorization and origins

`site_experiences.allowed_origins` already exists as a JSONB field. Runtime `/api/ask` authorization resolves a declared `site_id`, normalizes the request Origin/Referer, and requires an exact match against that DB field. `site_id` itself is not a credential.

The current bootstrap path still seeds `allowed_origins` from `config/sites.yaml` and updates that field on startup. Therefore an Admin edit to `allowed_origins` would currently risk being overwritten by a later seed/restart unless the authority lifecycle is corrected.

Global browser CORS is currently built from `CORS_ALLOW_ORIGINS` once at FastAPI process startup. It is therefore not automatically synchronized with DB `site_experiences.allowed_origins` after an Admin mutation.

This is the central #6 engineering reconciliation problem. Product truth is one conceptual `Authorized Websites` policy; implementation MUST NOT require administrators to maintain two independent authorization lists.

### 2.2 Widget experience persistence

The current Admin Widget Experience API writes per-site experience fields in `site_experiences`, including `entry_mode`, `proactive_timing`, launcher settings, chat theme/size, and `greeting_override`. Trusted Actions persist separately and already implement DRAFT → TEST → VERIFIED → PUBLISHED semantics.

The current `greeting_override` is a static string field. V2.3 changes the product surface to default `Automatic` deterministic greeting plus optional custom template variables. Engineering may evolve persistence/API representation as necessary, but migration MUST preserve existing values and legacy semantics.

### 2.3 Theme semantics

The backend semantic registry already defines exactly four chat theme modes: `match`, `light`, `dark`, `custom`, with Match Website as the default. Do not add a fifth `automatic` chat theme mode.

### 2.4 Preview

The Admin preview already uses the real Widget build/rendering path with preview configuration and `previewMode`; it is not authorized to become a second fake Widget implementation. Preview mode must continue to avoid accidental real visitor `/api/ask` traffic unless the administrator explicitly invokes a real test action.

### 2.5 Launcher/default mismatch

Current launcher compatibility registries still treat the legacy `current` icon / legacy-compatible shape as fallback defaults in several paths, while the accepted V2.3 new-site experience uses the branded `✦ Ask AI` pill as the normal default presentation. The executor must reconcile new-site/default behavior without rewriting legacy sites that intentionally remain on legacy semantics.

### 2.6 #33 first-visible appearance

Current main already contains a first-visible launcher appearance state machine and regression tests intended to prevent provisional appearance from becoming visible before authoritative configuration resolves, with deterministic fallback on failure/timeout and no late second flash.

Therefore #33 is not authorization to implement another independent loading design. The executor MUST first reconcile code provenance and runtime reproduction. If current production behavior still flashes, identify the actual remaining runtime/build/bootstrap/configuration cause and fix that cause. If no longer reproducible on the accepted candidate, prove closure rather than rewriting the state machine unnecessarily.

## 3. Frozen Product / UX semantics

### 3.1 Unified Admin Widget workspace — #38

Replace the two top-level Widget configuration destinations (`Widget 体验` and `Widget 外观`) with one top-level `Widget` workspace.

The workspace contains four coherent sections:

1. Entry & Engagement
2. Appearance
3. Authorized Websites
4. Preview & Test

The rest of the existing Admin navigation is OUT OF SCOPE and must remain materially unchanged. Do not introduce CamThink-specific branding or redesign the global Admin shell.

Desktop target: configuration area plus persistent Live Preview where practical. Narrow/mobile Admin may stack configuration and preview.

### 3.2 Entry & Engagement — #39

Preserve A/B/C semantics:

- A — Minimal Pill
- B — Contextual Nudge
- C — Mini Conversation Entry

New-site default remains C. Legacy sites with no explicit entry configuration preserve legacy behavior.

Desktop C proactive default remains Balanced ≈6s, once per site session, no automatic collapse, and dismissal/minimize suppresses repeat proactive expansion for that session.

Mobile does not proactively expand C/full chat; C proactive exposure becomes a B-style contextual nudge before explicit open.

### 3.3 Contextual Greeting

Default Admin mode: `Automatic (recommended)`.

Automatic greeting remains deterministic, page-aware, and zero-new-LLM-call. Authority order:

1. explicit custom Admin/Site greeting template
2. trusted page context
3. safe page-type template
4. generic fallback

Custom template supports trusted deterministic variables such as product/page context. The existing `{product}` vocabulary may be retained internally or migrated, but the Admin-facing semantic intent must support the accepted V2.3 model such as `{product_name}`, `{page_title}`, `{page_type}` or an equivalent clearly mapped representation.

Unresolved variables MUST fail safely. Never expose raw unresolved placeholders or malformed text to visitors. Wrong-specific is worse than correct-generic.

A concrete product name such as NE503 is a resolved Preview/Test example, not a default persisted greeting.

### 3.4 Launcher

Normal new-site/default presentation: branded compact pill with ASK-AI identity, conceptually `✦ Ask AI`.

Supported presentation direction:

- Branded Pill — default for new/default configured experience
- Compact Icon — optional

Motion remains independently configurable: Static / Subtle Glow / Soft Pulse / Sparkle; default Subtle Glow.

Size remains Small / Medium / Large; default Medium.

Legacy icon/style compatibility must remain available where required for existing sites; legacy compatibility must not redefine the new default.

### 3.5 Mini Conversation

Desktop design target remains approximately 340px × 180–210px, bottom-right anchored.

Hierarchy:

1. `✦ Ask AI` identity/header
2. short contextual greeting
3. maximum two applicable PUBLISHED Trusted Actions
4. direct input
5. weak `Not now`/minimize affordance

Trusted Actions render only when actually eligible. Do not render empty slots, disabled fake actions, or placeholders.

### 3.6 Full Chat

Same surface/anchor expands into floating chat, approximately 420×640px with safe viewport constraints. Transition remains restrained; no promotional bounce/morph spectacle.

After conversation starts:

- no repetitive `You` label
- no repetitive `ASK-AI` label above assistant messages
- ASK-AI identity remains in the header
- cold-start greeting/actions disappear
- user/assistant content remain distinguishable through restrained layout/surface treatment
- avoid strong Messenger-style bubbles

Primary information hierarchy:

`Question → Answer → Inline Evidence → Follow-up Input`

### 3.7 Evidence presentation

Visitor answer UI MUST preserve inline actionable citations.

Do NOT render a separate default `Sources` section/cards beneath answers when citations already expose the evidence path.

Complete source inventories remain appropriate only in Admin / Debug / Evaluation / explicit user request contexts.

### 3.8 Waiting / Streaming — #40

State model:

`Send → Waiting for first token → First token → Streaming → Complete`

Waiting copy: `✦ Preparing an answer…` or localized equivalent.

Allowed: restrained sparkle luminance/breathing motion.

Forbidden:

- three-dot typing indicator
- spinner
- progress bar / percentage
- skeleton answer block
- invented backend stages
- rotating fake progress messages

First real token replaces/yields from the waiting state without material layout jump. Streaming content becomes dominant immediately. Reduced-motion uses a static indicator.

Actual TTFT/E2E performance work remains #23 and is OUT OF SCOPE.

### 3.9 Appearance / Theme — #37/#39

Chat theme modes are exactly:

- Match Website — default/recommended
- Light
- Dark
- Custom

Do not add a second `Automatic` theme semantic.

Match Website adapts through ASK-AI-owned semantic tokens using safe host signals. The V2.3 blue presentation is illustrative, not a hard-coded universal palette.

Launcher branding and panel theme remain independent concepts.

### 3.10 Preview & Test — #36/#37

Live Preview must continue to use the real Widget renderer.

Preview state model:

`Saved Site Config → Configuration Draft → Live Preview`

plus optional ephemeral Test Override.

Preview theme override values:

- Use Site Config — default
- Light
- Dark
- Match Website

A preview override is temporary and MUST NOT become persisted production Site configuration merely because the user saves production configuration elsewhere.

When an override is active, its temporary nature must be visually clear and Reset must restore `Use Site Config`.

Do not create a duplicate Custom Theme editor in Preview/Test. Custom production theme is edited under Appearance.

Admin preview authorization is not public-site authorization. Admin preview must not require adding the Admin host to production Authorized Websites.

### 3.11 Authorized Websites — #6

Admin product terminology: `Authorized Websites`; technical helper terminology may say `origin`.

Required capabilities per Site:

- list currently authorized exact origins
- add exact origin
- enable/disable where the chosen persistence model supports reversible state cleanly
- safely remove origin
- canonicalize scheme + host + optional non-default port
- distinguish http vs https
- reject wildcard authorization
- reject path/query-based authorization as policy input
- optionally test whether a candidate origin would be authorized if this can be implemented without inventing a second policy engine

No new Production/Development environment taxonomy is authorized by this contract.

Safety invariants:

- authorization remains site-specific
- fail closed
- no wildcard broadening
- existing official origins survive migration/restart unless an authorized Admin explicitly changes them
- Admin mutation must not require application image rebuild/redeploy
- browser CORS execution and server Site authorization must not become silently divergent policies
- changes must be observable/auditable at least through existing product logging/persistence conventions; do not invent an unrelated audit platform

If removal would leave no authorized production-use origin for a Site, UI must clearly communicate the impact before applying the destructive change. Engineering may determine the narrowest reliable detection mechanism without adding an unapproved environment taxonomy.

## 4. Change Boundary

### EXPECTED

- Widget presentation components/styles/state transitions required for V2.3 fidelity
- unified Widget Admin page/routes/navigation entry
- greeting automatic/custom-template representation
- real Preview/Test state separation
- site origin Admin APIs/persistence and runtime reconciliation
- targeted #33 runtime/bootstrap correction if reproduction proves a remaining defect
- tests and browser-rendered acceptance artifacts
- migrations needed for additive/reversible persistence evolution

### REQUIRED SUPPORTING

Allowed only where necessary:

- `site_experiences` schema evolution
- Admin/backend API schemas and serializers
- runtime CORS/site-policy plumbing
- deterministic template resolver / variable mapping
- i18n strings
- compatibility adapters for legacy Widget configuration
- configuration seeding changes required to preserve Admin authority
- test fixtures

### FORBIDDEN

- retrieval/reranker/embedding changes
- EvidencePlan / claim-evidence semantic changes
- answer generation semantic changes
- ResponseStrategy changes
- #23 latency optimization
- global Admin IA redesign outside merging the two Widget destinations
- CamThink-specific Admin rebranding
- new person-aware/CRM targeting
- new LLM calls for greeting/actions
- separate default Sources list/cards
- new analytics/evaluator/audit platform architecture
- arbitrary CSS editor
- arbitrary animation editor
- production deployment

If correct implementation requires crossing a FORBIDDEN boundary, stop and report `SCOPE EXPANSION REQUIRED` before modifying that boundary.

## 5. Engineering acceptance

The implementation candidate must prove at minimum:

1. Existing non-Widget Admin navigation remains materially unchanged; only Widget Experience/Appearance are consolidated into Widget.
2. New-site/default configured entry visibly uses the accepted branded pill direction; explicit legacy sites preserve legacy compatibility.
3. A/B/C behavior and desktop/mobile proactive rules remain correct.
4. Automatic greeting changes according to reliable page context; custom template variables resolve deterministically and fail safely.
5. No per-message `You`/`ASK-AI` labels are added; active conversation is content-first.
6. Waiting state contains no three-dot typing indicator and makes no fake backend-progress claims.
7. Inline citations remain; duplicate default Sources section is absent.
8. Theme enum remains Match Website / Light / Dark / Custom; Match Website is default and adapts safely to host signals.
9. Admin Configuration Draft updates Live Preview without requiring persistence first.
10. Preview/Test overrides are ephemeral and cannot silently persist through Save.
11. Preview and production share the same Widget rendering/config-resolution path except for explicit preview/test boundary behavior.
12. Preview does not accidentally emit real `/api/ask` traffic; explicit Trusted Action Test still uses the real ASK-AI pipeline as already contracted.
13. Authorized Websites CRUD/config operations validate exact origin semantics, reject wildcard/path policy input, preserve ports correctly, and remain site-specific.
14. Authorized Websites changes survive ordinary service restart/reseed; startup seeding does not silently restore an obsolete YAML list over an Admin-authoritative mutation.
15. A browser request from an Admin-authorized origin succeeds through both CORS execution and server `resolve_site` authorization without redeploy.
16. A non-authorized origin fails closed; no CORS/site-policy mismatch can silently broaden access.
17. Existing official origins are preserved across migration unless explicitly changed.
18. #33: first visible successful appearance is the resolved final appearance; no stale/default → configured flash. Failure/timeout yields usable deterministic fallback; late config must not cause a second flash.
19. Attachments, feedback, conversation persistence, language, pageContext, citations, host isolation, accessibility and embed/bootstrap behavior do not regress.
20. No product-semantic changes outside the frozen corrective scope appear in the diff.

## 6. Required tests / evidence

Executor owns exact test design, but final evidence must cover:

- backend unit/integration tests for exact-origin normalization/validation and Site authorization
- persistence/restart/reseed test for Admin-managed origins
- CORS + Site authorization reconciliation test at the real HTTP boundary where practical
- Admin tests for unified Widget navigation/workspace and save semantics
- Preview tests proving configuration draft vs ephemeral override separation
- Widget component/runtime tests for launcher default/legacy split, greeting resolution, waiting→first-token→streaming, and no duplicate Sources section
- #33 first-visible appearance regression tests plus a real browser/runtime check
- desktop/mobile browser screenshots or equivalent rendered evidence for V2.3 states
- regression suite for existing Widget/Admin behavior touched by the change

## 7. Delivery

Executor must write:

`docs/engineering/tasks/I-UX-001-POST-PRODUCTION-CORRECTIVE-execution.md`

Report must include:

- implementation baseline and final candidate SHA
- engineering RCA, especially #6 authority reconciliation and #33 runtime status
- changed files grouped by issue
- migrations/default/legacy behavior
- test commands and exact results
- browser/runtime evidence
- scope audit
- unresolved risks
- delivery status: `CANDIDATE READY`, `PARTIAL`, `FAIL`, or `BLOCKED`

No production deployment is authorized by this contract.

## 8. Authorization

This implementation contract is AUTHORIZED for executor implementation once persisted in the repository on the planning branch.

The executor may choose implementation HOW inside the boundaries above, but may not reinterpret the accepted V2.3 design or change product semantics without returning to Product Owner / Planner.
