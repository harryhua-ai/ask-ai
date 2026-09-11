# Benchmark v1 Freeze Corpus — Persistence & Governance Record

Status: **FROZEN** (v1 contracts are immutable acceptance criteria for the
Answer Intelligence line). This file records how the corpus entered version
control, what was scrubbed, and which hashes bind which evidence.

## Tracked files (exact allowlist — enforced by `tests/benchmark/test_freeze_governance.py`)

- `contracts_frozen_v1.json`
- `executable_corpus_v1.json`
- `evaluator_contract_v1.json`
- `scoring_aggregation_spec_v1.json`
- `evidence_manifest_v1.json`
- `benchmark_manifest_v1.json`

## Intentionally NOT tracked

- `anonymization_map_v1.json` — customer-name reverse mapping (PII-bearing).
  Must never be committed. The governance test fails if it appears in
  `git ls-files`.

## Hash ledger

Baseline evidence binding (`baseline_v1_2026-09-10/run_manifest_v1.json`,
run `BF-SPRINT-V1-20260910-V140-41278F0`, 121 × 3 = 363 raw runs — immutable,
never regenerated) points at the PRE-SCRUB corpus:

| file | pre-scrub sha256 (baseline binding) | committed (cleaned) sha256 |
|---|---|---|
| contracts_frozen_v1.json | `5a436f05…` | `3c935500…` |
| executable_corpus_v1.json | `a1f920c0…` | `207f9684…` |
| evaluator_contract_v1.json | `c5898b07…` | unchanged |
| evidence_manifest_v1.json | `d638685f…` | unchanged |
| scoring_aggregation_spec_v1.json | `5afda9c2…` | unchanged |
| benchmark_manifest_v1.json | `f49adfd5…` | unchanged |

(The baseline manifest stores 8-char prefixes; full hashes are pinned by the
governance test via the tracked files themselves. Baseline results are valid
against the pre-scrub corpus: the only deltas are the enumerated name scrubs
below, which do not alter any case ID, question semantics, marking criteria,
or expected behavior.)

## Cleaning operation (2026-09-11, mechanical, disclosed)

Customer personal names only; company names retained (mirrors the
anonymization map's own sanitized forms):

| replacement | files | occurrences |
|---|---|---|
| `客户 Zac Diener (` → `客户（姓名略）(` | contracts | 2 |
| `Zac Diener` → `客户（姓名略）` | contracts | 1 |
| `Krzysztof Adamski 咨询` → `客户咨询` | contracts + corpus (sq-034) | 2 |
| `加拿大 Smart Parking Solutions Inc（Hichem Chouikha）` → `…（联系人姓名略）` | contracts + corpus (sq-040) | 2 |
| `Jim R ([邮箱])` → `联系人（姓名略）([邮箱])` | contracts (sq-049 origin) | 1 |
| `Massimo` → `客户` | contracts (sq-073/sq-074 criteria prose) | 9 |

Total: 17 occurrences across 2 files. Case IDs (121, unique), question
semantics, marking criteria, evaluator/scoring specs: unchanged.

## Governance enforcement

`tests/benchmark/test_freeze_governance.py` asserts:

1. the tracked freeze file set equals the allowlist above (nothing else under
   `freeze_v1/` may enter version control);
2. `anonymization_map_v1.json` is not tracked;
3. no email pattern and no known customer-name token appears in any tracked
   freeze file;
4. the committed corpus loads via the runner's default path with 121 unique
   case IDs and all mandatory seed cases present.
