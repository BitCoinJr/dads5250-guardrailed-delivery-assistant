"""Exercise the BA and DE gates through the real Streamlit interaction model."""
from pathlib import Path
import json

from streamlit.testing.v1 import AppTest

from delivery_assistant import backlog_ui

ROOT = Path(__file__).resolve().parents[1]


def intake(monkeypatch, tmp_path):
    monkeypatch.setenv("DELIVERY_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90).run()
    assert not at.exception
    assert at.get_by_key("view").value == "0  BA intake"
    return at


def estimate(at):
    at.button(key="estimate_backlog").click().run()
    assert not at.exception
    return at.session_state["triage_review_id"]


def ba_fields(at, review_id, request_id="REQ-001"):
    suffix = review_id + "_" + request_id
    at.text_area(key="ba_rationale_" + suffix).set_value("BA and marketing agreed the deadline; correct revenue before campaign decisions.")
    at.checkbox(key="ba_ack_" + suffix).check()


def test_four_quadrants_are_provisional_and_go_is_explicit(monkeypatch, tmp_path):
    at = intake(monkeypatch, tmp_path)
    assert len(at.dataframe[0].value) == 10
    review_id = estimate(at)
    review = json.loads((tmp_path / "runs/triage" / review_id / "review.json").read_text(encoding="utf-8"))
    assert {rec["quadrant_key"] for rec in review["recommendations"]} == {"high_small", "high_large", "low_small", "low_large", "unknown"}
    assert review["decisions"] == []
    assert at.session_state["active_run"] is None
    assert any("no AI call" in caption.value for caption in at.caption)
    at.button(key="record_ba_decision").click().run()
    assert any("confirm the review" in error.value for error in at.error)
    assert "intake_handoff" not in at.session_state


def test_ba_go_to_validated_patch_separate_de_approval_and_frozen_revision(monkeypatch, tmp_path):
    at = intake(monkeypatch, tmp_path)
    review_id = estimate(at)
    ba_fields(at, review_id)
    at.button(key="record_ba_decision").click().run()
    assert not at.exception
    receipt = at.session_state["intake_handoff"]
    assert receipt["decision"] == "Go"
    assert at.session_state["active_run"] is None
    assert at.get_by_key("view").value == "1  Request"
    assert at.text_area(key="description_" + receipt["decision_id"]).disabled
    at.button(key="prepare").click().run()
    assert not at.exception
    run_id = at.session_state["active_run"]
    path = tmp_path / "runs" / run_id / "state.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["status"] == "awaiting_approval"
    assert state["validation"]["proposed_total"] == 770
    provenance = json.loads(state["feedback"])
    assert provenance["ba_decision_id"] == receipt["decision_id"]
    at.get_by_key("view").set_value("4  Human review").run()
    assert at.button(key="approve").disabled
    assert not at.get("download_button")
    at.checkbox(key="ack_" + run_id).check().run()
    at.button(key="revise").click().run()
    assert not at.exception
    assert at.text_area(key="revised_description").disabled
    assert at.text_area(key="revised_criteria").disabled
    at.text_area(key="revision_feedback").set_value("Recheck the existing business rule; no requirement change.")
    at.button(key="regenerate").click().run()
    assert not at.exception
    revised_id = at.session_state["active_run"]
    revised_path = tmp_path / "runs" / revised_id / "state.json"
    revised = json.loads(revised_path.read_text(encoding="utf-8"))
    assert revised_id != run_id
    assert revised["request"] == state["request"]
    assert json.loads(revised["feedback"])["ba_decision_id"] == receipt["decision_id"]
    at.get_by_key("view").set_value("4  Human review").run()
    at.checkbox(key="ack_" + revised_id).check().run()
    at.button(key="approve").click().run()
    assert not at.exception
    assert json.loads(revised_path.read_text(encoding="utf-8"))["status"] == "approved"
    assert any(node.label == "Download approved patch package" for node in at.get("download_button"))


def test_unsupported_request_has_no_go_and_review_ack_does_not_transfer(monkeypatch, tmp_path):
    at = intake(monkeypatch, tmp_path)
    review_id = estimate(at)
    ba_fields(at, review_id)
    # Stage a form submission as Hold so a new request selection does not carry its acknowledgment.
    at.selectbox(key="ba_action_" + review_id + "_REQ-001").select("Hold")
    at.button(key="record_ba_decision").click().run()
    assert not at.exception
    at.selectbox(key="ba_request_" + review_id).select("REQ-010").run()
    assert at.selectbox(key="ba_action_" + review_id + "_REQ-010").options == ["Hold", "Clarify"]
    assert not at.checkbox(key="ba_ack_" + review_id + "_REQ-010").value
    assert not at.text_area(key="ba_rationale_" + review_id + "_REQ-010").value
    assert at.session_state["active_run"] is None


def test_changed_queue_blocks_go_even_if_selected_request_is_unchanged(monkeypatch, tmp_path):
    at = intake(monkeypatch, tmp_path)
    review_id = estimate(at)
    rows = backlog_ui.demo_items(ROOT)
    rows[1] = rows[1].model_copy(update={"business_impact": 5})
    monkeypatch.setattr(backlog_ui, "fresh_items", lambda source, root: rows)
    ba_fields(at, review_id)
    at.button(key="record_ba_decision").click().run()
    assert not at.exception
    assert any("queue changed" in error.value for error in at.error)
    assert "intake_handoff" not in at.session_state


def test_live_sheet_missing_auth_explains_setup_without_csv_or_demo_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(backlog_ui, "connection_status", lambda root: {"configured": False, "message": "Google credentials not configured."})
    def unavailable(source, root):
        raise backlog_ui.GoogleSheetsError("Connect Google using the setup guide.")
    monkeypatch.setattr(backlog_ui, "fresh_items", unavailable)
    at = intake(monkeypatch, tmp_path)
    at.get_by_key("backlog_source").set_value("Google Sheets").run()
    at.button(key="refresh_backlog").click().run()
    assert not at.exception
    assert any("Connect Google" in error.value for error in at.error)
    assert not at.dataframe
    assert not at.file_uploader
    assert "backlog_snapshot" not in at.session_state


def test_openai_estimation_requires_key_without_silent_sample_results(monkeypatch, tmp_path):
    at = intake(monkeypatch, tmp_path)
    at.selectbox(key="generation_mode").select("OpenAI API").run()
    at.button(key="estimate_backlog").click().run()
    assert not at.exception
    assert any("API key" in error.value for error in at.error)
    assert "triage_review_id" not in at.session_state
