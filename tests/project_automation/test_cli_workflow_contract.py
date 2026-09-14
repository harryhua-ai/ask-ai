"""CLI → shell → workflow exit semantics for Issue #69."""
from pathlib import Path

import yaml
from project_automation import cli
from project_automation.errors import ProjectMutationFailure

WORKFLOW = Path(".github/workflows/project-sync.yml")
RECONCILE_WORKFLOW = Path(".github/workflows/project-reconcile.yml")


def test_cli_success_results_are_zero(monkeypatch):
    monkeypatch.setattr(cli, "sync_issue", lambda *args, **kwargs: {
        "issue": 68, "result": "ALREADY_CONVERGED", "findings": [], "mutations": [],
    })

    assert cli.main(["--token", "test", "sync", "--issue", "68", "--apply"]) == 0


def test_cli_recognized_failure_result_is_nonzero(monkeypatch):
    monkeypatch.setattr(cli, "sync_issue", lambda *args, **kwargs: {
        "issue": 68, "result": "FAILED_VALIDATION",
        "findings": [{"code": "UNKNOWN_ITERATION", "message": "missing"}],
    })

    assert cli.main(["--token", "test", "sync", "--issue", "68", "--apply"]) != 0


def test_cli_transport_failure_is_nonzero(monkeypatch):
    def fail(*args, **kwargs):
        raise ProjectMutationFailure("simulated failure")

    monkeypatch.setattr(cli, "sync_issue", fail)

    assert cli.main(["--token", "test", "sync", "--issue", "68", "--apply"]) == 1


def test_project_sync_workflow_does_not_swallow_cli_failure():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    assert "set -euo pipefail" in workflow["jobs"]["sync"]["steps"][-1]["run"]
    run = workflow["jobs"]["sync"]["steps"][-1]["run"]
    assert "|| true" not in run
    assert "project_automation/cli.py sync" in run


def test_project_reconcile_workflow_does_not_swallow_cli_failure():
    workflow = yaml.safe_load(RECONCILE_WORKFLOW.read_text())
    run = workflow["jobs"]["reconcile"]["steps"][-1]["run"]
    assert "set -euo pipefail" in run
    assert "|| true" not in run
    assert "project_automation/cli.py reconcile" in run
