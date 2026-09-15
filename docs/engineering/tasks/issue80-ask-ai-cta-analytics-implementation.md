# Issue #80 — Ask AI CTA Analytics Implementation

**Implementation status:** BLOCKED

**Issue:** https://github.com/harryhua-ai/ask-ai/issues/80

**Target train:** v1.6.3-r4

**Investigation date:** 2026-09-15 (Asia/Shanghai)

**Execution mode:** Role B engineering executor. The product decision authorizes implementation prospectively, but this delivery stops at the task-defined hard gate because two required surface repositories cannot be identified or accessed.

**Safety boundary:** No production deployment, production GTM mutation, production GA4 mutation, historical-data reconstruction, Wiki content modification, Ask AI UX change, or interference with the active r4 integration worktree.

## 1. Final disposition

~~~text
ISSUE_80_IMPLEMENTATION = BLOCKED
PRODUCTION_ANALYTICS_CONFIGURATION_REQUIRED = YES
READY_FOR_R4_CONSIDERATION = NO — pending required source access and independent review
IMPLEMENTATION_AUTHORIZED = YES
IMPLEMENTATION_COMPLETED = NO
~~~

The implementation is not safely deliverable across all three surfaces from the available repositories. Website and Store are required implementation surfaces, but no authoritative source repository or checkout could be identified. The public deployed HTML is suitable for read-only topology evidence only; it is not a safe implementation target.

Historical Analytics continuity is not treated as a blocker, per the Role A decision. The blockers are source ownership/access and unresolved safe event ownership for the Store’s duplicate GTM path.

## 2. Accepted product contract

The product-level metric is conceptually named ask_ai_click. This implementation does not introduce a new transport event name because the accepted Discovery proved that the existing event contract already carries the required semantics:

~~~text
actual event_name     = element_click
track_category        = contact
track_type            = ask_ai
track_name            = ask_ai
conceptual metric     = ask_ai_click
~~~

The canonical CTA remains:

~~~html
<a href="/ask-ai/" data-track="contact" data-type="ask_ai">Ask AI</a>
~~~

Required externally meaningful dimensions are:

- source_surface: website, wiki, or store;
- source_host;
- source_path;
- destination;
- native analytics event timestamp.

No new user identity tracking, fingerprinting, PII, prompt content, conversation content, CRM enrichment, or competing per-surface taxonomy is authorized. A click is intent/entry only, not a chat, lead, purchase, conversion, or CRM-customer count.

## 3. Baselines and repository verification

| Repository/surface | Baseline | Access result |
|---|---|---|
| Ask AI | f4e67515af810840aa10fa800f0203c2ba290df0 (origin/main) | Accessible; repository search confirms no surface CTA implementation |
| Accepted Discovery artifact | 648b3916ab84219b7d2e6ece8708d252bcebe581 | Accessible and re-read; historical evidence remains explicitly unproven |
| Wiki | 64c521743593c3e89b19fc12c5e73e029704cec9 (origin/main) | Accessible remotely; local worktree is dirty and was not modified |
| Website | unavailable | No authoritative Website repository was listed in harryhua-ai GitHub repositories or available as a local checkout |
| Store | unavailable | No authoritative Store repository was listed in harryhua-ai GitHub repositories or available as a local checkout |
| private harryhua-ai/camthink candidate | main, skills-only repository | Not a Website/Store application; root contains README.md, install.sh, segment.yaml, and skills/ |

Repository discovery used the configured GitHub organization listing, local GitHub checkout inventory, and the private camthink candidate inspection. No replacement repository was guessed from a similarly named project.

The active r4 integration worktree is /Users/harryhua/Documents/GitHub/ask-ai-r4-integration on branch integration/v1.6.3-r4-20260915. It was not entered, modified, rebased, merged, or otherwise disturbed.

## 4. Surface topology

