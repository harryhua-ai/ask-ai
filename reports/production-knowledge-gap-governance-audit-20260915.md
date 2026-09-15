# Production Knowledge Gap & Governance Audit — 2026-09-15

**Role:** Senior Knowledge Quality Investigator — AUDIT / ANALYSIS ONLY.
**Status:** READY FOR ROLE A REVIEW. No code, production, knowledge-source, or content changes were made. #73/#74 not closed.
**Production identity:** `v1.6.3-r3` @ `5eac2b2b84d63a5889d8cb229e40e2bb083745d5` (`https://wiki-data.camthink.ai`, `/health` cross-checked by the upstream export).
**Machine-readable artifact:** [`reports/data/production-knowledge-gap-audit-20260915.json`](data/production-knowledge-gap-audit-20260915.json) (all cluster definitions, conversation IDs, classifications, verification checks).

---

## 1. Objective and method

Two questions kept strictly separate:

- **#73 (content):** what knowledge content should be added / updated / consolidated / retired so observed user needs are answerable.
- **#74 (governance):** which observed failures are NOT content problems but retrieval / eligibility / authority / lifecycle / citation defects.

**Evidence base (authoritative input, read-only):** `customer_candidates.jsonl` (119 records), `classified_conversations.jsonl` (full `trace_summary` incl. rerank results), `production_conversations_snapshot.json`, `audit_stats.json`, `link_checks.json` (574-URL inventory), `benchmark_v1_alignment.json` — export of 2026-09-15T01:18Z, window 2026-08-31 → 2026-09-15.

**Terminology discipline:** *customer_candidate* = "no strong test/internal signal detected"; it does **not** prove a verified external customer. The 1308 test/internal records are used only as corroborating / regression evidence and never inflate demand priority (frequencies reported separately throughout).

**Unit of analysis:** all 119 customer_candidate records were individually reviewed (question, answer, sources, rerank trace), then clustered by semantic user need → **52 clusters**, each mapped to exactly one primary classification. Coverage: 119/119 records, one cluster each (verified programmatically; mapping in the JSON artifact).

**Fact verification (Section-11 discipline):** no "missing fact" was declared from answer omission alone. Every actionable cluster's claim was re-checked read-only on 2026-09-15 against: the `wiki-documents` repo main (raw markdown via GitHub), live `camthink.ai` pages, the KB URL inventory, and the in-export rerank traces. 12 verification checks are recorded in the artifact. Claims that could not be established are marked **UNPROVEN**, not guessed.

**Benchmark boundary:** no Benchmark v1 scoring performed or published; benchmark data used only for case-origin context.

## 2. Population

| Measure | Value |
|---|---:|
| Total conversations | 1427 |
| customer_candidate | 119 (widget-only; en 82 / zh 35 / zh-cn 2) |
| test/internal | 1308 |
| customer_candidate trace mix | rag 87 · task_clarify 14 · product_clarify 3 · social_reply 8 · reject_short 4 · override 2 · generation_error 1 |

Demand skews heavily to **NE503** (≈50% of product records), then NE302, NE301, NE101, NG4500, NeoMind/platform, and a company/commerce-policy tail.

## 3. Classification totals

| Primary classification | Clusters | Records in defect/content clusters |
|---|---:|---:|
| MISSING_KNOWLEDGE | 4 | 4 |
| INCOMPLETE_KNOWLEDGE | 4 | 4 |
| FRAGMENTED_KNOWLEDGE | 2 | 10 |
| STALE_KNOWLEDGE | 0 | 0 |
| RETRIEVAL_FAILURE | 2 | 9¹ |
| ANSWER_FAILURE | 1 | 1 |
| NOT_KNOWLEDGE_PROBLEM | 39 | 91 |

¹ One of the 9 (record `30…` "who are the owners") was actually answered satisfactorily from news pages and only corroborates the cluster; record-level retrieval failures = 8.

**STALE_KNOWLEDGE = 0** in this population: the stale-adjacent phenomena found (marketing price figures, 404 provenance URLs, possible NE301-FAQ repo/serving drift) are recorded under FRAGMENTED (K01), governance G-05, and the #71 linkage note respectively — none was a case of obsolete knowledge being served as current truth to a customer question.

## 4. Key inversions of prior assumptions (evidence over intuition)

