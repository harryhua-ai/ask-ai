# Issue #80 — Ask AI CTA Analytics Discovery

**Investigation status:** PARTIAL / BLOCKED

**Issue:** https://github.com/harryhua-ai/ask-ai/issues/80

**Investigation date:** 2026-09-15 (Asia/Shanghai)

**Scope:** Website, Wiki, and Store public implementation; the Ask AI integration repository; the shared CamThink Tracker SDK; public GTM configuration; and the read-only analytics access boundary.

**Safety boundary:** Discovery only. No product code, GTM container, GA4 configuration, production deployment, taxonomy, CTA destination, or Ask AI semantic behavior was changed.

## 1. Executive conclusion

Issue #80 is not currently green. The shared tracking infrastructure is present on all three public surfaces, but the frozen canonical CTA is not present in the current public crawl or in the inspected Wiki source:

~~~html
<a href="/ask-ai/" data-track="contact" data-type="ask_ai">Ask AI</a>
~~~

The current runtime therefore cannot be proven to emit the requested real-CTA event element_click with track_category=contact, track_type=ask_ai, and track_name=ask_ai on Website, Wiki, or Store. A fully intercepted synthetic DOM probe proved that the existing CamThink Tracker maps those attributes correctly; it did not prove that a production CTA currently carries them.

The three-surface topology is:

~~~text
Website (www.camthink.ai, non-/store path) ─┐
Wiki (wiki.camthink.ai)                      ├─ CamThink Tracker 0.4.0
Store (www.camthink.ai/store/)              ┘    └─ custom collector
       └─ GTM-WRP2RQPS ─ GA4 Measurement ID G-XBWTN65KKB
~~~

The custom collector and GA4 are separate event destinations. The same user action can be represented as a custom element_click and, through the public GTM mapping, as a GA4 contact_click. They must not be summed as two canonical clicks. Store additionally has two public GTM bootstrap snippets and produced two blocked GA4 page-view requests in controlled reloads, so duplicate tracking is an existing supporting risk.

Historical counts, earliest recoverable date, and cross-surface distinct visitors remain UNPROVEN: the analytics dashboard is login-protected and no authorized read-only query result or export was available. The final metric must use one analytics source of truth and call the distinct-user measure “analytics visitor UV / distinct visitor identity,” not CRM customers.

## 2. Frozen contract and metric boundary

The following contract was treated as immutable for this investigation:

| Field | Required value | Boundary |
|---|---|---|
| Target element | Canonical Ask AI CTA link | Do not substitute an unlabeled widget button or generic contact link |
| href | /ask-ai/ | Destination is frozen |
| data-track | contact | Category is frozen |
| data-type | ask_ai | Type is frozen |
| Canonical event | element_click | Existing CamThink Tracker event |
| track_category | contact | Comes from data-track |
| track_type | ask_ai | Comes from data-type |
| track_name | ask_ai | Existing SDK fallback is data-type when data-track-name is absent |

The requested measurement is total canonical clicks, distinct visitors supported by the selected analytics identity, Website/Wiki/Store breakdown, and a specified date range. A click means Ask AI intent/entry only. It is not proof of a chat start, lead, purchase, conversion, or CRM customer identity. No prompt, conversation content, name, email, phone, or address is in scope.

## 3. Evidence ledger