| Surface | CTA implementation | Analytics bootstrap | Existing click tracking | Duplicate risk | Canonical implementation seam |
|---|---|---|---|---|---|
| Website | Public Widget button.ask-ai-launcher-pill; no canonical anchor found | CamThink Tracker 0.4.0 and GTM-WRP2RQPS observed; GA4 Measurement ID G-XBWTN65KKB observed | Tracker captures the unlabeled Widget button; current canonical CTA event is absent | UNPROVEN end-to-end; no equivalent duplicate bootstrap observed in public runtime, source unavailable | Website source/template required; unavailable |
| Wiki | Widget section.ask-ai-mini; no canonical anchor found | Docusaurus Root.js injects CamThink Tracker; production config loads GTM-WRP2RQPS | Tracker captures eligible clicks when consent allows; custom Root.js page() emits page_view | PROVEN page_view duplication; this mechanism does not duplicate element_click | Wiki src/theme/Root.js or approved theme/layout component; source available but not changed |
| Store | WordPress/WooCommerce Widget button.ask-ai-launcher-pill; WhatsApp/email contacts only; no canonical anchor found | Inline CamThink Tracker 0.4.0 plus duplicate GTM-WRP2RQPS bootstrap; GA4 Measurement ID G-XBWTN65KKB observed | Tracker captures the unlabeled Widget button; GTM contact_click mapping exists for tagged anchors | PROVEN duplicate GTM/page_view; LIKELY duplicate GA4 CTA mirror if a canonical anchor is later added | WordPress/WooCommerce theme/template required; unavailable |
| Shared CamThink Tracker | Public SDK 0.4.0 | Custom collector https://analytics.camthink.ai/collect/v1/events | Existing capture-phase listener maps frozen attributes to element_click | One observed SDK listener per inspected surface; duplicate custom listener not proven | NO CHANGE unless a future real-CTA test proves SDK insufficiency |
| ASK-AI repository | Backend, Widget, Admin, integration configuration | Not the Website/Store template owner | Repository search found no CTA analytics implementation | Not applicable to surface click ownership | NO CHANGE |

## 5. Root implementation seam and event ownership

The required seam is surface-owned semantic CTA markup consumed by the already-loaded CamThink Tracker:

~~~text
real canonical anchor
  -> existing capture-phase Tracker click listener
  -> one custom collector element_click event
  -> query/report as conceptual ask_ai_click
~~~

GTM/GA4 is a separate existing mirror path:

~~~text
real canonical anchor
  -> existing GTM data-track/data-type mapping
  -> GA4 contact_click
~~~

The custom collector event is the preferred canonical count source because it already satisfies the accepted Issue #80 contract. GA4 contact_click must not be added to the custom collector count. If GA4 remains a reporting source, its mapping must be reconciled and Store’s duplicate bootstrap must be resolved or explicitly excluded from the canonical report.

No second surface listener or new generic tag was added. The implementation cannot be completed because the Website and Store owners/source seams are unavailable, and a partial Wiki-only change would not satisfy the cross-surface contract.

## 6. CTA inventory confirmation

| SURFACE | Ask AI entry exists? | DOM type | destination | data-track | data-type | tracker listener applicable? | GTM applicable? | canonical CTA already present? |
|---|---|---|---|---|---|---|---|---|
| Website | YES — Widget only | button.ask-ai-launcher-pill | Opens Widget UI; no /ask-ai/ navigation | absent | absent | YES — existing SDK captures the button | YES — container loaded; current button has no canonical attributes | NO |
| Wiki | YES — Widget mini entry only | section.ask-ai-mini with controls | Opens Widget UI; no /ask-ai/ navigation observed | absent | absent | YES when consent allows SDK injection; otherwise consent-gated | YES — production container/config path exists; current mini entry has no canonical attributes | NO |
| Store | YES — Widget only | button.ask-ai-launcher-pill | Opens Widget UI; no /ask-ai/ navigation | absent | absent | YES — existing SDK captures the button | YES — container loaded; current button has no canonical attributes | NO |

Store’s existing data-track=contact elements are WhatsApp/email links, not Ask AI. The Widget launcher and the canonical anchor are separate semantic objects. None of the current Widget controls satisfy the frozen canonical CTA contract.

## 7. Surface attribution

Current attribution is deterministically derivable from existing event page fields:

| source_surface | Rule | Unknown-host behavior |
|---|---|---|
| wiki | hostname equals wiki.camthink.ai | not applicable |
| store | hostname equals www.camthink.ai and path starts /store/ | not applicable |
| website | hostname equals www.camthink.ai and path does not start /store/ | not applicable |
| unknown | all other host/path combinations | must not be counted as website/wiki/store |

The current custom collector payload contains page path and URL but does not expose a dedicated surface field on element_click. No new dimension was added. The apex camthink.ai currently redirects to www.camthink.ai. The current route rules are PROVEN for deployed topology; historical application remains unavailable.

## 8. Duplicate-event analysis

### Website

Classification: UNPROVEN end-to-end.

The public runtime showed one CamThink Tracker click listener path and no equivalent duplicate bootstrap. There is no real canonical anchor to click, and the authoritative source repository is unavailable. Therefore it is not safe to claim exactly-one canonical production behavior or to add another listener.

### Wiki

Classification: PROVEN page_view duplication; NOT APPLICABLE to element_click for the identified mechanism.

The SDK auto-sends page_view and Wiki Root.js calls CamthinkTracker.page() on Docusaurus location changes. Controlled observation captured two page_view events. The page() call emits page_view; it does not register a second click listener. The inspected initialization is guarded. This finding must not be generalized into a duplicate Ask AI click defect.

