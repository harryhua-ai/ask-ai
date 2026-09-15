# Issue #80 — Ask AI Plugin Click-Tracking Contract

Date: 2026-09-15
Mode: Corrected discovery → implementation / verification
Status: `ISSUE_80_PLUGIN_TRACKING = CANDIDATE READY`

~~~text
SKILL CONTRACT = VERIFIED / CORRECTED
IMPLEMENTATION_CHANGE_REQUIRED = YES
HOST SOURCE CODE REQUIRED = NO
HOST TRACKING SIGNAL = element_click / contact / ask_ai / ask_ai
ONE CLICK / ONE SIGNAL = PASS
SYNTHETIC HOST INTEGRATION = PASS
ANALYTICS ACCESS REQUIRED FOR IMPLEMENTATION = NO
HISTORICAL ANALYTICS = UNPROVEN / OUT OF SCOPE
RELEASE RECOMMENDATION = READY_FOR_R4_CONSIDERATION
~~~

## 1. Corrected product framing

The previous Issue #80 implementation artifact treated unavailable Website and Store application repositories as a hard blocker. The corrected Role B task explicitly supersedes that conclusion.

Website, Wiki and Store are host systems. ASK-AI owns the reusable Widget/plugin integration contract and the Widget-owned launcher/entry DOM. A conforming host observes the public DOM click and records it using its existing tracker. Host application source ownership is not required for this ASK-AI change.

This candidate changes only ASK-AI Widget code, the repository integration guide, and repository-local contract tests. It does not change any host application, host GTM/GA4 configuration, or production system.

## 2. Baseline and source-of-truth inspection

| Item | Evidence |
|---|---|
| ASK-AI repository | `harryhua-ai/ask-ai` |
| Baseline | `origin/main` at `f4e67515af810840aa10fa800f0203c2ba290df0` |
| Fresh worktree | `/Users/harryhua/Documents/GitHub/ask-ai/.worktrees/issue80-plugin-contract-20260915` |
| User-supplied contract document | `/Users/harryhua/Downloads/SKILL.md`; front matter declares `name: auto-cta` and no version field |
| Repository integration tutorial | `docs/integration/CAMTHINK_ASK_AI_WEBSITE_INTEGRATION.md`; document version 3.0, dated 2026-09-10 |
| Repository-root `SKILL.md` | Not present at the inspected baseline; the repository integration tutorial is the repository-equivalent integration source |
| Previous artifact | The earlier `BLOCKED BY WEBSITE / STORE SOURCE ACCESS` conclusion is superseded by this corrected report |

The user task is the authorization and scope source. The supplied `SKILL.md` supplies the allowed CTA vocabulary. The repository tutorial supplies the actual Widget integration topology. Before this candidate, the repository tutorial did not state the Issue #80 host-observable click contract; section 1.6 was added to close that proven documentation gap.

## 3. Frozen tracking contract

The implementation uses only the existing host-side semantic vocabulary:

~~~text
data-track="contact"
data-type="ask_ai"
~~~

Where a host uses the existing CamThink Tracker, the expected event identity is:

~~~text
event_name     = element_click
track_category = contact
track_type     = ask_ai
track_name     = ask_ai
~~~

No `ask_ai_click`, `ask_ai_website`, `ask_ai_wiki`, or `ask_ai_store` event family was introduced. No new Analytics endpoint, schema, identity logic, prompt tracking, conversation tracking, PII, or fingerprinting was added.

The signal means Ask AI entry/open intent only. It does not mean a successful conversation, lead, purchase, or conversion.

## 4. Actual ASK-AI plugin topology

The repository evidence shows the following public integration path:

~~~text
Host document
  ├─ loads widget.js and widget CSS according to the integration guide
  └─ owns the document-level tracker/listener
       │
       ▼ ordinary light-DOM event propagation
widget/src/index.tsx
  └─ mountWidget(document, currentScript)
       └─ widget/src/bootstrap.tsx
            ├─ reuses or creates #ask-ai-widget-root
            └─ React createRoot(...).render(<App ... />)
                 └─ one of the Widget-owned open/expand entry buttons
~~~

`mountWidget` appends/reuses a normal DOM container in the host document. It does not create an iframe or Shadow DOM boundary. Duplicate script injection is guarded by reusing the same root and skipping a non-empty container.

`widget/src/App.tsx` selects the current entry path:

- `Launcher` → `.ask-ai-fab` icon launcher;
- `LauncherPill` → `.ask-ai-launcher-pill` branded launcher;
- `EntryPill` → `.ask-ai-pill` minimal entry;
- `ContextualNudge` → `.ask-ai-nudge-body` open button.

