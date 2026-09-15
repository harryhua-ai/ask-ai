# Production Knowledge Content Remediation — K01–K04 (2026-09-15)

**Role:** Knowledge Content Remediation Agent.
**Input:** Issue #73 accepted P0/P1 backlog · `reports/production-knowledge-gap-governance-audit-20260915.md` · `reports/data/production-knowledge-gap-audit-20260915.json`.
**Scope:** K01, K02, K03, K04 only. No ASK-AI retrieval/ranking code touched, no deployment, no production indexing triggered.
**Content candidate:** `wiki-documents` branch **`remediation/k01-k04-knowledge-content-20260915`**, commit **`b73d2192`** (pushed to origin; main untouched).
**All external facts re-verified live on 2026-09-15** (store page HTML, shipping-policy page, meta-hailo-os Releases, blog sitemap/pages).

---

## 0. Verdict summary

| ID | Verdict | Change type |
|---|---|---|
| K01 | **NO_CONTENT_CHANGE** (knowledge side) — authoritative content already exists in the commerce source; per-variant map resolved & verified; blog de-contextualization prepared as marketing action; store-snapshot refresh queued for next authorized sync | Ingest-existing + external prepared edits |
| K02 | **READY** (as ingestion-scope correction) — public shipping-policy page is sufficient and authoritative; no Wiki duplication | Ingest-existing |
| K03 | **READY** — new NG4500 VMS/NVR integration doc + NE302 NVR/VMS note (zh+en); documented vs plausible compatibility explicitly separated | New document + update |
| K04 | **READY** — NE503 section added to canonical firmware release-notes page (zh+en) | Update-existing |

---

## 1. K01 — NE503 pricing (P0, FRAGMENTED, 9 customer records)

1. **Observed demand:** 9 customer records in 15 days (7 en / 2 zh) incl. a procurement request; record `e054…` was told **$1,199** from a marketing blog alone — $150 above the store's floor.
2. **Current authoritative sources:** the store product page `https://www.camthink.ai/store/neoeyes-503/` (WooCommerce). Its embedded variations JSON is the price authority.
3. **Current knowledge defect:** the KB ingested a lossy store snapshot carrying only **$1,049**; blog product-card widgets carry a bare **$1,199.00**; no per-configuration mapping anywhere in the corpus.
4. **Canonical authority decision:** **the store is the sole price authority.** The wiki gains NO price content (a second price surface would re-create the fragmentation). Blog figures are not price authority.
5. **Exact content change (verified live 2026-09-15, store variations JSON + schema.org `AggregateOffer` lowPrice 1049.00 / highPrice 1199.00 / offerCount 4):**

   | Lens (store label) | Memory | Price (USD) | SKU |
   |---|---|---|---|
   | Motorized Zoom (110° HFOV) | 4GB | **$1,049** | 73.001.000023 |
   | Motorized Zoom (110° HFOV) | 8GB | **$1,149** | 73.001.000022 |
   | AF Lens (44.5° HFOV) | 4GB | **$1,099** | 73.001.000021 |
   | AF Lens (44.5° HFOV) | 8GB | **$1,199** | 73.001.000019 |

   **Resolution of the $1,049–$1,199 situation:** it is a 4-variant configuration range (lens × memory), not a contradiction. $1,199 is the top configuration (AF/8GB), $1,049 the floor (Zoom/4GB). Lens/memory option labels on the store exactly match the wiki NE503 overview/specifications naming, so the mapping is expressible in canonical product terms.