### Store

Classification: PROVEN duplicate GTM bootstrap; LIKELY duplicate GA4 CTA mirror; custom collector duplication UNPROVEN.

The public WordPress HTML contains an inline GTM bootstrap and a second GTM bootstrap from the visible GTM integration, plus two matching noscript containers. Controlled reloads captured two blocked GA4 page-view POSTs. If a future canonical anchor is present, two GTM container instances can independently evaluate the same gtm.linkClick and fire the existing contact_click tag; this makes duplicate GA4 CTA reporting LIKELY. Only one Tracker script/listener was observed, so duplicate custom collector element_click is not proven.

No duplication fix was attempted because the Store source repository and exact owner are unavailable, and the task forbids production console mutation.

## 9. Production analytics configuration boundary

No production analytics configuration was changed.

The existing custom collector path requires no new event registration if the canonical anchor uses the existing Tracker contract. The GA4 path is not safe to treat as an independent canonical count until the following external/configuration work is explicitly authorized:

1. confirm whether GA4 contact_click is a mirror or the selected reporting source;
2. ensure Store’s duplicate GTM bootstrap cannot produce two reportable canonical CTA events;
3. confirm the one-source-of-truth query and existing host/path segmentation;
4. if required by the chosen GA4 report, register or expose existing fields without changing the frozen CTA taxonomy.

Because this configuration is external to the accessible repositories and no production mutation is authorized, the implementation delivery records:

~~~text
PRODUCTION_ANALYTICS_CONFIGURATION_REQUIRED = YES
~~~

This means a separately authorized post-merge configuration/reconciliation gate is required; it does not mean that any external console change was performed.

## 10. RED evidence

No RED tests were created or run. This is intentional and caused by the task-defined hard stop, not by a weakened test:

- Website authoritative source unavailable;
- Store authoritative source unavailable;
- no safe cross-surface implementation seam can be modified;
- a partial Wiki implementation would not prove the required three-surface behavior;
- no production or synthetic analytics traffic may be sent to compensate for missing source access.

The accepted Discovery report’s fully intercepted synthetic mapping probe remains valid evidence that the existing SDK maps the frozen attributes. It is not RED/GREEN evidence for a real CTA implementation.

## 11. GREEN evidence

No GREEN implementation evidence exists. The following acceptance criteria remain unproven:

- real Website click emits exactly one canonical event;
- real Wiki click emits exactly one canonical event from an approved canonical anchor;
- real Store click emits exactly one canonical event;
- cross-surface source_surface attribution from implemented production markup;
- source_path and destination capture from real canonical anchors;
- duplicate-event prevention for the implemented Store path;
- transport failure preserving navigation;
- non-Ask-AI contact exclusion in the implemented source seams;
- unknown-host fail-safe behavior in the implemented reporting path;
- cross-surface total/distinct-visitor/date-range reporting after deployment.

## 12. Regression and cross-surface verification

~~~text
FOCUSED CTA TESTS        = NOT RUN — hard stop before code changes
EXISTING ANALYTICS TESTS = NOT RUN — no repository-side implementation change
FRONTEND TESTS/BUILD     = NOT RUN — Website/Store source repositories unavailable
CROSS-SURFACE GREEN      = NOT PROVEN
~~~

There is no implementation diff whose failures could be classified against a baseline. The isolated worktree contains only the blocked implementation report. The report itself passed whitespace validation before commit; no application test result is being represented as a feature result.

Required future RED → GREEN tests remain:

| Test | Required GREEN condition |
|---|---|
| RED-1/2/3 | Real Website, Wiki, and Store canonical anchor clicks each emit one canonical custom collector event |
| RED-4 | source_surface resolves to exactly website, wiki, or store |
| RED-5/6 | source_path and destination equal the real clicked page/anchor values |
| RED-7 | One physical click cannot produce two canonical ask_ai_click records through overlapping SDK/GTM paths |
| RED-8 | Analytics transport failure does not block /ask-ai/ navigation |
| RED-9 | WhatsApp/email/generic contact links do not emit canonical Ask AI semantics |
| RED-10 | Unknown host/path is excluded or explicitly unknown, never silently mapped to a known surface |

## 13. Counting and query contract after deployment

Use one source of truth, preferably the CamThink custom collector:

~~~text
TOTAL:
  count events where
    event_name = element_click
    track_category = contact
    track_type = ask_ai
    track_name = ask_ai

BY SURFACE:
  apply the same event filter
  derive source_surface from existing page hostname/path
  group by website, wiki, store

DISTINCT:
  use the selected analytics platform's visitor/global visitor identity
  report as analytics visitor UV, never CRM customer count