| Finding | Status | Evidence and boundary |
|---|---|---|
| Ask AI integration backend is in this repository | PROVEN | README.md, docs/integration/CAMTHINK_ASK_AI_WEBSITE_INTEGRATION.md, and config/sites.yaml; this repo contains the widget/backend integration, not the three surface templates |
| Website, Wiki, and Store site IDs are camthink-website, camthink-wiki, and camthink-store | PROVEN | config/sites.yaml and public runtime configuration |
| Active Store URL is https://www.camthink.ai/store/ | PROVEN | config/sites.yaml and successful public response; store.camthink.ai does not resolve in the current check |
| CamThink Tracker is loaded by all three surfaces | PROVEN | Public HTML/runtime inspection; Wiki source src/theme/Root.js; Store inline HTML; Website deployed Next chunk |
| Shared tracker version is 0.4.0 | PROVEN | Public SDK https://analytics.camthink.ai/sdk/tracker.umd.js, response inspected on 2026-09-15 |
| Current public crawl contains the frozen canonical CTA | PROVEN: NO | 135 Website sitemap URLs and the inspected Wiki/Store pages had zero /ask-ai/ hrefs and zero data-type="ask_ai" matches |
| Current Widget launcher is the frozen CTA | PROVEN: NO | Rendered Website/Store launcher is a button.ask-ai-launcher-pill with no frozen attributes; Wiki renders an untagged mini entry |
| SDK can map the frozen attributes to element_click | PROVEN | Fully route-blocked synthetic DOM probe; mapping only, not production CTA existence |
| Current real canonical production CTA emits the frozen event | UNPROVEN | No qualifying real CTA was found to click |
| GA4 contact_click mapping exists | PROVEN | Public GTM container configuration; one initial Store probe also observed the mapping, subject to the probe limitation in Section 18 |
| Store has duplicate GTM bootstrap markup | PROVEN | Two head bootstrap snippets, two ns.html iframes, and two blocked GA4 page-view POSTs in controlled reloads |
| Historical event counts and earliest date | UNPROVEN | Analytics dashboard redirects to /auth/login; no authorized query/export was supplied |
| CRM/customer linkage for distinct clickers | UNPROVEN | SDK supports optional user_id, but no CRM identity linkage or authoritative customer definition was accessible |

## 4. CTA inventory by surface

| Surface | Current public route | Intended site ID | Observed CTA/tag state | Assessment |
|---|---|---|---|---|
| Website | https://www.camthink.ai/ and non-/store/ paths | camthink-website | Widget launcher button.ask-ai-launcher-pill, aria label “Open the Ask AI assistant”; no href, data-track, or data-type. Static crawl of 32 page, 62 post, and 41 product sitemap URLs found no canonical Ask AI tag. | MISSING TAG — canonical CTA source ownership is unavailable |
| Wiki | https://wiki.camthink.ai/docs/ | camthink-wiki | Docusaurus source injects the Widget. Docs homepage renders section.ask-ai-mini; no canonical Ask AI anchor or frozen attributes. | MISSING TAG — source is available locally, but no canonical CTA was found |
| Store | https://www.camthink.ai/store/ and product paths | camthink-store | WordPress/WooCommerce page has WhatsApp/email contact anchors only; Widget launcher is untagged. Store product sitemap crawl found no canonical Ask AI tag. | MISSING TAG — source repository is unavailable |

Existing data-track="contact" elements are not evidence of Ask AI tracking. They are currently associated with ordinary contact types such as whatsapp and email.

## 5. Current implementation and exact source locations

### Ask AI repository

Repository: /Users/harryhua/Documents/GitHub/ask-ai

Relevant files:

- config/sites.yaml: site identity and allowed-origin contract. Store is the /store/ path on www.camthink.ai; the old store.camthink.ai hostname is not authoritative.
- docs/integration/CAMTHINK_ASK_AI_WEBSITE_INTEGRATION.md: current v3.0 integration guide, production API, and three site_id values.
- README.md: backend/widget/Admin scope.

Repository search for data-track, data-type, element_click, track_category, track_type, track_name, and the frozen Ask AI markup found no surface CTA implementation in this repository. This is PROVEN for the inspected revision, not proof about unavailable Website/Store source repositories.

### Wiki

Repository: /Users/harryhua/Documents/GitHub/wiki-documents

- src/theme/Root.js: production tracker SDK injection, tracker config, Widget injection, custom events, and route-driven page calls.
- src/analytics/track.js: pre-initialization event queue and tracker delegation; no CTA tags.
- src/analytics/consent.js: default accepted consent; a stored rejected consent prevents tracker injection.
- docusaurus.config.js: production-only GTM container GTM-WRP2RQPS and production Widget enablement.

The inspected local Wiki worktree is dirty and was not modified. Relevant source matched the inspected origin/main revision for these files; no source edit was made.

### Website

No Website source repository was available in the configured GitHub organization checkout. The current public implementation was inspected through deployed HTML, browser runtime, and the Next.js layout chunk:

~~~text
https://www.camthink.ai/_next/static/chunks/app/layout-74c4402154bbfdf8.js
~~~

The deployed homepage returned 200 with deployment identifier 8b9874b17fce-20260914063033 in the HTML. The exact source template/owner remains UNPROVEN.

### Store