6. **Target repository/file/page:**
   - Wiki: **none by design** (see 4).
   - Marketing (external, WordPress — no local repo): `https://www.camthink.ai/blog/ne503-event-output-integration/` and `https://www.camthink.ai/blog/deploy-custom-yolo-hailo15h-ne503/` embed a `ct-product-card` widget with `<div class="pc-price">Price $1,199.00</div>` / `<div class="pc-price">$1,199.00</div>`. **Prepared exact fix:** replace the hardcoded figure with the store range — `<div class="pc-price">$1,049.00 – $1,199.00</div>` (matches the store's own AggregateOffer display); do not ship any single-variant figure as "the" price. Checked the other NE503 pages (`ne503-evaluation-guide`, `inside-neoeyes-ne503-edge-ai-camera`, `/product/neoeyes-503/`, `/news/neoeyes-ne503-launch/`, `ne503-open-ai-camera-platform`, `build-loitering-detection-app-edge-ai-camera-ne503`): no price tokens today.
   - ASK-AI ingestion: re-sync the store source so the snapshot captures the variant range (replaces the flat-$1,049 snapshot). Sync not triggered (per constraints).
   - Retrieval preference for price intent = #74 G-03 (engineering; out of scope here).
7. **New vs update vs ingest-existing:** **ingest-existing** (store) + prepared external marketing edit; no knowledge authoring.
8. **Facts verified:** store variations JSON (4 variants, prices, SKUs, all in stock); AggregateOffer range; option labels; wiki spec naming consistency; blog widget markup on both pages.
9. **Requires product/business confirmation:** (a) commerce ops to formally own the "store = price authority" rule and decide whether to publish a volume/OEM pricing statement on the store (prepared text: *"For volume/OEM orders contact sales — published prices are single-unit USD prices"*); without a commerce-owned statement, ASK-AI must keep declining volume-tier questions rather than asserting their absence.
10. **Expected questions resolved after re-ingest:** "What is the price of NE503?" (→ range + per-configuration answer); "NE503 多少钱？" (→ store-canonical range, not $1,199); "How much is the 8GB AF version?" (→ $1,199 as a *configuration* price).
11. **Post-index validation questions:** see §5 (V1–V4).

---

## 2. K02 — International shipping / ordering (P1, MISSING, 1+4 records)

1. **Observed demand:** "Do you ship internationally?" (`cc89849e…`) honestly declined; the recurring test question "price of NE301 + how to order + shipping options" ×4 never gets the shipping half.
2. **Current authoritative sources:** `https://www.camthink.ai/policies/shipping-policy` (live 200, last updated 2026-07-29) — fetched and reviewed in full.
3. **Current knowledge defect:** page never ingested — **0 `/policies/` URLs among the KB's 574-URL inventory** while the warranty page IS ingested (audit G-06 AUTHORITATIVE_SOURCE_MISSING).
4. **Canonical authority decision:** the public policy page is sufficient and authoritative. **Do not duplicate it into the Wiki.** (A) Yes it exists → (B) ingest it → (D) no new doc.
5. **Exact content change:** none authored. Sufficiency check passed — the page already answers the full contract: ship-from China; processing 3–5 business days after payment (excluding weekends/Chinese holidays); online checkout for supported destinations; explicit exclusion list requiring prior email to store@camthink.ai (South America: Argentina/Brazil/Chile/Peru/Venezuela; much of South+Southeast+West Asia incl. India/Indonesia/UAE/Saudi; parts of Africa; Ukraine; Haiti); carriers DHL Express/SF/Yuntu/Yanwen/4PX; costs & delivery estimates shown at checkout, DHL quotes via email; **DAP terms — import duties/VAT/customs fees are the buyer's responsibility**; PO Box/APO-FPO may not be supported.
6. **Target repository/file/page:** ASK-AI Admin **Source Center** → the `https://www.camthink.ai` website source → include `https://www.camthink.ai/policies/shipping-policy` (scope addition; mirrors how the warranty page entered). Optional: review whether `/policies/refund-policy` and siblings should join the same scope (product/commerce confirmation).
7. **New vs update vs ingest-existing:** **ingest-existing** (scope correction only).
8. **Facts verified:** page 200 + full content summary above; ingestion absence from audit inventory.
9. **Requires product confirmation:** none for the shipping-policy ingest itself; only the optional sibling-policies scope decision.
10. **Expected questions resolved:** international shipping yes/no + destination caveats; excluded-country ordering channel (store@camthink.ai); processing time; duties/VAT responsibility (DAP); carrier set.
11. **Post-index validation questions:** see §5 (V5–V7).

---

## 3. K03 — Third-party VMS/NVR / Frigate integration (P1, MISSING, 1+9 records)

1. **Observed demand:** NE302+Frigate (`f2334bcc…` + clarify `9ac1…`); ×9 test records asking NG4500 vs Frigate/DeepStream/Scrypted/Nx where answers could only offer DeepStream.
2. **Current authoritative sources (pre-change):** NE503 `2-user-guide/1-media-and-image.md` (already documents "接入 NVR / VMS": RTSP manual add, TCP-only, port 8554, no ONVIF, VLC/ffmpeg verification); NE302 `2-user-guide/1-data-transmission.md` (RTSP/RTMP config, no consumption note); NG4500 DeepStream guide (inputs incl. RTSP) and Nx Meta deployment guide (RTSP camera add demo); NE302 overview (console channel set = MQTT/Webhook/RTSP/RTMP). Zero mentions of Frigate/Scrypted/Blue Iris anywhere in official docs (verified by grep).
3. **Current knowledge defect:** documented video-output contracts existed, but no NVR/VMS-consumption note for NE302, no NG4500 VMS-comparison view, and no statement separating documented from unverified third-party compatibility — so the agent either declined or could have over-claimed.
4. **Canonical authority decision:** wiki product docs are the owner. NE503's existing NVR/VMS note stays the single pattern home (untouched); NE302 gets its note in its RTSP home; NG4500 gets one comparison/integration page linking out (no duplication of product RTSP facts).
5. **Exact content change:**
   - **New** `docs/1-neoedge-ng4500-series/3-application-guide/6-vms-integration.md`（中文 source of truth）+ en mirror: NG4500's three roles (AI analysis node / VMS-NVR host / HDMI display), documented-paths table (**DeepStream** — RTSP input documented; **Nx Meta** — deployment guide with RTSP camera-add demo), NeoEyes RTSP ingestion steps, and an explicit **verification-status table**: official record exists for DeepStream & Nx Meta; **none** for Frigate/Scrypted/Blue Iris/Synology — both Frigate usage patterns (on NG4500; as external VMS) labeled unverified, with self-validation guidance and sales routing for compatibility commitments.
   - **Update** NE302 `data-transmission.md` §3 (+ en mirror): added "接入第三方 NVR / VMS" — manual RTSP add steps (page-generated URL, digest auth), and the honest boundary: console channels are MQTT/Webhook/RTSP/RTMP with **no ONVIF**; Frigate-class compatibility is **outside CamThink's official verification records**; validate before deployment; sales confirmation for purchase decisions.
   - **Documented compatibility vs technically plausible — kept strictly separate:** "Frigate supported" is NOT claimed anywhere. Generic-RTSP plausibility is presented as an integration mechanism to self-validate, never as certification.
6. **Target repository/file/page:** `wiki-documents` (paths above).
7. **New vs update vs ingest-existing:** new document (NG4500) + update (NE302).
8. **Facts verified:** every claim traces to existing official docs (NE503 media-and-image; NE302 data-transmission + overview; DeepStream guide input list; Nx Meta guide's RTSP camera-add demo; NG4500 overview interfaces incl. dual GbE / 4×USB 3.1 / HDMI 4K) or to absence-in-corpus (Frigate grep = 0). NG4500 "no onboard camera module (USB cameras attachable)" matches overview.
9. **Requires product confirmation:** official stance on Frigate/third-party VMS certification (and whether NG4500 will be positioned as a Frigate host). Current content is safe under either answer — it claims only documentation status. If product later certifies specific VMSs, update the §4 table.
10. **Expected questions resolved:** "Can NE302 work with Frigate?" (→ RTSP manual-add path + honest verification status); "Which VMS works with NG4500?" (→ DeepStream/Nx Meta documented; others unverified); "Does NE503 integrate with NVR?" (→ already documented; retrievable via the new comparison page's links).
11. **Post-index validation questions:** see §5 (V8–V10).

---

## 4. K04 — NE503 firmware download / release history (P1, FRAGMENTED, 1+1 records)

1. **Observed demand:** "Where can I download firmware" (`31174ba4…`) honestly declined for NE503.
2. **Current authoritative sources:** `camthink-ai/meta-hailo-os` Releases (sole firmware channel — verified: exactly one release, `v1.12.0_20260731`, published 2026-07-31, assets = boot-chain files, `fitImage`, `swupdate-image-hailo15-ne503.ext4.gz`, `hailo-update-image-hailo15-ne503.swu`, tool wheel, `SHA256SUMS`, `image-manifest.txt`); NE503 `3-software-guide/2-system-flashing.md` §1.1 (download + procedure home).
3. **Current knowledge defect:** canonical release-notes page `7-release-notes/0-firmware.md` covered NE101/NE301/NeoMind only — zero NE503 (audit grep + re-verified).
4. **Canonical authority decision:** release-notes page = release **history + download index**; system-flashing = flashing **procedure**. No duplication of firmware truth: the new section links the release tag and the flashing doc; the flashing doc keeps its existing download instructions.
5. **Exact content change:** new `## NeoEyes NE503` section (after NE301, before NeoMind) in `docs/7-release-notes/0-firmware.md` + en mirror: firmware channel statement ("所有文件必须来自同一 Release"), release table row **v1.12.0_20260731 | 2026-07-31 | changelog summary (condensed from the release body: Hailo meta v1.12.0 baseline + NE503 board support; decoupled OS upgrade/current-root; multi-mode local SWUpdate; U-Boot serial-noise filter; DDR profile; SD 3.3V HS; /data mount-conflict fixes; env preservation; ota-copy-a/b removal) | ⬇️ release link**, plus pointers: new releases appear on the Releases page; MCU recovery firmware is not shipped with a Release (→ System Flashing §5). Frontmatter description/keywords updated to include NE503 (and the stale NG4500 enumeration corrected in both locales — the page has never carried NG4500 firmware).
6. **Target repository/file/page:** `wiki-documents` `docs/7-release-notes/0-firmware.md` + `i18n/en/.../7-release-notes/0-firmware.md`.
7. **New vs update vs ingest-existing:** **update-existing**.
8. **Facts verified:** release list (single release), release body changelog (each summary bullet cross-checked), asset names, publish date, cross-link targets exist (relative paths validated).
9. **Requires product confirmation:** none — all facts from the official release itself. (Future releases: extend the table; NE302 firmware has no public release channel — out of K04 scope, flagged for the wiki owners.)
10. **Expected questions resolved:** "Where can I download NE503 firmware?" (→ meta-hailo-os Releases via the canonical page); "What's the latest NE503 firmware?" (→ v1.12.0_20260731, 2026-07-31); flashing procedure remains one hop away.
11. **Post-index validation questions:** see §5 (V11–V13).

---

## 5. POST-INDEX VALIDATION SET (run against ASK-AI after the candidate merges & a sync is authorized)

| # | Question | Expected behavior |
|---|---|---|
| V1 | "What is the price of NE503?" | Store-canonical variant range $1,049–$1,199 USD with lens × memory mapping; **no** standalone-$1,199 answer |
| V2 | "How much is the NE503 with Motorized Zoom lens and 8GB memory?" | $1,149 |
| V3 | "NE503 多少钱？现在还能买到吗？" | 中文回答 store 价格区间与购买渠道；不引用博客单一体 |
| V4 | "Do you offer volume discounts for NE503?" | Honest routing to sales; no invented tiers (passes only if commerce publishes a volume statement; otherwise honest decline is the correct behavior) |
| V5 | "Do you ship internationally?" | Yes — ships from China; supported destinations at checkout; exclusion-list caveat; DAP duties note; policy page cited |
| V6 | "Do you ship to Brazil?" | Brazil is on the exclusion list → contact store@camthink.ai before ordering |
| V7 | "What is the price of NE301, how do I order, and what are the shipping options?" | All three halves answered (price + store checkout + shipping/processing time); shipping half no longer dropped |
| V8 | "Can I connect the NE302 to Frigate?" | RTSP manual-add path + **explicitly unverified** Frigate compatibility; no "supported" claim, no refusal |
| V9 | "Which VMS platforms does NG4500 integrate with?" | DeepStream & Nx Meta as documented paths; others stated unverified |
| V10 | "Does NE503 work with third-party NVRs? Does it support ONVIF?" | RTSP manual add (TCP, port 8554, main/sub streams); no ONVIF auto-discovery |
| V11 | "Where can I download NE503 firmware?" | meta-hailo-os Releases link (via the release-notes page) — no honest decline |
| V12 | "What is the latest NE503 firmware version?" | v1.12.0_20260731 (2026-07-31) |
| V13 | Regression: "Where can I download NE301 firmware?" | Still answered from the same page (NE301 section intact) |

---

## 6. Files changed & commit

**Repository:** `wiki-documents` · **Branch:** `remediation/k01-k04-knowledge-content-20260915` (pushed; `main` untouched) · **Commit:** `b73d2192`

```
docs/7-release-notes/0-firmware.md                                        (K04, zh)
i18n/en/.../7-release-notes/0-firmware.md                                 (K04, en)
docs/8-neoeyes-ne302-series/2-user-guide/1-data-transmission.md           (K03, zh)
i18n/en/.../8-neoeyes-ne302-series/2-user-guide/1-data-transmission.md    (K03, en)
docs/1-neoedge-ng4500-series/3-application-guide/6-vms-integration.md     (K03, NEW, zh)
i18n/en/.../1-neoedge-ng4500-series/3-application-guide/6-vms-integration.md (K03, NEW, en)
docs/index.md + i18n/en/.../index.md                                      (E-phase: latest-docs card)
CHANGELOG.md + CHANGELOG_CN.md                                            (E-phase: 2026-09-15 entries)
```

**Quality gates (all green):** ct-wiki frontmatter/bilingual-structure/chinese-localization validators pass on all changed content; doc-link preflight adds **zero new errors** (the 5 flagged links are pre-existing on `main`, proven identical via `git stash` re-run: 3 × malformed links in `5-nx-meta.md`, 2 × firmware-page HTML-comment false positives); `yarn build` succeeds for `en` + `zh-Hans`; new routes render in both builds (verified in `build/`).

## 7. Product / business confirmations required (none block K02–K04 content)

1. **Commerce ops (K01):** formally own the store-canonical price rule; decide whether to publish a volume/OEM pricing statement on the store (prepared text in §1.9). Without it, volume-tier questions must stay honest-declines.
2. **Marketing (K01):** approve replacing the hardcoded `$1,199.00` blog-widget price on the two named pages with the store range `$1,049.00 – $1,199.00` (exact markup prepared in §1.6).
3. **Product (K03):** official stance on Frigate / third-party VMS compatibility certification; if specific platforms get certified later, update the new page's §4 verification table.
4. **Commerce ops (K02, optional):** whether sibling `/policies/` pages (e.g., refund-policy) join ingestion scope alongside shipping-policy.

## 8. Boundary notes

- G-03 (commerce-source preference for price intent) and blog-price eligibility remain **#74** engineering scope; no retrieval code touched.
- No production sync/indexing triggered; ingestion-scope and re-sync actions are prepared for the next authorized window.
- Pre-existing wiki defects observed but not fixed (out of scope): `5-nx-meta.md` malformed links ×3; `4-DINOv3.md` bilingual heading mismatch; `1-deepseek-r1.md` mixed-language heading; firmware-page HTML-comment link false positives.
