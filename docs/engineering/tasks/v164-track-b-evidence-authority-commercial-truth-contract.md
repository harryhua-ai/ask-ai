# v1.6.4 Track B Contract — Commercial Truth & Evidence Authority (#28 + #31)

- Status: FROZEN WHAT / Boundary / Acceptance (implementation HOW open)
- Owner track: B (sub-layers B1 ingestion / B2 semantics) · Issues: #28, #31 · Base: main `5c501914` · Gate: v1.6.3 COMPLETE + drift check
- Factual basis: [v164-engineering-reality-audit.md](./v164-engineering-reality-audit.md) §2–§3

## 1. Product semantics frozen (WHAT)

### B1 — Variation truth ingestion (#28)

B1-1. For WooCommerce **variable** products, the Store's **actual variations** (endpoint-provided) must be ingested as first-class truth: per-variation attributes, SKU, regular/current/sale price, stock/purchasability where supported, and canonical product/variation identity (permalink/ids).

B1-2. **Only real Store variations are purchasable truth.** No Cartesian synthesis of theoretical attribute combinations; if the Store does not define a combination, it must not exist as purchasable truth in the system.

B1-3. Variation identity must survive as **structured metadata** (not prose-only) from ingestion through chunk persistence, so one variation can never be confused with another product/SKU, and so downstream layers (retrieval filters, citation source identity, admin) can read it. Parent-product documents remain.

B1-4. The #50 document-truth surface must expose product/variation representation (variation/SKU/price/stock fields) — doc-level inspectability, no IA change.

B1-5. A **frozen internal interface** B1→B2: the variation metadata/identity contract (field names, identity key, Weaviate property additions, admin schema shape) is pinned in this contract's §4 before B2 consumes it. Amendment = versioned contract change, never silent drift.

### B2 — Claim-dependent evidence authority & truthful absence (#28 + #31)

B2-1. **Authority is claim-dependent** (frozen direction, not mechanism):

| Claim type | Best available eligible authority |
|---|---|
| technical specification | Product / Wiki / authoritative technical docs |
| SDK / API | Developer docs / authoritative repository docs |
| current price / sale / stock / purchasable variation | Store (WooCommerce), when healthy & fresh |
| validated deployment proof | Case Study (first-party published case) |
| solution architecture / pattern | Solution + relevant Case |
| compatibility / capability | Authoritative product / technical docs |
| AI model / use-case capability | Model / use-case / developer documentation |

A Case Study is valid proof of a deployment but must not override a more authoritative spec for a baseline technical claim; docs absence must never produce an "official price unavailable" statement while Store truth exists in the knowledge domain.

B2-2. **Absence semantics.** "官方资料未载明 X"-class claims must be assessed against the eligible authoritative source classes for X, not merely the retrieved context. At minimum: when an eligible authority class for the claim type exists in the knowledge domain but is not represented in the current context, the answer must not assert official absence — it must express insufficiency per the existing coverage/gap semantics instead. The current context-scoped instruction (`rag.py:1156-1157`) must be replaced by semantics consistent with this rule.

B2-3. **Mixed questions.** Configuration+price questions must combine product/docs evidence for technical distinctions with Store variation evidence for commercial facts; the commercial handling (required STORE slot, reservation, frame directives) must not be bypassed because the question also contains technical content.

B2-4. **Case role.** First-party published case-study pages (website crawl class) are eligible CASE_EVIDENCE; "validated deployment proof" must be distinguishable from internal historical support cases; vague "historical cases" must not substitute for an existing first-party case.

B2-5. **Solution retention.** Solution queries have a defined retention path for official Solution pages (retrieval bucket or equivalent guarantee), not title-signal-only matching.

B2-6. **Freshness truthfulness.** Current-price/stock answers carry truthful freshness/source semantics; historical/sale-window prices must not be presented as current; when the Store source is stale/unavailable the answer says so (honest insufficiency), and does not silently substitute documentation prices.

B2-7. **EN/ZH parity** with an explicit regression pair for solution and pricing queries.

B2-8. **Generality.** No CamThink-specific hard-coding beyond existing taxonomy configuration; no product-name if/else in business code (existing freeze rule).

## 2. Boundary

- Untouched contracts (regression-protected): comparison pipeline exemption; product isolation gates; fail-closed retrieval; citation numbering/integrity (CIT-01/02/03); F-1' reservation mechanism (B may extend slot semantics but not remove the mechanism); `evidence_authority_class` schema may be activated or replaced — decision is engineering HOW, but one authority representation only (no parallel competing authority fields).
- No prices/attributes in prompts or static config; no woo API calls outside the connector; ingestion changes additive-only at the schema level; woo source re-sync (41 docs) is the expected data path — no mass corpus rebuild.
- B2 may build against fixtures before B1 lands; the joined acceptance (cg-r05 e2e) happens on the combined tree.

## 3. Frozen internal interface (B1→B2, §5 of B1-5) — placeholder to be pinned at B1 kick-off

```
variation_identity_key:        <to pin: e.g. product_id + variation_id>
metadata fields (chunk props): <to pin: sku / attributes / prices / stock / purchasable / permalink / freshness stamp>
admin schema fields:           <to pin>
source_type / doc typing:      woo parent vs variation discriminable downstream
```

## 4. Acceptance

Unit/integration (new or extended, green on integration tree):

1. Connector: variable product fixture ⇒ parent + N variation documents with the pinned metadata; simple product unchanged; non-variable products unchanged; only listed variations represented (no synthesis).
2. Chunk metadata: commerce fields present as structured properties; identity unique per variation; anti-conflation test (two variations / two products never merge identities).
3. Authority mapping: representative claim-type × available-evidence matrix — each material claim cites its owning class; case-does-not-override-spec test (sq-045 class); store-price-beats-docs-absence test.
4. Absence semantics: eligible-class-exists-but-not-in-context ⇒ no official-absence assertion (new tests — currently zero); store-stale ⇒ truthful staleness, not silent substitution.
5. Mixed intent: config+price query reaches STORE slot + reservation + frame directives.
6. Solution composition: solution/case/wiki/model docs retained complementary (roles preserved in final context); website case satisfies CASE_EVIDENCE.
7. EN/ZH pair parity; freshness qualification present on commercial answers.
8. Red lines: cg-r03/r04/cg-s01 byte-identical behavior; comparison suite green; citation-integrity suite green; full backend suite green.

End-to-end (combined B1+B2 tree): **cg-r05 frozen repro** — NE101/NE301 per-configuration prices answered from real variation truth with SKU/attribute association, no false official-absence, no fabricated combinations, product isolation intact.

Runtime/production acceptance (post-deploy): real cg-r05 repro against production; admin variation inspection on woo source; a solution-class real query showing complementary role-preserving citations with authority-consistent ownership; zero unsupported absence claims in the acceptance transcript.

Issue #28 closure: B1+B2 acceptance + cg-r05 production evidence. Issue #31 closure: B2 acceptance + solution-composition production evidence.