- **Task Case A inverted:** "where is your head office" is **not** missing knowledge. The KB's ingested `camthink.ai/company/contact-us/` page contains the HQ address (*Software Park Phase III, Xiamen 361024, Fujian, China*) and "A Milesight sub-brand" — and it is retrievable (cited as `sources[].url` by 9 test records). For the HQ query the top-10 rerank was NE101 store pages and NE301 driver code at scores 0.016–0.029; the contact page did not rank. → **RETRIEVAL_FAILURE** (K12/G-02), content action NO_CONTENT_CHANGE.
- **"Factory reset" is not undocumented:** NE301 quick-start documents reset (double-press capture key + ~10 s long-press, verified on repo main). Record `7bf5…` was answered from firmware `.c` files instead. → RETRIEVAL_FAILURE.
- **NE503 price "conflict" resolved:** the live store page (re-checked 2026-09-15) shows **$1,049.00–$1,199.00 as a variant price range** (lens AF/zoom × 4GB/8GB). The ingested store snapshot carried only $1,049; blog pages carry $1,199 without variant context. → FRAGMENTED (K01), not stale.
- **Shipping policy exists but was never ingested:** `https://www.camthink.ai/policies/shipping-policy` returns 200; zero `/policies/` URLs exist among the KB's 574 inventoried URLs (while the warranty page IS ingested). → MISSING_KNOWLEDGE with governance cause AUTHORITATIVE_SOURCE_MISSING (K02/G-06).

## 5. ISSUE #73 — Knowledge Content Backlog

| ID | Domain | User need | Count (cust/test) | Gap type | Current evidence | Missing facts | Authoritative owner | Action | Priority | Confidence |
|---|---|---|---|---|---|---|---|---|---|---|
| K01 | ne503/commerce | NE503 price incl. configuration & procurement | 9 / 0 | FRAGMENTED | Store $1,049 vs blog $1,199; live page = variant range $1,049–$1,199, no per-variant map; record `e054…` asserted $1,199 (blog) as the price | per-configuration price mapping; store-canonical rule | Commerce/store + marketing blog | CONSOLIDATE_CANONICAL_SOURCE | **P0** | HIGH |
| K02 | commerce policy | International shipping / ordering | 1 / 4 | MISSING | Policy page live (200) but 0 `/policies/` URLs in KB; honest decline | shipping regions, ordering channel, costs | Commerce ops + ingestion scope | NEW_DOCUMENT (ingest) | **P1** | HIGH |
| K03 | integration | Third-party VMS/NVR (Frigate) compatibility | 1 / 9 | MISSING | "Frigate not mentioned in any available sources"; DeepStream documented; NE302 RTSP output documented, no NVR-consumption note | RTSP→third-party NVR integration note; VMS comparison | Wiki product docs | NEW_DOCUMENT | **P1** | HIGH |
| K04 | ne503/firmware | NE503 firmware download / release history | 1 / 1 | FRAGMENTED | `release-notes/firmware` covers NE101/NE301/NG4500 only (verified grep); NE503 firmware lives in system-flashing → meta-hailo-os Releases | NE503 section in canonical release-notes page | Wiki docs | UPDATE_EXISTING | **P1** | HIGH |
| K05 | ne302 spec | NE302 weight | 1 / 0 | INCOMPLETE | Overview has dims + environment, no mass (verified grep) | weight (g) | Product/wiki docs | UPDATE_EXISTING | P2 | HIGH |
| K06 | ne302 support | NE302 factory reset | 1 / 0 | INCOMPLETE | No reset procedure in NE302 docs (answer verified absence; NE301 contrast documented) | whether a reset gesture exists + procedure | Product/wiki docs | UPDATE_EXISTING (confirm hw first) | P2 | MEDIUM |
| K07 | hw integration | OV5640 module pinout/electricals; alarm-pin electricals; PoE class | 1 / 10 | INCOMPLETE | Partial pinout tables exist; answers flagged the rest as not documented | module datasheet electricals; alarm IO params; PoE class/cable limits | Hardware docs | UPDATE_EXISTING / publish annex or formalize decline | P2 | MEDIUM |
| K08 | compliance | IP67 test report (cert documents) | 1 / 0 | MISSING | Rating documented; no report in KB (answer verified) | cert summary / report access path | Compliance/quality + wiki | NEW_DOCUMENT if publishable, else NO_CONTENT_CHANGE | P2 | MEDIUM |
| K09 | solutions | Smart-agriculture solution content | 1 / 10 | MISSING | Only NeoMind **eval fixture** `scenario-agriculture-solution.json` stands in (see G-04) | public owned solution page | Solutions/marketing + NeoMind docs | NEW_DOCUMENT (conditional) | P2 | MEDIUM |
| K10 | neomind | NeoMind default credential / first-login flow | 1 / 12 | INCOMPLETE | Only password *policy* from `auth.rs`; NE301 default credential documented by contrast | first-login/credential setup (security review first) | NeoMind docs | UPDATE_EXISTING | P2 | MEDIUM |

### P0 / P1 detail

