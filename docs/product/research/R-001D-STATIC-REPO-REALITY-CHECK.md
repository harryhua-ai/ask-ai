# R-001D — Static Repo Reality Check

**Status:** STATIC ARCHITECTURE REALITY ESTABLISHED — PRODUCTION RECONCILIATION PENDING  
**Repository:** `harryhua-ai/ask-ai`  
**Research branch:** `research/r001-knowledge-retrieval-architecture`  
**Engineering baseline:** `main@fbbf6530935d917c7729c58e2c4c9f6e109ebb70`  
**Date:** 2026-09-08  
**Production evidence:** NONE  
**Implementation authorization:** NONE  
**Production mutation:** NONE  
**Benchmark mutation:** NONE

## 1. Purpose

R-001D Part A grounds R-001C in the actual accepted ASK-AI repository before post-I-002 production deployment and Benchmark reconciliation.

This document answers static architecture questions only:

```text
What identity contracts exist now?
What knowledge representation exists now?
What is actually persisted in the ledger and vector index?
What lifecycle and reconciliation semantics already exist?
Where does retrieval policy live today?
Can CoverageReport become a future corrective-retrieval signal without replacing existing authority?
Which R-001C gaps are real structural gaps vs already-existing foundations?
```

It does **not** claim production behavior, answer-quality improvement, or post-I-002 issue resolution.

---

## 2. Executive conclusion

The current repo is already structurally stronger than a simple RAG stack. It has a stable document/chunk identity model, explicit Postgres ledger, deterministic vector identity, consistency reconciliation, fail-closed source visibility, durable source deletion lifecycle, Hybrid retrieval, EvidencePlan, CoverageReport and a clearly bounded evidence-control plane.

The principal static gaps relevant to R-001C are therefore **not** "build basic RAG infrastructure." They are:

1. **source-item semantics are still document-oriented and connector-specific rather than a generic Knowledge Item contract;**
2. **WooCommerce is parent-product oriented and does not expose first-class variation/SKU records;**
3. **web crawling converts server-visible HTML to text/Markdown but has no generic interactive-tool or rich derived representation contract;**
4. **ledger/index truth is strong for admitted documents, but the system does not yet preserve a unified durable inventory of all discovered/admitted/rejected/failed/retired source items;**
5. **evidence authority and temporality are intentionally mostly `unknown`, so I-003 still needs explicit source/native authority and freshness semantics;**
6. **retrieval remains primarily Hybrid + specialized/bucket routes; EvidencePlan influences post-retrieval selection but does not yet act as a generalized retrieval policy input;**
7. **CoverageReport is computed after evidence composition and is semantically suitable as a future bounded corrective signal, but no accepted feedback loop currently consumes it to perform another retrieval.**

This validates the R-001C separation:

```text
I-003 = Knowledge Truth / lifecycle / representation
I-004 = Evidence Acquisition Policy / adaptive retrieval
```

No evidence from this static check justifies a wholesale GraphRAG migration or an unrestricted agentic loop.

---

## 3. Source and item identity reality

### 3.1 Connector output contract

All connectors converge on immutable `RawDocument`:

```text
source_id
source_type
product
title
content
url
metadata
content_hash
channel_visibility
branch
```

`source_id` is explicitly the document's unique identity in the source system. The connector protocol exposes:

```text
fetch_all()
fetch_changes(since)
fetch_deleted(since)
```

This is a solid replaceable ingestion boundary.

### 3.2 Ledger authority

Postgres `documents` uses `source_id` as the primary key. `content_hash` is a content fingerprint, not identity.

The ledger represents:

```text
one admitted source document
→ one documents row
→ expected chunk_count
```

This is an important existing Knowledge Truth foundation: the system can distinguish identity from content equality.

### 3.3 Chunk identity

Weaviate chunk UUIDs are deterministic:

```text
uuid5(source_id + "#" + chunk_index)
```

Therefore the stable evidence identity already used by I-002:

```text
(source_id, chunk_index)
```

is structurally aligned with ingestion and reconciliation.

### Static disposition

```text
Document identity foundation      = STRONG / KEEP
Chunk evidence identity           = STRONG / KEEP
Generic Knowledge Item abstraction = NOT PRESENT
```

A future I-003 Knowledge Item model should extend rather than discard the current identity chain.

---

