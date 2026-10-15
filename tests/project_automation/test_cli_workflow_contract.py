"""CLI return semantics for the historical Project automation tooling."""
from project_automation import cli
from project_automation.errors import ProjectMutationFailure


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
