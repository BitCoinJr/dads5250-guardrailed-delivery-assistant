from pathlib import Path
import json

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def app(monkeypatch, tmp_path):
    monkeypatch.setenv("DELIVERY_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    instance = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90).run()
    assert not instance.exception
    instance.get_by_key("view").set_value("1  Request").run()  # ty: ignore[missing-union-attribute]
    return instance


def test_uploaded_csv_to_approval_and_download(monkeypatch, tmp_path):
    at = app(monkeypatch, tmp_path)
    at.get_by_key("input_source").set_value("Upload CSV").run()
    at.file_uploader[0].upload("request.csv", (ROOT / "inputs/sample_request.csv").read_bytes()).run()
    at.button(key="prepare").click().run()
    assert not at.exception
    run_id = at.session_state["active_run"]
    state_path = tmp_path / "runs" / run_id / "state.json"
    assert json.loads(state_path.read_text(encoding="utf-8"))["status"] == "awaiting_approval"
    at.get_by_key("view").set_value("3  Changes and checks").run()
    assert not at.exception
    assert any(metric.value == "770.00" for metric in at.metric)
    at.button(key="to_approval").click().run()
    assert at.button(key="approve").disabled
    at.checkbox[0].check().run()
    at.button(key="approve").click().run()
    assert not at.exception
    assert json.loads(state_path.read_text(encoding="utf-8"))["status"] == "approved"
    assert any(node.label == "Download approved patch package" for node in at.get("download_button"))


def test_clarification_creates_a_new_validated_run(monkeypatch, tmp_path):
    at = app(monkeypatch, tmp_path)
    at.selectbox(key="sample_file").select("ambiguous_request.csv").run()
    at.button(key="prepare").click().run()
    original = at.session_state["active_run"]
    assert json.loads((tmp_path / "runs" / original / "state.json").read_text(encoding="utf-8"))["status"] == "needs_clarification"
    at.get_by_key("view").set_value("4  Human review").run()
    at.text_area(key="revised_description").set_value("Exclude canceled orders from revenue.")
    at.text_area(key="revised_criteria").set_value("Revenue excludes canceled orders. Tests, docs and dashboard agree.")
    at.button(key="regenerate").click().run()
    assert not at.exception
    revised = at.session_state["active_run"]
    assert revised != original
    revised_path = tmp_path / "runs" / revised / "state.json"
    assert json.loads(revised_path.read_text(encoding="utf-8"))["status"] == "awaiting_approval"
    at.get_by_key("view").set_value("4  Human review").run()
    at.checkbox[0].check().run()
    at.button(key="reject").click().run()
    assert not at.exception
    assert json.loads(revised_path.read_text(encoding="utf-8"))["status"] == "rejected"
    assert not any(node.label == "Download approved patch package" for node in at.get("download_button"))


def test_openai_requires_key_and_does_not_fall_back(monkeypatch, tmp_path):
    at = app(monkeypatch, tmp_path)
    at.selectbox(key="generation_mode").select("OpenAI API").run()
    at.button(key="prepare").click().run()
    assert not at.exception
    assert at.session_state["active_run"] is None
    assert any("OPENAI_API_KEY" in error.value for error in at.error)


def test_empty_startup_key_can_be_loaded_on_a_later_rerun(monkeypatch, tmp_path):
    import dotenv
    import os
    at = app(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "")
    def first_time_local_config(*args, **kwargs):
        os.environ.setdefault("OPENAI_API_KEY", "test-only-no-api-call")
        return True
    monkeypatch.setattr(dotenv, "load_dotenv", first_time_local_config)
    at.run()
    assert not at.exception
    assert os.environ["OPENAI_API_KEY"] == "test-only-no-api-call"
    # Never select or run the live provider in this configuration test.
    assert at.selectbox(key="generation_mode").value == "Sample walkthrough"