## 4. WooCommerce / connector-native structured truth

### 4.1 Current behavior

`WooCommerceConnector` calls:

```text
/wp-json/wc/v3/products
```

and maps each published **parent product** to one `RawDocument`:

```text
source_id = <data_source_id>/<product_id>
```

The parent payload contributes flattened searchable fields such as:

- name;
- parent SKU;
- price / regular price / sale price;
- stock status / stock quantity;
- categories;
- description / short description;
- product type;
- modified date.

These fields are inserted into both searchable text and RawDocument metadata.

### 4.2 What is absent

No variation endpoint or variation iteration is present in the accepted connector path. There is no first-class identity such as:

```text
<data_source_id>/<product_id>/<variation_id>
```

and no generic variant object carrying:

```text
variation_id
attribute combination
variant SKU
variant current/sale price
variant stock
variant lifecycle/freshness
```

### 4.3 Deletion semantics

The connector explicitly degrades `fetch_deleted` rather than pretending it can prove remote deletion. This is safe, but means WooCommerce native item retirement is not fully represented by the connector today.

### Decision consequence

R-001C G-02 is confirmed as a **real structural I-003 gap**, not merely a prompt/retrieval issue.

However the correct future abstraction should remain source-native and provenance-preserving. This check does **not** freeze whether variants become RawDocuments, structured records beside RawDocuments, or another substrate.

```text
Connector-native structured truth = PRIORITY I-003 EXPERIMENT
Parent-product-only representation = CURRENT LIMIT
```

---

## 5. Web crawl and first-party tool representation

### 5.1 Existing web foundation

`web_crawl` already has substantial source-discovery discipline:

- robots handling;
- sitemap discovery;
- URL canonicalization;
- same-domain restriction;
- configurable exclusions;
- failure/rejection run statistics;
- thin-content rejection;
- server-visible HTML → Markdown extraction;
- URL-aware content hashing;
- full-run deletion-diff semantics.

A normal web page is therefore not ingested as an opaque blob.

### 5.2 Representation boundary

The accepted representation is still fundamentally:

```text
HTTP page
→ HTML parser
→ extracted text / Markdown
→ RawDocument
→ chunks
```

Script/style and other non-content elements are deliberately removed. The crawler is not a browser execution environment and does not define a generic contract for:

- JavaScript-calculated state;
- interactive selector combinations;
- structured calculator input/output space;
- executable first-party tools;
- image/VLM derived knowledge;
- rich table semantics beyond extracted textual representation.

### Decision consequence

R-001C G-03 remains a genuine representation question, but the baseline is stronger than "website crawler missing." The precise question is:

> Which authoritative knowledge cannot be faithfully represented by current server-visible text/Markdown, and what is the minimum additional representation needed?

This should be experiment-driven. Do not create a universal browser/VLM/tool execution pipeline by assumption.

```text
Normal website representation = MATURE BASELINE
Interactive/rich tool representation = GAP / EXPERIMENT REQUIRED
```

---

## 6. Ledger ↔ vector reconciliation reality

ASK-AI already has explicit Postgres/Weaviate consistency logic.

For a source, `verify_source_vectors` compares:

```text
Postgres expected chunk_count
vs
actual Weaviate source_id/chunk_index sets
```

It detects:

- whole documents missing from Weaviate;
- partial/mismatched chunk sets;
- stale/excess chunks;
- orphan vectors with no Postgres ledger row;
- source IDs requiring refill.

Importantly, reconciliation is conservative: orphan/stale data is reported rather than casually deleted.

This means R-001C G-04 should **not** introduce a second competing definition of `indexed/searchable` if current ledger/index reconciliation can supply it.

### Static disposition

```text
Admitted-document ledger truth   = EXISTS
Chunk/index reconciliation       = EXISTS / STRONG
Item-level Admin inventory       = GAP
Pre-admission discovery manifest = CONNECTOR-DEPENDENT / INCOMPLETE
```

I-003 should reuse this truth instead of replacing it with a new generic status table unless a specific missing lifecycle fact requires durable state.

---

## 7. Source lifecycle reality

At DataSource level ASK-AI already has an explicit durable lifecycle:

```text
ACTIVE
→ DELETE_REQUESTED
→ DELETING
→ success: configuration row removed
→ failure: DELETE_FAILED
```