No Store source repository was available. The current public implementation was inspected through WordPress/WooCommerce HTML and runtime. The public HTML identifies the tracker script as tracker.umd.js?ver=0.4.0 and contains inline initialization under script#camthink-analytics-js; the exact theme/plugin source owner remains UNPROVEN, although the duplicate GTM markup is visible and the page exposes the duracelltomi-google-tag-manager plugin version 1.22.4.

## 6. SDK behavior and real event path

The public CamThink Tracker SDK (camthink-web, schema version 1.0, SDK version 0.4.0) attaches a capture-phase document click listener. Its selector includes anchors, buttons, role buttons, and elements with [data-track], [data-track-name], or [data-ct-action].

For the closest clicked element, the SDK emits event_name: "element_click" and derives:

~~~text
track_category <- data-track
track_name     <- data-track-name ?? data-type ?? ""
track_type     <- data-type ?? ""
~~~

It also records existing element/page/context fields and optional analytics identity fields. It POSTs batches to:

~~~text
https://analytics.camthink.ai/collect/v1/events
~~~

The SDK sends an automatic page_view on initialization, supports an explicit page() call, batches by default, and uses sendBeacon on pagehide.

The frozen anchor would therefore be correctly mapped by the existing SDK without a new event name or new taxonomy. The missing capability is surface-owned canonical markup, followed by authorized measurement validation.

## 7. Sanitized runtime payload evidence

The following is a shape-preserving, identifier-redacted result from a fully intercepted Store probe. It is included to show the existing mapping; it is not a production CTA event.

~~~json
{
  "event_name": "element_click",
  "event_time": "[redacted]",
  "event_id": "[redacted]",
  "page": {
    "path": "/store/",
    "title": "Shop All | Edge AI Hardware - CamThink",
    "url": "https://www.camthink.ai/store/#issue80-probe"
  },
  "properties": {
    "track_category": "contact",
    "track_type": "ask_ai",
    "track_name": "ask_ai",
    "href": "#issue80-probe",
    "tag_name": "A"
  },
  "context": {
    "sdk_name": "camthink-web",
    "schema_version": "1.0",
    "sdk_version": "0.4.0"
  },
  "identity": {
    "visitor_id": "[redacted]",
    "global_visitor_id": "[redacted]",
    "session_id": "[redacted]"
  }
}
~~~

The synthetic probe used a fragment URL to avoid navigation. It proves attribute-to-event mapping and does not prove an existing qualifying anchor in production.

## 8. Surface-specific implementation evidence

### Website

window.CamthinkTracker was present. The Widget used siteId: "camthink-website" and rendered button.ask-ai-launcher-pill. A controlled click on that real Widget launcher, with all relevant analytics routes blocked before reload, produced one unlabeled CamThink element_click:

~~~text
element_aria_label: Open the Ask AI assistant
element_classes: ask-ai-launcher-pill
tag_name: button
track_category: ""
track_type: ""
track_name: ""
~~~

The Widget transitioned to its mini entry and did not navigate to /ask-ai/. This is PROVEN evidence of Widget interaction instrumentation, not canonical CTA tracking.

### Wiki

Root.js injects the Tracker with site_id-appropriate Widget configuration (camthink-wiki). The docs homepage uses an automatic section.ask-ai-mini entry. It has no frozen anchor. A route-blocked reload captured two custom collector page_view events and no canonical click; the two page views are explained by SDK auto page view plus Root.js calling CamthinkTracker.page() on Docusaurus location changes.

### Store

The tracker is initialized inline with auto_track.page_view: false and an explicit CamthinkTracker.page({page_type:"page",content_id:0}). The Widget uses camthink-store. Store contact anchors are WhatsApp/email, not Ask AI. A fully intercepted synthetic mapping probe produced the sanitized payload in Section 7.

## 9. GTM and GA4 mapping

The public GTM container GTM-WRP2RQPS is loaded by Website, Wiki, and Store. Its public container configuration reads the nearest [data-track] and [data-type] attributes.

The existing contact_click tag maps, among other fields:

~~~text
contact_type <- data-type
track_group  <- data-track
target_url   <- clicked href
page_path/page_url/lead fields <- current page and element context
~~~

The observed Measurement ID is G-XBWTN65KKB. This is public configuration, not a credential. The exact GA4 property/stream identity beyond this Measurement ID was not independently accessible.