**K01 — NE503 price (P0).** *Demand:* 9 customer-candidate records in 15 days (7 en, 2 zh) including one procurement request with lead capture (`116…`). *Evidence:* 6 answers honestly reported the store/blog conflict; record `e054…` told a zh customer the price is **$1,199** citing the blog alone — $150 above store price and materially misleading. *Required contract:* NE503 price by configuration (lens × memory) expressible from ONE canonical commerce source; explicit "blog figures are not price authority"; volume-tier absence stated with sales routing. *Action:* store page expresses per-variant pricing (or a price annex it links); refresh the ingested store snapshot; update/de-contextualize blog figures; retrieval prefers the commerce source for price intent (governance G-03). *Test support:* 0 exact; related "price of NE301 + how to order + shipping" test question ×4.

**K02 — Shipping policy (P1).** *Demand:* "Do you ship internationally?" (`654f…`); test question asking price+order+shipping ×4 never gets the shipping half answered. *Contract:* ship-to regions, ordering channel, cost/lead-time expectations, link to the official policy page. *Action:* add the existing public page to ingestion scope; no new content invention needed.

**K03 — Third-party NVR/VMS integration (P1).** *Demand:* NE302+Frigate (`f233…`, same-session clarify `9ac1…`); ×9 test records on NG4500 VMS comparison can only answer "DeepStream". *Contract:* per product, documented video-output contracts plus an explicit third-party-NVR compatibility/integration note; NG4500 VMS comparison page. *Owner:* wiki application guides.

**K04 — NE503 firmware release notes (P1).** *Demand:* "Where can I download firmware" (`3117…` honestly declined for NE503). *Verified:* `7-release-notes/0-firmware.md` has zero NE503 mentions; the firmware and download location are documented at `3-software-guide/2-system-flashing.md` → `meta-hailo-os` Releases. *Action:* add an NE503 section to the canonical release-notes page.

### Top content additions
1. Ingest/author international shipping & ordering policy (K02).
2. Third-party NVR/VMS (Frigate) integration notes + NG4500 VMS comparison (K03).
3. Certification summary per product (K08 — only if cleared for publication).

### Top content updates
1. NE503 canonical pricing with per-configuration mapping (K01).
2. NE503 section in `release-notes/firmware` (K04).
3. NE302 weight in spec table (K05); NE302 reset procedure after hardware confirmation (K06).

### Content that should be retired
- Standalone $1,199 price figures on NE503 blog/integration pages (as *price statements*; keep only within variant context) — part of K01. No other retirement justified; STALE_KNOWLEDGE = 0.

### No-knowledge-change cases
91 records: by-design clarify prompts (17), social/small talk (10), correct off-topic rejects (3), transient generation_error (1), answered-ok product/spec clusters (33 clusters / 58 records), AUD-currency decline + typo disambiguation (K11), NG4500 "battery life" premise mismatch (K16b).

## 6. ISSUE #74 — Knowledge Governance Backlog

| ID | Governance cause | Belongs | Evidence | Proven by |
|---|---|---|---|---|
| G-01 | RETRIEVAL_FAILURE — source-code / internal artifacts outrank user-facing docs for how-to & commercial intents | ASK_AI_ENGINEERING | PROVEN | 7 conversations (below) |
| G-02 | RETRIEVAL_FAILURE — company/intent queries cannot rank the (already ingested) company page; secondary AUTHORITATIVE_SOURCE_MISSING (no dedicated About source) | ASK_AI_ENGINEERING | PROVEN | `cbaf…` "where is your head office" |
| G-03 | AUTHORITY_AMBIGUOUS + ELIGIBILITY_FAILURE — no store-canonical price rule; marketing blog served as price evidence | BOTH | PROVEN | K01 records |
| G-04 | ELIGIBILITY_FAILURE — internal eval fixtures (`/eval/fixtures/*.json`) retrievable and cited as solution authority | ASK_AI_ENGINEERING | PROVEN | `5fca…` (agriculture via fixture), `cbaf…` (fixture in sources) |
| G-05 | LIFECYCLE / CITATION — provenance URL rot after wiki-documents restructure (9 unique GitHub blob URLs 404, 40+ citation occurrences; served wiki URLs fine) | BOTH | PROVEN | link_checks + repo tree diff |
| G-06 | AUTHORITATIVE_SOURCE_MISSING — commerce policy pages outside ingestion scope (warranty in, shipping out) | KNOWLEDGE_PROCESS | PROVEN | `95`-record + 574-URL inventory |