DATE:
  apply one explicit half-open UTC range [start, end)
~~~

Do not sum custom collector element_click with GA4 contact_click. If the selected report uses GA4, it must prove that duplicate Store GTM processing is removed or excluded before reporting.

## 14. Historical-continuity limitation

Historical continuity is explicitly out of scope for v1 and is not the implementation blocker. The prospective boundary is:

~~~text
CANONICAL TRACKING EFFECTIVE FROM DEPLOYMENT FORWARD
~~~

No historical counts or baseline were fabricated. Historical Analytics access is now partially available through the authenticated account, but only the Wiki production project is exposed; no claim is made that pre-deployment records are comparable to the prospective contract. The current host/path attribution rules are proven for current deployment only.

## 14.1. Authenticated Analytics follow-up

The user-provided login enabled a read-only check of `https://analytics.camthink.ai/notifications` and the linked Analytics views on 2026-09-15. The account scope is still incomplete for this issue:

| Check | Observed result | Evidence boundary |
|---|---|---|
| Visible project inventory | `GET /api/admin/projects` returned HTTP 200 with exactly one visible project: `wiki`, `production` | Project key and internal IDs were not retained in this report |
| Current data scope | UI shows `Camthink全站（1 个项目）`; the selectable project and table rows are `wiki` | No Website or Store project is available to this account |
| Existing event filter | User Records supports `点击页面元素（element_click）` | This confirms the existing event family is reportable |
| Current filtered visitor records | The UI shows `共 783 条` for the current `element_click` filter; the same read-only API query returned `total = 783` | This is a visitor-record total, not Ask AI clicks and not CRM customers |
| Canonical Ask AI historical evidence | One sampled visitor detail contained historical `element_click` records but no exact `contact / ask_ai / ask_ai` match | A single visitor sample is not a full-project zero claim |

This follow-up narrows the historical limitation from `authentication unavailable` to `partial authenticated visibility`. It does not establish three-surface historical continuity, does not reconstruct a historical Ask AI count, and does not remove the implementation hard stop: the authoritative Website and Store UI repositories/templates are still unidentified or inaccessible. No Analytics configuration or production data was changed.

## 15. Exact files changed

Only the following file was changed in this delivery:

- docs/engineering/tasks/issue80-ask-ai-cta-analytics-implementation.md

No Website, Wiki code, Wiki content, Store template, shared SDK, GTM, GA4, or ASK-AI application source file was modified. The Wiki local worktree and active r4 integration worktree were preserved.

## 16. Branch and artifact

This report was created in an isolated worktree from origin/main:

~~~text
WORKTREE = /Users/harryhua/Documents/GitHub/ask-ai/.worktrees/issue80-implementation-20260915
BRANCH   = codex/issue-80-implementation-20260915
BASE     = f4e67515af810840aa10fa800f0203c2ba290df0
~~~

The candidate branch will be pushed only with this blocked report. It does not contain an implementation.

## 17. Release relationship

Role B does not decide final r4 admission. Technically, this artifact is not ready for late r4 consideration because Website and Store source access is missing and no GREEN cross-surface evidence exists. The conservative engineering recommendation is:

~~~text
NEXT_RELEASE_RECOMMENDED
~~~

Role A may reconsider after the missing repositories are identified, the Store event path is made deterministic, and the full RED → GREEN matrix passes in an isolated candidate.

## 18. Remaining blockers and next gate

Remaining blockers:

1. Identify and provide access to the authoritative Website source repository/template.
2. Identify and provide access to the authoritative Store WordPress/WooCommerce source repository/template.
3. Resolve or explicitly gate Store duplicate GTM processing before using GA4 as a canonical report source.
4. Define the implementation-side unknown-host fail-safe and test it without introducing a competing surface taxonomy.
5. Run the required cross-surface RED → GREEN tests after source access is available.
6. Separately authorize any external production GTM/GA4 configuration/reconciliation; do not perform it as part of this branch.

Recommended next gate:

1. Role A/owners identify the two missing source repositories and confirm their baseline SHAs.
2. Re-run topology inspection in isolated worktrees.
3. Add only the frozen canonical anchor seam in each surface repository, reusing the existing Tracker contract.
4. Run surface-native tests/builds and the cross-surface event contract tests with all analytics transports intercepted in staging.
5. Obtain independent Role A review before any merge, production configuration, or deployment decision.

~~~text
NO PRODUCTION DEPLOY
NO PRODUCTION GTM MUTATION
NO PRODUCTION GA4 MUTATION
NO HISTORICAL-DATA FABRICATION
NO WIKI CONTENT MODIFICATION
NO INTERFERENCE WITH CURRENT R4 INTEGRATION BRANCH
~~~