This means a future canonical anchor would be consumed by two existing paths:

1. CamThink Tracker: canonical element_click to the custom collector.
2. GTM: existing contact_click to GA4.

The second path must not be counted as an additional canonical Issue #80 click. The report/query owner must select one source of truth, preferably the custom collector event contract already frozen by the issue, and explicitly exclude or reconcile the noncanonical GA4 representation.

## 10. Duplicate and loss risks

| Risk | Status | Impact |
|---|---|---|
| Missing canonical attributes on all three surface CTAs | PROVEN | Real canonical element_click/contact/ask_ai cannot be confirmed |
| Widget button is instrumented but unlabeled | PROVEN | Unlabeled Widget opens must not be mixed into canonical CTA counts |
| Website/Wiki/Store share a GA4 Measurement ID through GTM | PROVEN | Cross-surface GA4 segmentation is possible only with reliable path/host or dimensions |
| Same action can produce custom element_click and GA4 contact_click | PROVEN | Summing destinations inflates click totals |
| Store has duplicate GTM bootstrap markup | PROVEN | Duplicate GA4 page views observed; duplicate contact-click behavior requires authorized post-remediation validation |
| Wiki SDK auto page view plus explicit page() | PROVEN | Two Wiki page views observed on initial load; page-view metrics are contaminated unless deduplicated |
| Wiki rejected consent prevents SDK injection | PROVEN | Some Wiki visits may produce no custom collector events |
| Pagehide/beacon/keepalive delivery | PROVEN capability, UNPROVEN end-to-end | Navigation can preserve events, but delivery rate was not measured with historical data |
| Browser cookie/storage restrictions | INFERRED from identity design | Cross-surface global visitor deduplication will not be perfect for all browsers/consent states |
| User-ID bridge on signed-in Website users | PROVEN code path, UNPROVEN business meaning | Optional analytics user_id must not be described as CRM customer identity |

## 11. Surface attribution and identity semantics

The current event payload has page path/URL but no explicit site_id or surface field in the inspected element_click properties. The existing URL topology is sufficient for current public routes:

| Surface | Current derivation | Status |
|---|---|---|
| Wiki | hostname wiki.camthink.ai | PROVEN |
| Store | hostname www.camthink.ai and path starts /store/ | PROVEN |
| Website | hostname www.camthink.ai and path does not start /store/ | PROVEN |

The apex camthink.ai currently redirects to www.camthink.ai. Do not encode surface into data-type; preserve data-type=ask_ai. An explicit stable surface/site_id dimension is only a future fallback if host/path stops being authoritative. Adding it is outside this discovery task.

The custom tracker identity model exposes visitor_id, global_visitor_id when cross-project scope is enabled, session_id, and optional user_id. The current configuration uses the global scope key camthink and cookie domain .camthink.ai. This supports an analytics distinct-visitor metric, subject to consent, cookie, browser, and storage limitations. It does not prove CRM linkage or a count of real customers.

## 12. Historical measurement availability

https://analytics.camthink.ai/ redirects to an authenticated dashboard login. Public frontend bundles expose protected routes including:

~~~text
/admin/overview/stats
/admin/overview/daily-trend
/admin/overview/top-pages
/admin/visitors
/admin/identities
~~~

The dashboard UI includes visitor UV (visitor_count), sessions, identified users, page views, and date-range filters. Unauthenticated requests returned the SPA shell rather than data. No credentials were guessed or used, and no production data was mutated.

Therefore the following remain UNPROVEN:

- earliest date with a canonical element_click/contact/ask_ai event;
- historical total canonical clicks;
- Website/Wiki/Store historical breakdown;
- historical distinct visitor count and cross-surface deduplication quality;
- historical duplicate contamination from GTM or Wiki page calls;
- whether the frozen taxonomy has historical continuity after the Umami-to-CamThinkTracker migration.

Required follow-up access is a read-only analytics role/token or an exported query result covering one UTC date window and the three public surface scopes. Project keys and identity values do not need to be included in the report.

## 13. Missing capability and likely root cause

The missing capability is not an Ask AI backend API or Widget API feature. It is the absence of a surface-owned canonical link carrying the frozen analytics attributes, plus the lack of authorized historical query access.

Likely ownership split:

- Website: Website template/layout owner must place the canonical CTA in the intended navigation/CTA locations.
- Wiki: Wiki theme/layout owner must place the canonical CTA where the product requirement intends it; the existing Widget mini entry is a separate interaction.
- Store: WordPress/WooCommerce theme/template owner must place the canonical CTA; existing WhatsApp/email contact anchors are separate.
- Shared analytics: analytics/GTM owner must reconcile the existing GA4 contact_click mapping and Store duplicate bootstrap.
- Reporting: analytics owner must query historical counts and define the one source of truth.

The exact Website and Store source repositories are unavailable in the current workspace, so source-level ownership and change files for those two surfaces are UNPROVEN.

## 14. Minimum remediation boundary

The smallest implementation capable of satisfying the frozen contract is:

1. Add or repair one intended canonical Ask AI link per surface with exactly the frozen href, data-track, and data-type values.
2. Keep the existing CamThink Tracker path as the canonical Issue #80 event source.
3. Keep surface attribution derived from current host/path unless an owner proves that topology is changing.
4. Query one authorized analytics source for historical and post-change counts; do not sum custom collector and GA4 users/events.
5. Treat Widget launcher clicks as a separate unlabeled interaction unless a future approved contract explicitly changes that semantic.

Supporting work may be required to remove Store’s duplicate GTM bootstrap and to prevent the GA4 contact_click representation from contaminating the canonical report. Those are not part of an automatically authorized implementation.

## 15. Required supporting decisions and access

Role A / product or analytics owner must confirm:

- exact intended placement of the canonical CTA on each surface;
- whether “all three surfaces” means one CTA per surface or every repeated CTA instance;
- the authoritative analytics source and exact UTC date range;
- whether GA4 contact_click is a supporting mirror or must be excluded from Issue #80 reporting;
- whether Store duplicate GTM bootstrap is in scope for cleanup;
- the approved read-only analytics role/token or an exported result for historical validation;
- acceptance treatment for anonymous visitors, rejected Wiki consent, and browsers that block cross-site cookies.

## 16. Change boundary

### Expected changes after explicit implementation approval

- Website source/template or deploy artifact: add the frozen canonical anchor at the approved placement.
- Wiki source/layout: add the frozen canonical anchor at the approved placement.
- Store WordPress/WooCommerce theme/template: add the frozen canonical anchor at the approved placement.
- Report/query configuration: read-only validation of canonical element_click and distinct analytics visitors.

### Required supporting changes only if separately approved

- GTM container trigger/tag/report reconciliation for the existing GA4 contact_click path.
- Store duplicate GTM bootstrap cleanup.
- Analytics query/dashboard view that segments Website/Wiki/Store by current host/path.
- Shared SDK/collector changes only if a controlled real-CTA test proves the existing path cannot satisfy the frozen contract.

### Explicitly forbidden within Issue #80 discovery

- changing Ask AI Widget behavior, API, prompt, or entry semantics;
- changing /ask-ai/ destination;
- inventing or renaming an event or taxonomy field;
- encoding surface into data-type;
- adding PII, prompts, conversation text, or CRM enrichment;
- changing production GTM/GA4 configuration or deploying surface changes;
- claiming historical counts, earliest date, or customer counts without authorized analytics evidence.

## 17. RED → GREEN acceptance probes

These are future implementation/acceptance probes, not changes performed during this discovery.

| Test | RED condition | GREEN condition |
|---|---|---|
| TEST-1 Website | Approved real Website CTA is absent, untagged, or not an anchor | Real rendered anchor has exact frozen href, data-track, and data-type; click stays on intended path |
| TEST-2 Wiki | Approved real Wiki CTA is absent or untagged | Same exact frozen markup on the approved Wiki placement; Widget mini entry remains a separate interaction unless explicitly re-scoped |
| TEST-3 Store | Approved real Store CTA is absent or untagged | Same exact frozen markup on the approved Store placement; WhatsApp/email links remain distinct |
| TEST-4 Event contract | No event, wrong event name, or any wrong frozen field | Exactly one custom collector element_click for the real click with track_category=contact, track_type=ask_ai, track_name=ask_ai |
| TEST-5 Count source | Report combines destinations or has no date definition | One named source of truth, one UTC date range, and count equals canonical event rows only |
| TEST-6 Distinct visitors | Uses CRM customers or sums incompatible identities | Uses the selected analytics visitor identity (visitor_id/global_visitor_id semantics as documented) and labels it analytics visitor UV |
| TEST-7 Breakdown | Surface is inferred from mutable taxonomy or cannot be separated | Website/Wiki/Store are segmented by authoritative current host/path without changing data-type |
| TEST-8 Duplicate transport | Duplicate custom events or GA4 mirror is counted as a second canonical click | One canonical custom event per real CTA click; GA4 mirror is explicitly reconciled/excluded from the Issue #80 count |
| TEST-9 Delivery | Navigation drops the event | Normal click/navigation preserves delivery via the existing keepalive/beacon path; no destination change |
| TEST-10 Privacy | Payload includes PII or prompt/conversation content | Payload contains only the existing event/page/context/identity fields and no name, email, phone, address, prompt, or conversation content |

