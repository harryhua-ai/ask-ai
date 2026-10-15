from pathlib import Path


RETIRED_WORKFLOWS = (
    Path(".github/workflows/project-sync.yml"),
    Path(".github/workflows/project-reconcile.yml"),
    Path(".github/workflows/project-iteration-create.yml"),
)

PROTECTED_WORKFLOWS = (
    Path(".github/workflows/ght-complete.yml"),
    Path(".github/workflows/ght-plan-publish.yml"),
    Path(".github/workflows/build-image.yml"),
    Path(".github/workflows/deploy-production.yml"),
    Path(".github/workflows/release-integrity.yml"),
)


def test_project_automation_workflow_entrypoints_are_removed():
    assert all(not workflow.exists() for workflow in RETIRED_WORKFLOWS)


def test_core_workflow_files_remain_present():
    assert all(workflow.is_file() for workflow in PROTECTED_WORKFLOWS)


def test_project_automation_document_marks_retirement_and_restore_gate():
    document = Path("docs/engineering/project-automation.md").read_text()

    assert "已停用" in document
    assert "历史说明" in document
    assert "independent User authorization" in document