**G-01 detail (top governance item).** 1. *Proof conversations:* `4823…` (reset → `device_service.c` etc. instead of quick-start doc), `f885…`/`a92b…` (NG4500 LLM → missed `deepseek-r1` page that record `22b5…` retrieved 3 days earlier), `8f77…` (custom camera → NeoMind internal `isolated.rs`/`recognizer.rs`/`builtin_types/ne301_camera.json`), `f1b0…` (where to buy NE302 → store page not retrieved; INFERRED, ingestion timeline unverifiable), `c922…` (NG4500 config → only NeoMind automation i18n json), `a985…` (price → `mongoose.c`/quaternion math), `1f4a…` (NE503 upgrade failure → only `CMakeLists.txt` while troubleshooting + flashing-recovery pages exist). 2. *Sources involved:* per above. 3. *Should have been authoritative:* wiki user docs / store pages (all in-corpus). 4. *Failed rule:* ranking/eligibility treats code and internal artifacts as first-class chunks for how-to/commercial intents; the F-1' rerank corrective (deployed v1.6.2, 09-12) did not fully resolve — `f885…` (09-13) and `4823…` (09-14) post-date it. 5. *Minimum correction:* narrow source-type eligibility/ranking rule (user docs & commerce > source code / eval artifacts for these intent families), verified against the 7 conversations; **no** new platform, ontology, taxonomy, or health framework. 6. ASK_AI_ENGINEERING. 7. Not covered by #71/413/422 or open UA issues. 8. PROVEN.

**G-05 detail.** The 9 dead URLs are all `github.com/camthink-ai/wiki-documents/blob/main/docs/6-neoeyes-ne503-series/4-application-guide/1-app-development/...` paths; the repo's NE503 `4-application-guide` now contains `2-cookbook`, `3-ai-assisted-dev.md`, `4-verified-apps.md`, `5-troubleshooting.md` — i.e., a restructure, while `wiki.camthink.ai` serving URLs resolve. Minimum correction: rebuild provenance URL mapping when the source repo restructures (re-sync refresh); distinct mechanism from #71 (which is serving-content staleness) but the same source-vs-serving family.

## 7. Diagnostic distinctions applied

- **Case A (head office):** inverted by evidence — knowledge existed and was indexed; failure is retrieval (G-02). No company FAQ written; no retrieval-bug claim without proof — the rerank trace is the proof.
- **Case B (obsolete SDK page):** not observed. The NE503 SDK cluster was answered from current resources; the only staleness-adjacent artifact is provenance-URL rot (G-05), not served content. No SDK FAQ written; no #71 duplicate opened.
- **Case C (authoritative doc exists, unrelated chunks retrieved):** confirmed in 7 conversations (G-01). Facts were NOT duplicated into new documents to work around ranking.
- **Case D (evidence retrieved, wrong answer):** one instance, K15 (`e39d…`): English question containing the product store URL answered with a Chinese-token reject template ("商城") — generation/URL-entity defect, knowledge correct (NE302 indoor positioning). No content changed to accommodate generation.

## 8. Existing-track mapping (no duplication)

- **#71 (stale serving):** no customer-candidate conversation attributed. One weak observation, UNPROVEN: NE301 FAQ absent from wiki-documents repo main while an i18n variant is inventoried in the KB and the serving URL exists; serving state not verifiable from the export (SPA). Recorded for the #71 owner to glance at; no new issue opened here.
- **INC_WEB_EMBED_413 / Embedding-422:** no customer-candidate conversation attributable. The single `generation_error` record (2026-09-02) matches the 5 such records in the full population and is not evidence of the 422 path.
- **Admin credential remediation:** out of scope; no interaction observed.
- **F-1' rerank corrective:** relevant prior art for G-01; see note above.

## 9. Test/internal cross-check (frequencies never merged into demand)

Cluster demand is reported as `customer/test` throughout: K01 9/0 · K02 1/4 · K03 1/9 · K04 1/1 · K07 1/10 · K09 1/10 · K10 1/12; answered-ok SDK cluster 3/18 (demand corroboration); test/internal records also show the same honest-decline behavior on shipping and VMS questions (regression-style repetition), which supports the gap being systematic rather than a one-off.

## 10. New-issue recommendation (NOT created)

One new engineering issue is recommended, covering G-01 + G-04 as a single fix surface:

> **Retrieval/citation eligibility: user-doc & commerce sources must outrank source code and internal eval artifacts for how-to/commercial intents.**
> Acceptance evidence: the 8 PROVEN retrieval/eligibility conversation IDs in this report; explicit non-goals: no new platform, no taxonomy redesign, no per-URL live checking.

## 11. Artifacts and auditability

- Report: `reports/production-knowledge-gap-governance-audit-20260915.md` (this file)
- Machine-readable artifact: `reports/data/production-knowledge-gap-audit-20260915.json` — 52 clusters with full conversation-ID lists, per-record metadata, classifications, backlog entries, 12 verification checks
- Source evidence (read-only, unchanged): `optimize/results/2026-09-15T09-18/` export (classified_conversations.jsonl etc.)
- Privacy: only opaque de-identified conversation UUIDs are reproduced; no emails, phone numbers, names, or credentials.

**STOP.** No content or engineering changes implemented. Returning `PRODUCTION_KNOWLEDGE_AUDIT = READY FOR ROLE A REVIEW`.