All RED → GREEN probes should first run in a staging/test container with analytics routes observed and captured. Production verification requires explicit authorization and a defined maintenance window.

## 18. Evidence limits, accidental probe write, and final disposition

### Evidence limits

- Public runtime and static HTML prove current deployed behavior, not unavailable source ownership.
- Synthetic attribute probes prove SDK/GTM mapping only; they do not create evidence that a real CTA exists.
- Dashboard route discovery proves that query surfaces exist behind authentication, not that historical data contains the requested event.
- Same GA4 Measurement ID proves observed collection convergence, not independent proof of the underlying GA4 property/stream configuration.

### Probe integrity note

The first controlled Store synthetic probe blocked the custom collector POST but did not yet block the GA4 GET transport. One synthetic GA4 contact_click request therefore escaped. It used the fragment-based synthetic target and was not a user action. The limitation was identified immediately; all subsequent probes blocked both the custom collector and GA4 routes before reload, and no further probe writes were allowed. This must be excluded from any production metric or historical count.

### Final disposition

~~~text
ISSUE_80_DISCOVERY = PARTIAL / BLOCKED
~~~

The infrastructure is sufficiently understood to define the minimal remediation, but the issue cannot be marked complete because the frozen CTA is missing on all inspected surfaces and the required historical analytics query is blocked by missing read-only access. No implementation or deployment was performed.

## Appendix A — Reproducibility references

Observed public endpoints and references:

- Website: https://www.camthink.ai/
- Wiki: https://wiki.camthink.ai/docs/
- Store: https://www.camthink.ai/store/
- Shared SDK: https://analytics.camthink.ai/sdk/tracker.umd.js
- Custom collector: https://analytics.camthink.ai/collect/v1/events
- GTM container: GTM-WRP2RQPS
- Observed GA4 Measurement ID: G-XBWTN65KKB
- Analytics dashboard: https://analytics.camthink.ai/ → authenticated login

Sensitive public project-key values and all event/visitor/session identifiers are intentionally redacted.

## ROLE A EVIDENCE-GATE FOLLOW-UP

**Follow-up date:** 2026-09-15 (Asia/Shanghai)

This section appends the evidence-gate completion results to the original discovery record. The original evidence and its limitations are retained above.

### Gate A — remote artifact verification

| Item | Result |
|---|---|
| LOCAL SHA | 57aba0457ac6e4a4423072cc87cd6bf87e395f33 |
| REMOTE SHA | 57aba0457ac6e4a4423072cc87cd6bf87e395f33 |
| BRANCH | codex/issue-80-cta-analytics-discovery-20260915 |
| BASE SHA | f4e67515af810840aa10fa800f0203c2ba290df0 |
| AHEAD/BEHIND vs origin/main | ahead 10, behind 0 |
| REPORT PATH | docs/engineering/tasks/issue80-ask-ai-cta-analytics-discovery.md |
| REMOTE VERIFICATION | PASS — git ls-remote resolved the branch to the same SHA |

The local SHA was recovered without rewriting or recreating the original discovery history. The branch was initially absent from origin; it was subsequently pushed as the existing branch. The original commit remains the report’s first commit. This follow-up is an appended report update and will have its own later commit.

### Gate B — analytics evidence

~~~text
ANALYTICS_EVIDENCE_GATE = BLOCKED
~~~

Read-only checks performed:

- The dashboard at https://analytics.camthink.ai/ is an authenticated SPA and redirects users to the login surface.
- Known protected read-only routes such as /api/admin/overview/stats, /api/admin/visitors, and /api/admin/identities returned Unauthorized without authentication.
- Environment variable names and the Ask AI repository .env key names were inspected without reading values; no Analytics/GA4 credential variable was available.
- No login was attempted with guessed credentials, and no collector/GA4 endpoint was called with a write method.

Historical evidence was not obtained. The following exact query/report outputs remain required from an authorized read-only Analytics role or an equivalent export:

1. **Canonical event identity and earliest date:** filter custom collector records by event_name = element_click and properties track_category = contact, properties track_type = ask_ai, properties track_name = ask_ai; return the minimum event timestamp and the event count. Run the same date-bounded query without the three property filters to show whether other element_click records exist.
2. **GA4 relationship:** for the same UTC date range, query event_name = contact_click and return contact_type, track_group, target_url, page_path, page_url, and lead_type. Compare, do not add, this result to the custom collector result.
3. **Historical total:** for the exact Role A-selected half-open UTC range [start, end), return canonical custom event count grouped by event date.
4. **Distinct visitors:** for the same range and canonical event filter, return distinct global_visitor_id where present, plus the documented fallback behavior for visitor_id when global_visitor_id is absent. Report this as analytics visitor UV, not customer count.
5. **Surface breakdown:** for the same range, group the canonical event by existing page hostname and page path/page URL. Validate Wiki by wiki.camthink.ai, Store by www.camthink.ai plus /store/ path, and Website by www.camthink.ai excluding /store/. No new dimension is requested.
6. **Routing identity:** report the observed project/property/stream/application identity for each source without exposing project keys or user identifiers, and confirm whether the common GA4 Measurement ID maps to one property/stream or only reflects common routing configuration.
7. **Continuity check:** compare any pre- and post-migration records around the Umami-to-CamThinkTracker change and report whether the frozen canonical fields are historically queryable. If no canonical records exist, return zero rows rather than infer continuity.

An exported report is sufficient if it contains the query date range, event filters, counts, distinct-visitor definition, existing attribution fields, and the source/property identity needed to prevent cross-source double counting. It must not contain credentials, project-key values, PII, prompts, or conversation text.

Remaining acceptance criteria blocked by this gate: historical total, earliest trustworthy Ask AI event date, historical Website/Wiki/Store split, historical analytics distinct-visitor count, and historical continuity. Current runtime topology and SDK mapping are not substitutes for these historical results.

### Gate C — narrow CTA inventory confirmation

| SURFACE | Ask AI entry exists? | DOM type | destination | data-track | data-type | tracker listener applicable? | GTM applicable? | canonical CTA already present? |
|---|---|---|---|---|---|---|---|---|
| Website | YES — Widget only | button.ask-ai-launcher-pill | no /ask-ai/ navigation; opens Widget UI | absent | absent | YES — existing SDK captures the button | YES — container loaded, but current button lacks canonical attributes | NO |
| Wiki | YES — Widget mini entry only | section.ask-ai-mini with controls | no /ask-ai/ navigation observed | absent | absent | YES when consent permits SDK injection; otherwise consent-gated | YES — container/config path exists, but current mini entry lacks canonical attributes | NO |
| Store | YES — Widget only | button.ask-ai-launcher-pill | no /ask-ai/ navigation; opens Widget UI | absent | absent | YES — existing SDK captures the button | YES — container loaded, but current button lacks canonical attributes | NO |

The public Store page also has data-track = contact anchors for WhatsApp and email. Those are not Ask AI entries. The Widget launcher/mini entry and the frozen anchor are separate semantic objects; none of the current Widget controls satisfy the canonical CTA contract.

### Gate D — duplication analysis without production writes

