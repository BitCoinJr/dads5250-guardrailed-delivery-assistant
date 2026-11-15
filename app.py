"""Local interactive demo. Business logic lives in delivery_assistant/."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from pydantic import ValidationError

from delivery_assistant.intake import parse_csv
from delivery_assistant.models import ChangeRequest
from delivery_assistant.workflow import DeliveryService

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=False)
project_evaluation = ROOT.parent.parent / "03_Evaluation"
default_runs = project_evaluation / "runs" if ROOT.parent.name == "02_Development" and project_evaluation.is_dir() else ROOT / ".runs"
RUNS = Path(os.environ.get("DELIVERY_RUNS_DIR", str(default_runs))).resolve()

st.set_page_config(page_title="Request to review", page_icon=":material/account_tree:", layout="wide")
st.session_state.setdefault("active_run", None)
st.session_state.setdefault("view", "1  Request")
if "next_view" in st.session_state:
    st.session_state["view"] = st.session_state.pop("next_view")


def navigate(view: str) -> None:
    st.session_state["next_view"] = view
    st.rerun()


def remember_run(result: dict) -> None:
    st.session_state["active_run"] = result["run_id"]
    st.session_state["next_view"] = "2  Evidence and plan"
    st.rerun()


def show_status(result: dict) -> None:
    labels = {
        "awaiting_approval": ("success", "Validation passed. Ready for human review."),
        "approved": ("success", "Approved. The reviewed patch package is ready to download."),
        "needs_clarification": ("warning", "More information is needed. Update the requirement and prepare a new run."),
        "blocked": ("error", "The request was blocked by an input safety check."),
        "validation_failed": ("error", "Validation failed. Approval is disabled."),
        "rejected": ("warning", "The reviewer rejected this proposal."),
        "revision_requested": ("warning", "The reviewer requested a revision. Create a new run below."),
        "error": ("error", "This run could not finish. Review the safe error details below."),
    }
    kind, message = labels.get(result.get("status", ""), ("info", "Run in progress."))
    getattr(st, kind)(message)
    st.caption(f"Run {result['run_id']} | {'OpenAI API' if result.get('mode') == 'openai' else 'Sample mode - deterministic, no AI call'}")
    for warning in result.get("warnings", []):
        st.warning(str(warning))


with st.sidebar:
    st.subheader("Delivery assistant")
    mode_label = st.selectbox("Generation mode", ["Sample walkthrough", "OpenAI API"], key="generation_mode")
    mode = "openai" if mode_label == "OpenAI API" else "sample"
    model = st.text_input("OpenAI model", value=os.environ.get("OPENAI_MODEL", "gpt-6.1-sol"), placeholder="Set OPENAI_MODEL or enter a model ID", key="model_id") if mode == "openai" else None
    if mode == "openai":
        st.caption("API key: configured" if os.environ.get("OPENAI_API_KEY") else "API key: not configured")
    else:
        st.caption("Runs without credentials. Outputs come from bounded sample templates.")
    st.divider()
    history = []
    if RUNS.exists():
        for state_file in sorted(RUNS.glob("*/state.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:30]:
            try:
                state = json.loads(state_file.read_text(encoding="utf-8"))
                history.append((state["run_id"], f"{state.get('status', '')} | {(state.get('ticket') or {}).get('title', (state.get('request') or {}).get('title', state['run_id']))}"))
            except (OSError, ValueError, KeyError, AttributeError):
                continue
    if history:
        run_labels = dict(history)
        chosen = st.selectbox("Saved runs", list(run_labels), format_func=lambda key: run_labels[key], key="saved_run")
        if st.button("Open saved run", key="open_saved"):
            st.session_state["active_run"] = chosen
            st.session_state["next_view"] = "2  Evidence and plan"
            st.rerun()
    st.caption("DADS5250 | Satoshi Nakamura | Solo")

service = DeliveryService(ROOT / "sample_repo", RUNS, mode=mode, model=model)
st.title("Request to review")
st.markdown("Turn a spreadsheet request into a tested data change that a person can review.")
st.caption("Google Sheets CSV → structured ticket → repository evidence → proposed changes → automated checks → human approval")
if mode == "sample":
    st.info("Sample walkthrough: extraction and patches use deterministic fixtures. Switch to OpenAI API for actual AI generation.")
else:
    st.info("OpenAI mode sends the selected request and allowlisted sample repository excerpts to the API when you prepare a run.")

view = st.segmented_control("Workflow", ["1  Request", "2  Evidence and plan", "3  Changes and checks", "4  Human review"], key="view", selection_mode="single")
result = None
if st.session_state.get("active_run"):
    try:
        result = service.load(st.session_state["active_run"])
    except (OSError, ValueError, KeyError) as exc:
        st.error(f"The saved run could not be opened: {type(exc).__name__}.")

if view == "1  Request":
    st.subheader("Start with a spreadsheet request")
    source = st.segmented_control("Input source", ["Sample CSV", "Upload CSV"], default="Sample CSV", key="input_source")
    data = None
    if source == "Sample CSV":
        sample_files = sorted((ROOT / "inputs").glob("*.csv"))
        if sample_files:
            sample_names = [p.name for p in sample_files]
            sample_name = st.selectbox("Sample file", sample_names, index=sample_names.index("sample_request.csv") if "sample_request.csv" in sample_names else 0, format_func=lambda name: Path(name).stem.replace("_", " "), key="sample_file")
            if sample_name not in sample_names:
                st.error("Choose one of the available sample files.")
                st.stop()
            data = (ROOT / "inputs" / sample_name).read_bytes()
            st.download_button("Download this CSV", data=data, file_name=sample_name, mime="text/csv", key="download_input")
    else:
        uploaded = st.file_uploader("Google Sheets CSV export", type=["csv"], key="csv_upload", help="Required columns: request_id, title, description. Include acceptance_criteria and target_metric where available.")
        if uploaded is not None:
            data = uploaded.getvalue()
    if data is not None:
        try:
            requests = parse_csv(data)
            selected = st.selectbox("Request to process", range(len(requests)), format_func=lambda i: f"{requests[i].request_id} | {requests[i].title}", key="request_row")
            request = requests[selected]
            fingerprint = hashlib.sha256(data + str(selected).encode()).hexdigest()[:10]
            st.caption("You can clarify the request before starting. The MVP supports revenue changes that exclude order statuses.")
            with st.form(f"request_form_{fingerprint}"):
                title = st.text_input("Title", value=request.title, max_chars=200, key=f"title_{fingerprint}")
                description = st.text_area("Business requirement", value=request.description, height=120, max_chars=6000, key=f"description_{fingerprint}")
                criteria = st.text_area("Acceptance criteria", value=request.acceptance_criteria, height=80, max_chars=3000, key=f"criteria_{fingerprint}")
                submitted = st.form_submit_button("Prepare and validate", type="primary", key="prepare")
            if submitted:
                if mode == "openai" and (not os.environ.get("OPENAI_API_KEY") or not model or not model.strip()):
                    st.error("Set OPENAI_API_KEY in .env and choose a model before running OpenAI mode.")
                else:
                    updated = request.model_copy(update={"title": title, "description": description, "acceptance_criteria": criteria})
                    updated = ChangeRequest.model_validate(updated.model_dump())
                    with st.spinner("Preparing the ticket, evidence, changes and validation results…"):
                        prepared = service.run(updated)
                    remember_run(prepared)
        except (ValueError, UnicodeError, ValidationError) as exc:
            st.error("Check the required request fields and text limits." if isinstance(exc, ValidationError) else str(exc))
    with st.expander("What happens in this demo?"):
        st.markdown("1. Structured Output turns the request into a typed ticket.\n2. RAG retrieves relevant repository evidence.\n3. LangGraph coordinates analysis, patch generation and validation.\n4. A person reviews the evidence and makes the final decision.")
        st.caption("The source repository stays read-only. Live Sheets/Jira integration and production merge/release are future work.")
elif result is None:
    st.info("Import a CSV and prepare a request first, or open a saved run.")
elif view == "2  Evidence and plan":
    show_status(result)
    ticket = result.get("ticket") or {}
    if ticket:
        st.subheader("Structured ticket")
        st.text(ticket.get("title", ""))
        st.text(ticket.get("summary", ""))
        st.caption("Metric: " + str(ticket.get("metric", "revenue")) + " | Excluded statuses: " + ", ".join(ticket.get("excluded_statuses", [])))
        for question in ticket.get("clarification_questions", []):
            st.warning(str(question))
        with st.expander("Ticket JSON"):
            st.json(ticket)
    plan = result.get("plan") or {}
    if plan:
        st.subheader("Impact analysis and change plan")
        st.text(plan.get("summary", ""))
        st.dataframe([{"Affected file": p} for p in plan.get("affected_files", [])], hide_index=True, alt="Files affected by the proposed change")
        for index, step in enumerate(plan.get("steps", []), 1):
            st.text(f"{index}. {step}")
        for risk in plan.get("risks", []):
            st.caption("Review consideration: " + str(risk))
    evidence = result.get("evidence") or []
    if evidence:
        st.subheader("Repository evidence")
        st.caption("RAG retrieves relevant source files. Retrieved text is treated as untrusted data.")
        for index, item in enumerate(evidence):
            with st.expander(str(item["path"])):
                st.caption(str(item.get("reason", "")))
                st.code(item.get("content", ""), language="text")
    if result.get("changes"):
        if st.button("Review changes and checks", type="primary", key="to_checks"):
            navigate("3  Changes and checks")
    elif st.button("Update the request", key="back_request"):
        navigate("1  Request")
elif view == "3  Changes and checks":
    show_status(result)
    validation = result.get("validation") or {}
    st.subheader("Automated checks")
    if validation:
        cols = st.columns(3)
        for col, key, label in zip(cols, ["baseline_total", "proposed_total", "expected_total"], ["Original revenue", "Proposed revenue", "Expected by acceptance rule"]):
            value = validation.get(key)
            col.metric(label, f"{value:,.2f}" if value is not None else "—")
        short_details = {
            "dbt build and data tests": "Predefined dbt models and data tests completed.",
            "Trusted pytest acceptance tests": "Independent daily revenue, dashboard and documentation checks completed.",
        }
        checks = [{"Check": c["name"], "Result": "PASS" if c["passed"] else "FAIL", "Details": short_details.get(c["name"], c["details"][:180]) if c["passed"] else c["details"][:180]} for c in validation.get("checks", [])]
        st.dataframe(checks, hide_index=True, alt="Automated validation results")
        with st.expander("Detailed check results"):
            for check in validation.get("checks", []):
                st.text(check["name"])
                st.code(check["details"], language="text")
        with st.expander("Validation commands"):
            for command in validation.get("executed_commands", []):
                st.code(command, language="text")
    else:
        st.info("Validation has not run for this request.")
    st.subheader("Proposed diff")
    st.code(result.get("diff") or "No changes were generated.", language="diff")
    st.caption("Changes are staged only in a run-specific workspace. Approval does not merge or release them.")
    if result.get("status") in {"awaiting_approval", "approved", "rejected", "revision_requested"}:
        if st.button("Continue to human review", type="primary", key="to_approval"):
            navigate("4  Human review")
elif view == "4  Human review":
    show_status(result)
    st.subheader("Reviewer decision")
    st.caption("This is a local demo. The reviewer name is recorded for traceability and is not an authenticated identity.")
    if result.get("status") == "awaiting_approval":
        reviewer = st.text_input("Reviewer name", value="Satoshi Nakamura", max_chars=100, key=f"reviewer_{result['run_id']}")
        comment = st.text_area("Review comment", max_chars=2000, placeholder="Record your reasoning, or explain what needs to change.", key=f"comment_{result['run_id']}")
        acknowledged = st.checkbox("I reviewed the evidence, diff and validation results.", key=f"ack_{result['run_id']}")
        with st.container(horizontal=True):
            for label, decision, key in [("Approve patch", "approved", "approve"), ("Request revision", "revision_requested", "revise"), ("Reject proposal", "rejected", "reject")]:
                clicked = st.button(label, type="primary" if decision == "approved" else "secondary", disabled=not acknowledged or not reviewer.strip(), key=key)
                if clicked:
                    try:
                        service.decide(result["run_id"], decision, reviewer.strip(), comment.strip())
                        st.rerun()
                    except (ValueError, OSError) as exc:
                        st.error(str(exc))
    if result.get("status") == "approved":
        try:
            bundle = service.export_bundle(result["run_id"])
            st.download_button("Download approved patch package", data=bundle, file_name=f"approved_patch_{result['run_id']}.zip", mime="application/zip", type="primary", key="download_approved")
        except (OSError, ValueError) as exc:
            st.error(str(exc))
    if result.get("status") in {"revision_requested", "validation_failed", "needs_clarification", "rejected"}:
        original = result.get("request") or {}
        with st.form("revision_form"):
            revised_description = st.text_area("Clarified or revised requirement", value=original.get("description", ""), max_chars=6000, key="revised_description")
            revised_criteria = st.text_area("Revised acceptance criteria", value=original.get("acceptance_criteria", ""), max_chars=3000, key="revised_criteria")
            feedback = st.text_area("Revision context", max_chars=2000, key="revision_feedback")
            regenerate = st.form_submit_button("Create a revised run", key="regenerate")
        if regenerate:
            try:
                revised = ChangeRequest.model_validate({**original, "description": revised_description, "acceptance_criteria": revised_criteria})
                with st.spinner("Preparing a new run for review…"):
                    prepared = service.run(revised, feedback=feedback)
                remember_run(prepared)
            except (ValueError, ValidationError) as exc:
                st.error("Check the revised request fields and text limits." if isinstance(exc, ValidationError) else str(exc))
    with st.expander("Audit events", expanded=False):
        st.json(result.get("events", []))
    with st.expander("Review record"):
        public_record = {k:v for k,v in result.items() if k not in {"run_dir", "changes"}}
        st.json(public_record)
