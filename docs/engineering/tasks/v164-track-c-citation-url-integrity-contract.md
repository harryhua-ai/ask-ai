# v1.6.4 Track C Contract — Citation URL Integrity (#48)

- Status: FROZEN WHAT / Boundary / Acceptance (implementation HOW open)
- Owner track: C · Issue: #48 (P0) · Base: main `5c501914` · Gate: v1.6.3 COMPLETE + drift check
- Factual basis: [v164-engineering-reality-audit.md](./v164-engineering-reality-audit.md) §4 (production corpus: 93% unmapped GitHub URLs)

## 1. Product semantics frozen (WHAT)

C-1. **Trust contract (from the issue, unchanged):** a rendered clickable citation must resolve to the authoritative user-facing source represented by that evidence. Claim-support and link-resolvability are two independent validity dimensions; both must hold for a citation to be presented as verifiable.

C-2. **No fake navigability.** A source without a safe external URL must never render as clickable — neither as `<a href="">` (self-navigation) nor as a dead scheme. This closes: the knowledge-case `url=""` blanking path, legacy `file://` objects, and any empty/invalid permalink (WooCommerce included).

C-3. **Linkability is backend-owned state, not widget guessing.** The citation object serialized to the widget must carry explicit link state distinguishing at least: (a) valid external canonical URL; (b) no external destination → render non-clickable source representation; (c) private/inaccessible → no fake public navigability; (d) moved/deleted/stale → truthful unavailable/stale representation. The widget renders per state; it must not decide linkability from string shape.

C-4. **GitHub evidence.** Ingestion captures repository accessibility (the connector knows at clone time) and it must survive to the citation state: private/inaccessible repos never produce public-looking clickable links. Public repo files keep canonical blob URLs (identity preservation R3 unchanged). Staleness (branch-ref 404 window) must be explicit and truthful in the state model and documentation — the system may not present a possibly-stale link as verified.

C-5. **Non-linkable classes are closed.** `local_git` (and `file://` generally) must not be a publicly linkable class; existing legacy objects in the corpus render non-clickable rather than dead links. Filesystem sources were never publicly linkable — keep it that way.

C-6. **Wiki canonical mapping preserved.** The existing wiki-documents → `wiki.camthink.ai` canonical mapping and its passthrough-for-everything-else behavior remain (display-layer only, retrieval untouched).

C-7. **Cross-source regression suite.** For every linkable source type: an automated test asserting the chain stored URL → API citation JSON → rendered href, including the non-clickable classes asserting absence of `<a>` fabrication. This is the suite the issue's acceptance explicitly requires and that does not exist today.

C-8. **Optional, not gated:** wire the existing orphaned click telemetry endpoint for production dead-link signal.

## 2. Boundary

- Zero changes to retrieval, rerank, evidence selection, claim grounding, citation numbering, or answer content (R5/R6 of the issue). If a URL fix tempts a retrieval change, it is out of this track.
- Widget behavior change is confined to link-state rendering; badge numbering/display (T29) for valid URLs is unchanged.
- No mass URL backfill required: link state may be derived at read/serialization time from persisted fields; any additive persistence follows the additive-only rule. Stored historical URLs are not rewritten (frozen-at-ingestion truth stays).
- Admin already guards correctly — align it with the new explicit state without redesign.

## 3. Acceptance

Unit/integration (new or extended, green on integration tree):

1. Widget: badge/link rendering per state — valid ⇒ clickable canonical href (incl. wiki mapping); empty/`file://`/non-http ⇒ **non-clickable** representation; no DOMPurify-bypassing or self-navigating anchors (new tests; currently zero for these classes).
2. Backend serialization: citation objects carry the explicit state for each class (a)–(d); `url=""` blanking replaced by explicit state (or equivalent contract-conformant representation).
3. GitHub: public repo file ⇒ canonical blob URL unchanged; private/inaccessible repo (fixture) ⇒ non-fake state; identity fields preserved.
4. `local_git`/legacy `file://` objects ⇒ non-clickable; woo empty-permalink fixture ⇒ non-clickable.
5. E2E chain test per linkable type: stored URL → API JSON → rendered href (the missing suite).
6. Regression: citation-integrity suite, numbering/stream-parity tests, widget vitest, admin type checks — all green; red-line benchmarks untouched (C does not execute answer-path code changes).

Runtime/production acceptance (post-deploy): real conversation containing a **non-wiki GitHub citation** (the Sep-11 class) — public repo ⇒ resolves; private repo ⇒ truthful non-navigable; a knowledge-case citation renders non-clickable without self-navigation; wiki citations unchanged; admin truth panel consistent with rendered states. Zero dead/malformed/misdirected clickable citations in the acceptance transcript.

Issue #48 closure: C acceptance + production cross-source click-through evidence.