| Surface | Existing duplication mechanism | Effect on page_view | Effect on canonical element_click/contact analytics | Classification |
|---|---|---|---|---|
| Store | WordPress public HTML contains an inline GTM bootstrap and a second GTM bootstrap from the visible GTM plugin/theme integration; two matching noscript containers are also present | PROVEN — two blocked GA4 page-view POSTs were observed in controlled reloads | LIKELY for the GA4 mirror if a future canonical anchor is present: two GTM container instances can independently evaluate the same gtm.linkClick and fire the existing contact_click tag. Duplicate custom collector element_click is UNPROVEN because only one Tracker script/listener was observed and no real canonical CTA exists to test. | PROVEN page-view duplication; LIKELY GA4 CTA duplication; custom event duplication UNPROVEN |
| Wiki | SDK auto page_view plus explicit Root.js CamthinkTracker.page() on location effect | PROVEN — two custom collector page_view events and two blocked GA4 page-view requests were observed on initial load | NOT APPLICABLE to element_click for this mechanism: page() emits page_view and does not register a second click listener. Broader duplicate SDK injection is UNPROVEN, but the inspected Root.js init is guarded and no second click listener was established. | PROVEN page-view duplication; element_click duplication NOT APPLICABLE from this cause |
| Website | No equivalent duplicate Tracker/GTM bootstrap was observed in the inspected public runtime; exact source repository is unavailable | UNPROVEN end-to-end; no duplicate page-view evidence was observed in the controlled runtime available | UNPROVEN — no real canonical CTA exists to test and source ownership is unavailable | UNPROVEN |

The Store conclusion is deliberately split: duplicate GTM processing is a real likely risk for the noncanonical GA4 contact_click mirror, but it is not evidence that the custom collector currently emits duplicate canonical element_click events. No additional production probe was run.

### Historical continuity and attribution

~~~text
HISTORICAL_CONTINUITY = UNPROVEN
SURFACE_ATTRIBUTION = CURRENT ROUTE DERIVATION PROVEN; HISTORICAL VALIDATION BLOCKED
~~~

Current route derivation is stable and already available in existing page fields:

- Wiki: hostname wiki.camthink.ai.
- Store: hostname www.camthink.ai with path prefix /store/.
- Website: hostname www.camthink.ai with no /store/ prefix.

The current custom collector payload does not expose an explicit surface/site_id property on element_click. No new dimension is proposed. Historical attribution still requires the authorized query in Gate B. The common GA4 Measurement ID was observed on all three surfaces, but property/stream identity and historical routing were not accessible. The Umami-to-CamThinkTracker migration further prevents an unverified continuity claim.

### Change surface matrix

| Surface/configuration | Discovery disposition | Smallest future topology |
|---|---|---|
| Website | CHANGE REQUIRED | Add the frozen canonical anchor in the approved Website template/layout; exact source repository is still unavailable |
| Wiki | CHANGE REQUIRED | Add the frozen canonical anchor in the approved Docusaurus layout/theme location |
| Store | CHANGE REQUIRED | Add the frozen canonical anchor in the approved WordPress/WooCommerce template |
| Shared CamThink Tracker | NO CHANGE | Existing 0.4.0 SDK already maps the frozen attributes |
| GTM/GA4 | UNPROVEN / supporting review required | Do not change during Discovery; separately reconcile GA4 contact_click reporting and Store duplicate bootstrap if authorized |
| ASK-AI repo | NO CHANGE | Current repository owns integration/widget/backend configuration, not the missing surface CTA markup |

No row above authorizes implementation. The first three rows identify where the smallest future implementation would belong; the supporting rows identify evidence/cleanup gates, not approved changes.

### Final Role B verdict

~~~text
ISSUE_80_DISCOVERY = PARTIAL / BLOCKED
IMPLEMENTATION_AUTHORIZED = NO
~~~

Remaining blockers:

1. No qualifying canonical CTA is currently present on Website, Wiki, or Store.
2. Website and Store source repositories/templates are unavailable for source-level ownership confirmation.
3. Analytics historical evidence is blocked by authentication: no earliest date, total, surface split, distinct visitor UV, or continuity result is proven.
4. Exact GA4 property/stream identity and the historical relationship between custom element_click and GA4 contact_click remain unverified.
5. Store duplicate GTM bootstrap requires an authorized cleanup/acceptance decision before GA4 CTA reporting can be trusted.

Recommended next gate:

1. Provide read-only Analytics access or a redacted export satisfying the seven queries in Gate B.
2. Have Role A freeze CTA placement and the one-source-of-truth reporting rule without changing the frozen markup contract.
3. Obtain surface-owner source access, add only the frozen anchor after explicit implementation authorization, and validate in staging with all analytics transports blocked/observed.
4. Re-run the RED → GREEN probes in Section 17, then perform any separately authorized production verification.