Only ACTIVE is sync-eligible; all other/unknown states fail closed.

The deletion worker is durable and restart-recoverable. It prevents delete/sync races, purges vector state before deleting configuration/ledger rows, and retains `DELETE_FAILED` when cleanup cannot be proven complete.

### Important boundary

This is **source-level lifecycle**, not a generic lifecycle for every item inside a source.

Individual connector items rely on connector-specific change/delete semantics. WooCommerce explicitly cannot currently prove deletion through its existing path; web full runs can perform stronger source-item diff semantics.

### Decision consequence

I-003 should preserve the existing source lifecycle authority and add item lifecycle only where the upstream connector can prove it.

```text
Source lifecycle             = STRONG / KEEP
Per-item lifecycle semantics = INCOMPLETE / CONNECTOR-SPECIFIC
```

No inferred disappearance should be promoted to authoritative retirement without connector evidence.

---

## 8. Evidence semantic metadata / provenance reality

I-002 INC-2a already persists chunk-level evidence metadata:

```text
evidence_authority_class
evidence_temporality
evidence_sensitivity
evidence_citation_eligibility
evidence_origin
```

But the safety design intentionally refuses unsupported inference:

- authority is currently generally `unknown`;
- temporality is `unknown` because ingestion/sync timestamps are not source-valid dates;
- sensitivity is only promoted when supported by explicit structural evidence;
- citation eligibility mirrors existing source-type display/citation semantics.

This is not a missing implementation defect. It is an explicit architectural boundary:

> ASK-AI has the **schema and propagation path** for richer evidence truth, but does not yet have trustworthy producers for authority/freshness semantics.

### Decision consequence

R-001C's I-003 authority/freshness work has a natural extension point already in place.

```text
Evidence metadata carrier       = EXISTS
Authority truth producer        = GAP
Source-valid temporality/freshness = GAP
Provenance identity chain       = EXISTS
```

Future structured/native knowledge should attach to this provenance model rather than invent an unrelated trust system.

---

## 9. Retrieval architecture reality

### 9.1 Current generic retriever

`HybridSearcher` is a Weaviate Hybrid retriever:

```text
BM25 sparse + dense vector
```

with:

- alpha control;
- product filters;
- product-label eligibility filters;
- channel visibility filters;
- symbol BM25 retrieval;
- source/chunk-type bucket retrieval;
- persisted evidence metadata projection.

This is already more than one unfiltered vector query.

### 9.2 Current routing model

The repo contains specialized routes/buckets and comparison-specific retrieval behavior, but there is no generalized first-class abstraction equivalent to:

```text
RetrievalPolicy(EvidencePlan, current_coverage, budget)
→ one or more retrieval actions
```

### 9.3 EvidencePlan timing

I-002 EvidencePlan explicitly defines **what evidence is required**, with roles including:

```text
PRODUCT_SPEC
SOLUTION_GUIDE
CASE_EVIDENCE
STORE_OFFICIAL
```

But INC-5 is deliberately post-retrieval: it takes existing retrieval/rerank/prune outputs and performs deterministic role matching, stable required-first ordering, and CoverageReport construction with **zero second retrieval**.

Therefore current architecture is:

```text
existing retrieval logic
→ candidates
→ EvidencePlan-aware selection/composition
→ CoverageReport
```

not yet:

```text
EvidencePlan
→ generalized retrieval policy
→ substrate/actions
```

### Decision consequence

R-001C G-05/G-07 are confirmed as genuine I-004 evolution points.

The existing HybridSearcher should be treated as A0/A1 substrate/control, not as the architecture authority and not as something to replace merely for novelty.

---

## 10. CoverageReport as future corrective retrieval signal

`CoverageReport` is an explicit frozen value object containing:

```text
slots
required_total
required_covered
coverage_complete
missing_required
```

Its semantics are strong: a required slot counts as covered only when matching evidence actually reaches the terminal generation context with the correct citation/background eligibility.

That makes it substantially better than raw retrieval count or top-k relevance as a possible future sufficiency signal.

### Current boundary

INC-5 explicitly forbids second retrieval. Current RAG wiring uses CoverageReport for evidence truth and downstream response strategy; there is no accepted loop:

```text
coverage incomplete
→ retrieve missing role
→ recompose
```

### Static feasibility conclusion

A future bounded corrective retrieval path is **architecturally feasible without redefining CoverageReport**.