These are the four real Widget-owned controls whose click opens the panel or expands the mini entry. Their callbacks are the existing `openPanel` / `expandMini` behavior. `MiniConversationEntry` minimize, not-now, Trusted Action, and submit controls are intentionally not Ask AI entry targets; marking those controls would misclassify later conversation interactions as the initial Ask AI entry click.

## 5. Host-observable seam and implementation

### Before

The four real open/expand controls had their existing classes, accessibility attributes, and `onClick` callbacks, but no `data-track` or `data-type` attributes. A host delegated listener therefore had no stable Ask AI semantic identity to read from the Widget-owned DOM.

### After

The following existing controls now carry only the frozen attributes:

| Component | Element | Existing behavior preserved |
|---|---|---|
| `widget/src/launcher/Launcher.tsx` | `.ask-ai-fab` button | `onOpen` opens the panel or expands mini entry |
| `widget/src/launcher/Launcher.tsx` | `.ask-ai-launcher-pill` button | `onOpen` opens the panel or expands mini entry |
| `widget/src/components/EntrySurfaces.tsx` | `.ask-ai-pill` button | `onOpen` opens the panel |
| `widget/src/components/EntrySurfaces.tsx` | `.ask-ai-nudge-body` button | `onOpen` opens the panel |

The change is attribute-only at each existing entry seam. No manual `CamthinkTracker.track(...)` call was added, so the Widget does not create a second event alongside a host delegated listener.

The entry handlers do not call `preventDefault()`, `stopPropagation()`, or `stopImmediatePropagation()`. The only `preventDefault()` found in the entry surface is the existing mini conversation form-submit handler; it is not attached to the open/expand click buttons. The Widget remains in ordinary light DOM, so a host document listener can observe the click.

## 6. Synthetic host integration harness

`widget/src/__tests__/issue80PluginTracking.test.tsx` contains a repository-local synthetic host harness. It is test-only and does not become an ASK-AI analytics implementation.

The harness:

1. renders the real Widget entry components, rather than calling an internal tracking function;
2. places the rendered controls in a synthetic host document;
3. installs a minimal generic `document.addEventListener("click", ...)` delegated listener;
4. finds the nearest `[data-track][data-type]` element from the physical event target;
5. derives `track_category`, `track_type`, and `track_name` from the public attributes;
6. records the existing `element_click` semantic payload;
7. removes the listener after each case.

The harness does not import GA4, GTM, Analytics credentials, or a private ASK-AI emitter. A nested click on the branded pill text is also covered, proving that the public interaction container is the observable seam and that one physical event is not counted once per nested child.

## 7. TEST-1 through TEST-10

The tests were written before the production attribute change and run against the baseline first.

### RED baseline

~~~text
Focused command: npm test -- --run src/__tests__/issue80PluginTracking.test.tsx
Test files: 1 failed
Tests: 6 failed, 4 passed
~~~

The six failures were expected missing-contract failures: TEST-1, TEST-2, TEST-3, TEST-4, TEST-7 and TEST-9. The four baseline-green tests were TEST-5, TEST-6, TEST-8 and TEST-10; they verify non-Ask-AI isolation, existing callback behavior, generic semantic shape independence, and the documented anchor form respectively.

### GREEN result

~~~text
Focused command: npm test -- --run src/__tests__/issue80PluginTracking.test.tsx
Test files: 1 passed
Tests: 10 passed, 0 failed
~~~

| Test | Contract | Result |
|---|---|---|
| TEST-1 | All four real Widget entry seams expose `contact / ask_ai` | PASS |
| TEST-2 | Generic host delegated listener observes the launcher click | PASS |
| TEST-3 | Host derives `element_click / contact / ask_ai / ask_ai` | PASS |
| TEST-4 | One physical click on each real entry produces exactly one canonical signal | PASS |
| TEST-5 | Email/contact control remains non-Ask-AI | PASS |
| TEST-6 | Existing launcher open callback remains intact | PASS |
| TEST-7 | Harness requires no GA4/GTM/Analytics credentials | PASS |
| TEST-8 | Contract is independent of class, label, DOM position, and button shape | PASS |
| TEST-9 | Widget click reaches the host and is not default-prevented | PASS |
| TEST-10 | Documented anchor form has the same public semantic contract | PASS |

## 8. Documentation truth

The supplied `SKILL.md` correctly defines:

~~~html
<a href="/ask-ai/" data-track="contact" data-type="ask_ai">Ask AI</a>
~~~

and the mapping to the existing `element_click` event semantics. It also permits equivalent button/launcher carriers. The existing repository tutorial was technically incomplete because it documented the Widget integration but did not explain how a host observes Ask AI entry clicks. Section 1.6 of `docs/integration/CAMTHINK_ASK_AI_WEBSITE_INTEGRATION.md` now documents:

- the exact attributes and their placement on the actual interaction element;
- anchor and button forms;
- the four Widget-owned open/expand controls;
- ordinary light-DOM event bubbling and host delegated observation;
- host responsibility for reporting and identity;
- the distinction between entry intent and conversation/conversion success;
- controls that must not be marked as Ask AI entry clicks.

This is technical integration documentation, not Wiki knowledge content.

## 9. Regression, build, and typecheck

### Passed

~~~text
Widget full suite: 15 test files passed, 193 tests passed
Widget production build: npm run build → exit 0
~~~

The build emitted the existing IIFE artifacts successfully. No production artifact was deployed.

### Baseline environment failures, A/B proven

`npx tsc --noEmit` exits 2 in both this candidate and a fresh `origin/main` baseline worktree with the same four existing errors in `src/__tests__/issue47UserBubbleAlignment.test.tsx`: missing `node:fs`, `node:url`, `node:path`, and `process` types because `@types/node` is not installed. The Issue #80 test file does not introduce those imports or errors.

`pytest -q tests/test_widget_hosting.py` cannot load the root test suite in both this candidate and a fresh `origin/main` baseline worktree because the environment lacks `sqlalchemy`. No Python file was changed by this candidate.

`widget/package.json` has no lint script; no repository-standard Widget lint command is configured to run.

## 10. Analytics responsibility and query contract

ASK-AI provides a trackable integration signal, not a centralized analytics platform. After a host integrates the Widget/markup and its existing tracker observes the event, the host analytics system should query:

~~~text
event_name     = element_click
track_category = contact
track_type     = ask_ai
track_name     = ask_ai
~~~

The host may then calculate, using its existing capabilities:

- total qualifying Ask AI click events;
- distinct Analytics visitors according to the host platform's identity semantics, never an implied CRM customer count;
- page URL/path and host context;
- Website/Wiki/Store surface where the host's page context supports that attribution;
- a selected time range.

GA4 `contact_click` and CamThink custom collector `element_click` remain separate representations/destinations. They must not be summed as if they were independent Ask AI clicks. No host GTM/GA4 redesign is part of this candidate.

## 11. Historical Analytics limitation

Historical Analytics is optional evidence and not required for this integration implementation. The authenticated read-only check performed during this task exposed only the `wiki / production` project; the UI's current `element_click` visitor filter showed 783 visitor records. Those records were not interpreted as Ask AI clicks, customer counts, or three-surface coverage.

Historical continuity remains `UNPROVEN` and out of scope. No historical count was reconstructed, normalized, or fabricated. The contract is prospective from the eventual host deployment onward.

## 12. Exact files changed

| File | Change |
|---|---|
| `widget/src/launcher/Launcher.tsx` | Added frozen attributes to the existing FAB and branded launcher buttons |
| `widget/src/components/EntrySurfaces.tsx` | Added frozen attributes to the existing Minimal Pill and nudge open buttons |
| `widget/src/__tests__/issue80PluginTracking.test.tsx` | Added TEST-1 through TEST-10 and the generic synthetic host harness |
| `docs/integration/CAMTHINK_ASK_AI_WEBSITE_INTEGRATION.md` | Added the minimal Issue #80 host-observable click contract section |
| `docs/engineering/tasks/issue80-ask-ai-cta-analytics-implementation.md` | This corrected implementation report |

No Website/Store source was requested or changed. No Wiki content was changed. No shared Tracker contract was changed.

## 13. Branch and release relationship

~~~text
WORKTREE = /Users/harryhua/Documents/GitHub/ask-ai/.worktrees/issue80-plugin-contract-20260915
BRANCH   = codex/issue-80-plugin-contract-20260915
BASE     = f4e67515af810840aa10fa800f0203c2ba290df0
~~~

The branch is independent of the active `integration/v1.6.3-r4-20260915` worktree. The candidate recommendation is:

~~~text
READY_FOR_R4_CONSIDERATION
~~~

This is a Role B candidate recommendation only. Role A decides whether to include it in r4 after reviewing the small Widget change, test evidence, and release timing.

## 14. Boundary confirmation

~~~text
NO WEBSITE SOURCE REQUESTED
NO STORE SOURCE REQUESTED
NO PRODUCTION HOST MUTATION
NO PRODUCTION DEPLOY
NO GTM MUTATION
NO GA4 MUTATION
NO ANALYTICS MUTATION
NO NEW ANALYTICS EVENT FAMILY
NO HISTORICAL-DATA FABRICATION
NO WIKI CONTENT MODIFICATION
NO ASK-AI PROMPT OR CONVERSATION TRACKING
NO PII OR FINGERPRINTING
NO INTERFERENCE WITH R4 COMBINED INTEGRATION
~~~

Role A review is the next gate. Stop after candidate delivery.
