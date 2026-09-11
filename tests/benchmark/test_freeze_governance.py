"""#32 基准冻结语料治理守卫(PERSISTENCE.md 契约的机器可执行形态)。

四条不变量:
1. freeze_v1 下入库文件集合 == 白名单(防止任何未审计文件混入公开仓库);
2. anonymization_map_v1.json(客户姓名反查表,PII)永不入库;
3. 已入库冻结文件不含邮箱模式与已知客户姓名 token;
4. 提交态语料可被 runner 默认路径加载:121 个唯一 case_id + 强制种子齐备。
"""

import json
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FREEZE_DIR = REPO_ROOT / "docs/evaluation/benchmark_v1/freeze_v1"
RUNNER = REPO_ROOT / "scripts/benchmark_v1/run_benchmark.py"

ALLOWLIST = {
    "PERSISTENCE.md",
    "benchmark_manifest_v1.json",
    "contracts_frozen_v1.json",
    "evaluator_contract_v1.json",
    "evidence_manifest_v1.json",
    "executable_corpus_v1.json",
    "scoring_aggregation_spec_v1.json",
}

MANDATORY_SEEDS = {
    "cg-r03", "cg-r04", "cg-s01", "cg-r05", "cg-r06", "cg-r07", "cg-r09",
    "sq-026", "sq-034", "sq-040", "sq-045", "sq-073", "sq-080",
}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# 客户个人姓名 token(公司名/产品名不属于 PII,允许出现)。
CUSTOMER_NAME_TOKENS = (
    "Zac Diener",
    "Krzysztof Adamski",
    "Adamski",
    "Hichem Chouikha",
    "Chouikha",
    "Jim R",
    "Massimo",
)


def _tracked_freeze_files() -> set[str]:
    out = subprocess.run(
        ["git", "ls-files", "docs/evaluation/benchmark_v1/freeze_v1/"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    )
    return {Path(p).name for p in out.stdout.splitlines() if p.strip()}


def test_only_allowlisted_freeze_files_are_tracked():
    tracked = _tracked_freeze_files()
    assert tracked == ALLOWLIST, (
        "freeze_v1 入库集合漂移(意外新增/缺失)。新增冻结文件必须同步更新 "
        "PERSISTENCE.md 与本测试白名单。"
    )


def test_anonymization_map_is_never_tracked():
    assert "anonymization_map_v1.json" not in _tracked_freeze_files(), (
        "anonymization_map_v1.json 是客户姓名反查表(PII),禁止入库。"
    )


def test_tracked_freeze_files_contain_no_emails_or_customer_names():
    for name in ALLOWLIST - {"PERSISTENCE.md"}:
        text = (FREEZE_DIR / name).read_text()
        assert not EMAIL_RE.search(text), f"{name} 含邮箱模式"
        for token in CUSTOMER_NAME_TOKENS:
            assert token not in text, f"{name} 含客户姓名 token: {token}"


def test_committed_corpus_loads_via_runner_default_path_with_121_cases():
    assert RUNNER.exists(), "runner 必须在库(评审与回归的执行入口)"
    assert DEFAULT_CORPUS_REACHABLE()
    corpus = json.loads((FREEZE_DIR / "executable_corpus_v1.json").read_text())
    cases = corpus["cases"]
    ids = [c["case_id"] for c in cases]
    assert len(cases) == 121, f"冻结语料必须 121 cases,实际 {len(cases)}"
    assert len(set(ids)) == 121, "case_id 必须唯一"
    assert MANDATORY_SEEDS <= set(ids), "强制种子缺失"


def DEFAULT_CORPUS_REACHABLE() -> bool:
    """runner 的默认语料路径必须指向已入库文件(相对 repo 根可解析)。"""
    from scripts.benchmark_v1.run_benchmark import DEFAULT_CORPUS

    return Path(DEFAULT_CORPUS).is_file()