The likely extension boundary is between:

```text
initial retrieval/composition
and
final response/generation
```

but R-001D does not freeze exact code placement or implementation HOW.

Required future invariants:

- CoverageReport remains evidence truth, not an agent opinion;
- corrective retrieval targets explicit missing evidence;
- bounded budget/stopping rule;
- no hidden mutation of Product Resolver authority;
- answer/stream semantic parity;
- final CoverageReport must reflect the final generation context;
- failure to retrieve more evidence must degrade to existing partial/insufficient semantics, not infinite retry.

```text
CoverageReport corrective control potential = STRONG
Current feedback loop                       = ABSENT
I-004 experiment suitability               = HIGH
```

---

## 11. Admin/source observability reality

The current Admin Data Sources surface exposes DataSource CRUD, lifecycle state, last sync status/error, discovery previews and sync operations.

The backend also contains rich internal evidence across:

- `documents` ledger;
- SyncLog/SyncRun;
- crawler run statistics;
- vector reconciliation;
- source lifecycle/deletion state.

However these truths are not yet unified into the #30 product requirement:

```text
for one known source item:
upstream/discovered
→ admitted/excluded
→ fetched/parsed
→ ledgered
→ indexed/searchable
→ failed/skipped
→ retired/deleted/stale
```

### Critical architecture observation

A substantial fraction of the required truth already exists **distributed across current components**. Therefore #30 should begin as a truth-model/IA integration problem, not by assuming a large new observability subsystem.

The main genuinely missing data appears likely to be pre-admission item history for connectors that do not persist discovered/rejected/failed item manifests beyond run aggregates.

That must be proven connector-by-connector before adding durable state.

```text
G-04 Product Gap = CONFIRMED
Foundation        = STRONGER THAN PREVIOUSLY ASSUMED
New persistent state = ONLY WHERE EXISTING TRUTH CANNOT RECONSTRUCT REQUIRED ITEM STATE
```

---

## 12. Source visibility / trust boundary

ASK-AI has two-layer visibility enforcement:

1. chunk-level `channel_visibility` filter during retrieval;
2. `SourceVisibilityGuard` rechecks source configuration before candidates reach rerank/LLM context.

The second layer fails closed for unknown/ghost sources and for absence of an authoritative snapshot.

This is important for future multi-substrate architecture: a graph, structured store or tool retriever must not become an authorization bypass.

### Required architecture invariant

Any new substrate must preserve equivalent source/product/channel authorization semantics before evidence can enter composition.

---

## 13. R-001C gap reconciliation

| R-001C Gap | Static Repo Reality | Updated disposition |
|---|---|---|
| G-01 Interaction/context | I-002 implementation exists | production validation pending |
| G-02 Connector-native structured commercial truth | parent WooCommerce product only; no first-class variations | **confirmed structural I-003 gap** |
| G-03 Rich/tool representation | robust static HTML pipeline, no generic interactive-tool representation | **confirmed conditional I-003 gap** |
| G-04 Source Content Inventory | strong distributed ledger/sync/reconciliation truth; missing unified item inventory/pre-admission history | **confirmed I-003 product gap; reuse existing truth** |
| G-05 Solution-aware multi-role retrieval | roles/coverage exist after retrieval; retrieval not generally role-driven | **confirmed I-004 experiment gap** |
| G-06 Sufficiency-driven retrieval | CoverageReport exists; no corrective feedback loop | **confirmed I-004 experiment gap** |
| G-07 Adaptive retrieval policy | specialized Hybrid/bucket routes, no generalized policy engine | **confirmed strategic I-004 hypothesis** |
| G-08 Context utility | rerank/prune + required-first composition exist | experiment still required |
| G-09 Relationship/multi-hop | no governed graph/relationship substrate frozen | experiment required; no GraphRAG mandate |
| G-10 Global/corpus | no evidence it is current P0 | conditional only |
| G-11 Agent Context | outside current answer surface | I-005 remains appropriate |
| G-12 Enterprise | existing self-host/control foundations but not part of this static retrieval check | I-006 later |

---

## 14. Architectural foundations to preserve

The future architecture should carry forward these proven repo contracts unless experiments establish a material reason to replace them:

1. `source_id` as stable source-item/document identity boundary;
2. `(source_id, chunk_index)` as evidence lineage identity;
3. Postgres ledger separated from vector index;
4. deterministic chunk UUIDs;
5. conservative ledger↔index reconciliation;
6. connector protocol / RawDocument ingestion boundary;
7. deny-by-default source lifecycle sync eligibility;
8. fail-closed source visibility guard;
9. explicit EvidencePlan semantics;
10. CoverageReport as terminal evidence-coverage truth;
11. source-backed evidence remains answer truth;
12. `UNKNOWN > unsupported inference` for authority/freshness.

This does not grant the current implementation preservation privilege. These are semantic contracts/foundations, not mandatory framework choices.

---

## 15. Architecture implications

### I-003 should primarily extend existing truth infrastructure

Priority static candidates:

```text
1. Source Content Inventory assembled from existing ledger/sync/index truth
2. Connector-native item schema for sources where stable native semantics exist
3. Explicit authority/freshness producers
4. Rich representation only for demonstrated source classes
5. Governed relationships only after provenance/lifecycle semantics are proven
```

### I-004 should add policy above replaceable retrieval substrates

The cleanest current strategic hypothesis remains:

```text
EvidencePlan
→ Retrieval Policy
→ current Hybrid and future optional substrates
→ composition
→ CoverageReport
→ optional bounded corrective policy
→ final evidence context
```

This lets ASK-AI evolve retrieval without turning GraphRAG, LightRAG, an agent loop, or a vector database into the product architecture.

---

## 16. What this check does NOT prove

This static review does not establish:

- whether I-002 fixes #26/#27 in production;
- whether #28/#29/#31 still fail after I-002;
- current production source inventory contents;
- whether the Battery Calculator is actually indexed in production;
- exact WooCommerce production variation payloads;
- real post-I-002 K0–K9 distribution;
- any architecture quality gain;
- any latency/cost benefit;
- that graph retrieval is needed;
- that bounded agentic retrieval is worth its cost.

Those remain production/evaluation evidence questions.

---

## 17. Part B — Production Reality Reconciliation gate

R-001D Part B must wait for:

```text
I-002 Release Gate FINAL PASS
→ Production Deployment
→ Production Acceptance
→ Benchmark v1 rerun
```

Then reconcile:

1. #26/#27 actual production behavior;
2. #28/#29/#31 residual failure classes;
3. zero-source rate and post-I-002 K0–K9 distribution;
4. Knowledge Truth vs Retrieval Policy residuals;
5. which representative cases should seed A0–A5 experiments;
6. whether global/graph/multi-hop capability is materially demanded by real failures.

---

## 18. Current disposition after Part A

```text
STATIC_REPO_REALITY_CHECK                  = COMPLETE
BASELINE                                   = main@fbbf6530935d917c7729c58e2c4c9f6e109ebb70
PRODUCTION_EVIDENCE                        = NONE
PRODUCTION_RECONCILIATION                  = PENDING

DOCUMENT / CHUNK IDENTITY FOUNDATION       = STRONG
LEDGER / VECTOR RECONCILIATION             = STRONG
SOURCE-LEVEL LIFECYCLE                     = STRONG
SOURCE VISIBILITY BOUNDARY                  = STRONG
EVIDENCE META CARRIER                       = EXISTS

WOO VARIATION-NATIVE TRUTH                 = GAP
INTERACTIVE/RICH TOOL REPRESENTATION       = CONDITIONAL GAP
ITEM-LEVEL KNOWLEDGE INVENTORY              = GAP
EXPLICIT AUTHORITY/FRESHNESS PRODUCERS      = GAP
GENERAL RETRIEVAL POLICY ENGINE             = GAP / HYPOTHESIS
COVERAGEREPORT CORRECTIVE FEEDBACK LOOP     = GAP / PRIORITY EXPERIMENT

WHOLESALE GRAPHRAG MIGRATION                = NOT JUSTIFIED
UNRESTRICTED AGENTIC LOOP                   = NOT JUSTIFIED
TARGET ARCHITECTURE FREEZE                  = NOT READY
I-003 / I-004 IMPLEMENTATION AUTHORIZATION  = NONE
```

R-001C can now treat **Static Repo Reality Check** as satisfied. The next architecture evidence gate is post-I-002 Production Reality + Benchmark reconciliation, followed by selecting the highest-value A0–A5 experiments.
