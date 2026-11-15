"""BA intake screen: read, estimate, then make a recorded human decision."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

from .backlog_models import BacklogItem
from .google_sheets import EXPECTED_SHEET_ID, GoogleSheetsError, connection_status, read_backlog
from .provider import redact
from .triage import TriageService


def demo_items(root: Path) -> list[BacklogItem]:
    return [BacklogItem.model_validate(row) for row in json.loads((root / "inputs/backlog_demo.json").read_text(encoding="utf-8"))]


def fresh_items(source: str, root: Path) -> list[BacklogItem]:
    if source == "Google Sheets":
        return read_backlog(EXPECTED_SHEET_ID, project_root=root)
    if source == "Demo backlog":
        return demo_items(root)
    raise ValueError("Choose an available backlog source.")


def batch_fingerprint(items: list[BacklogItem]) -> str:
    payload = [item.model_dump() for item in items]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def safe(value: object) -> str:
    return str(redact(str(value)))


def matrix(recommendations: list[dict], items: dict[str, BacklogItem]) -> None:
    st.subheader("Business impact and change volume")
    st.caption("Top row: high business impact. Left column: smaller change. Estimates are provisional; BA makes the Go decision.")
    cells = [
        ("high_small", "High impact / Small change", "Prioritize for a Go discussion"),
        ("high_large", "High impact / Large change", "Plan the scope or split into phases"),
        ("low_small", "Low impact / Small change", "Batch when capacity is available"),
        ("low_large", "Low impact / Large change", "Defer or revisit the business case"),
    ]
    for row in range(2):
        columns = st.columns(2)
        for column, (key, title, action) in zip(columns, cells[row * 2:row * 2 + 2]):
            with column.container(border=True, height="stretch"):
                st.markdown(f"**{title}**")
                st.caption(action)
                members = [rec for rec in recommendations if rec.get("quadrant_key") == key]
                if not members:
                    st.caption("No requests in this quadrant.")
                for rec in members:
                    item = items[rec["request_id"]]
                    st.text(f"{item.request_id}  {safe(item.title)}")
                    st.caption(f"BA: {item.ba_status} | Suggested: {rec['suggested_action']} | Confidence: {rec.get('confidence', 'Low')}")
    unknown = [rec for rec in recommendations if rec.get("quadrant_key") not in {cell[0] for cell in cells}]
    if unknown:
        st.info("Needs estimation: " + ", ".join(rec["request_id"] for rec in unknown) + ". Review the missing business context or repository evidence before assigning a quadrant.")


def render_backlog(root: Path, runs_root: Path, resources: dict, mode: str, model: str | None) -> None:
    st.subheader("BA request intake")
    st.markdown("Business users record a request, discuss it with BA, and agree on priority and timing. Review the estimated impact and change volume before selecting a delivery candidate.")
    if resources.get("request_sheet_url"):
        st.link_button("Open the business request backlog", resources["request_sheet_url"])
    source = st.segmented_control("Backlog source", ["Demo backlog", "Google Sheets"], default="Demo backlog", key="backlog_source")
    if source not in {"Demo backlog", "Google Sheets"}:
        st.info("Choose a backlog source.")
        return
    if st.session_state.get("loaded_backlog_source") != source:
        st.session_state.pop("backlog_snapshot", None)
        st.session_state.pop("triage_review_id", None)
        st.session_state["loaded_backlog_source"] = source
    if source == "Demo backlog":
        st.caption("Synthetic business queue captured for the demonstration. This is not a live Google read.")
        if "backlog_snapshot" not in st.session_state:
            st.session_state["backlog_snapshot"] = [item.model_dump() for item in demo_items(root)]
            st.session_state["backlog_loaded_at"] = datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(timespec="seconds")
    else:
        setup = connection_status(root)
        st.caption(safe(setup["message"]))
        if not setup["configured"]:
            with st.expander("Connect Google once"):
                st.markdown("Use the Japanese setup guide in the project. Save your Google Desktop OAuth client locally, then run the connection command. The app requests read-only Sheets access and reads only the configured backlog.")
                st.code(".\\.venv\\Scripts\\python.exe scripts/connect_google.py", language="powershell")
                st.caption("Credentials stay in the ignored .secrets folder. The app does not change sharing or write decisions back to the spreadsheet.")
    if st.button("Refresh Google Sheets" if source == "Google Sheets" else "Reload demo backlog", key="refresh_backlog"):
        try:
            with st.spinner("Reading the request backlog…"):
                loaded = fresh_items(source, root)
            st.session_state["backlog_snapshot"] = [item.model_dump() for item in loaded]
            st.session_state["backlog_loaded_at"] = datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(timespec="seconds")
            st.session_state.pop("triage_review_id", None)
        except (ValueError, OSError) as exc:
            st.session_state.pop("backlog_snapshot", None)
            st.session_state.pop("triage_review_id", None)
            st.error(safe(str(exc)) if isinstance(exc, GoogleSheetsError) else "The backlog could not be loaded. Check the source and setup guide.")
    snapshot = st.session_state.get("backlog_snapshot")
    if not snapshot:
        st.info("Connect Google and refresh to read the private sheet directly, or choose Demo backlog to explore the workflow without credentials.")
        return
    items = [BacklogItem.model_validate(row) for row in snapshot]
    by_id = {item.request_id: item for item in items}
    st.caption(f"{len(items)} requests | Loaded {st.session_state.get('backlog_loaded_at', '')} | Decisions are recorded in the local audit log.")
    with st.expander("Review scope", expanded=len(items) > 30):
        chosen = st.multiselect("Requests in this review", list(by_id), default=list(by_id) if len(by_id) <= 30 else [], max_selections=30, key="triage_batch", format_func=lambda key: f"{key} | {safe(by_id[key].title)}")
        st.caption("Choose up to 30 requests for one bounded review. Completed or held requests remain visible and cannot be auto-started.")
    if any(key not in by_id for key in chosen) or len(chosen) > 30:
        st.error("Choose requests from the current backlog.")
        return
    selected_items = [by_id[key] for key in chosen]
    as_of = st.date_input("Planning date", value=datetime.now(ZoneInfo("Asia/Tokyo")).date(), key="triage_as_of")
    service = TriageService(runs_root, mode=mode, model=model, repo_root=root / "sample_repo")
    signature = (source, batch_fingerprint(selected_items), mode, model, str(as_of))
    if st.button("Estimate impact and change volume", type="primary", disabled=not chosen, key="estimate_backlog"):
        if mode == "openai" and (not os.environ.get("OPENAI_API_KEY") or not model or not model.strip()):
            st.error("Configure the OpenAI API key and model before requesting AI estimates.")
        else:
            with st.spinner("Reviewing business context and dbt repository evidence…"):
                review = service.review(selected_items, as_of=as_of)
            st.session_state["triage_review_id"] = review["review_id"]
            st.session_state["triage_signature"] = signature
    review_id = st.session_state.get("triage_review_id")
    if not review_id or st.session_state.get("triage_signature") != signature:
        st.dataframe([
            {"ID": item.request_id, "Request": safe(item.title), "BA impact": item.business_impact, "Priority": item.priority, "Desired by": item.desired_by, "BA status": item.ba_status}
            for item in selected_items
        ], hide_index=True, alt="Business request backlog before impact and change volume estimation")
        if review_id:
            st.info("The source, review scope or mode changed. Estimate again before making a decision.")
        return
    try:
        review = service.load(review_id)
    except (ValueError, OSError):
        st.error("The saved priority review could not be opened. Create a new review.")
        return
    if review.get("status") == "error":
        for message in review.get("warnings", []):
            st.error(safe(message))
        return
    st.caption("AI estimates" if review.get("mode") == "openai" else "Sample estimates from explicit rules and repository templates; no AI call was made.")
    st.text(safe(review.get("summary", "")))
    recommendations = review.get("recommendations", [])
    matrix(recommendations, by_id)
    with st.expander("Ranked queue and secondary rubric"):
        st.dataframe([
            {"Rank": rec["rank"], "ID": rec["request_id"], "Request": safe(by_id[rec["request_id"]].title), "Impact": rec.get("estimated_impact"), "Change volume": rec.get("estimated_change_volume"), "Suggestion": rec["suggested_action"], "BA status": by_id[rec["request_id"]].ba_status, "Due": by_id[rec["request_id"]].desired_by, "Rubric score": rec.get("rubric_score")}
            for rec in recommendations
        ], hide_index=True, alt="Ranked requests with impact, change volume, BA readiness and timing")
        st.json(review.get("rubric", {}))
    if not recommendations:
        st.info("No requests are available for a BA decision.")
        return
    recommended = review.get("recommended_request_id")
    ordered = [rec["request_id"] for rec in recommendations]
    selected_id = st.selectbox("Request for BA decision", ordered, index=ordered.index(recommended) if recommended in ordered else 0, key=f"ba_request_{review_id}", format_func=lambda key: f"{key} | {safe(by_id[key].title)}")
    item = by_id[selected_id]
    recommendation = next(rec for rec in recommendations if rec["request_id"] == selected_id)
    st.subheader(safe(item.title))
    st.text(safe(item.description))
    st.caption(f"Team: {safe(item.requester_team)} | BA: {item.ba_status} | Priority: {item.priority} | Desired by: {item.desired_by or 'Not agreed'}")
    columns = st.columns(3)
    columns[0].metric("Estimated business impact", recommendation.get("estimated_impact", "Unknown"))
    columns[1].metric("Estimated change volume", recommendation.get("estimated_change_volume", "Unknown"))
    columns[2].metric("Estimate confidence", recommendation.get("confidence", "Low"))
    st.text("Impact: " + safe(recommendation.get("impact_rationale", recommendation["rationale"])))
    st.text("Change volume: " + safe(recommendation.get("change_rationale", "")))
    count = recommendation.get("estimated_file_count")
    if count is not None:
        st.caption(f"Inspected template estimate: {count} changed files; {recommendation.get('estimated_model_count')} SQL model; {recommendation.get('estimated_line_delta')} added/removed text lines. This is a provisional scope estimate, not working hours.")
    for concern in recommendation.get("concerns", []):
        st.caption("Consideration: " + safe(concern))
    for reason in recommendation.get("eligibility_reasons", []):
        st.warning(safe(reason))
    with st.expander("Business and repository evidence"):
        st.text("BA notes: " + safe(item.ba_notes))
        st.text("Acceptance criteria: " + safe(item.acceptance_criteria))
        st.caption("BA initial effort: " + item.effort + ". The repository estimate is shown separately.")
        for evidence in recommendation.get("evidence", []):
            st.text(safe(evidence["path"]))
            st.code(safe(evidence.get("content", "")), language="text")
    st.subheader("BA decision")
    st.caption("AI recommends; BA decides. Go creates a Jira-style delivery handoff inside this demo. The sheet is read-only and the decision is recorded locally.")
    previous = next((row for row in review.get("decisions", []) if row["request_id"] == selected_id), None)
    if previous:
        st.info(f"{previous['decision']} was already recorded for this request in this review. Create a new estimate review to reconsider it.")
        with st.expander("Recorded BA decision"):
            st.json(redact(previous))
        return
    decision_key = review_id + "_" + selected_id
    with st.form(f"ba_decision_{review_id}_{selected_id}"):
        reviewer = st.text_input("BA reviewer", value="Satoshi Nakamura", max_chars=100, key="ba_reviewer_" + decision_key)
        comment = st.text_area("Decision rationale", max_chars=2000, placeholder="Explain the business priority, agreed timing and why this request should proceed.", key="ba_rationale_" + decision_key)
        confirmed = st.checkbox("I reviewed the business context, estimate and readiness.", key="ba_ack_" + decision_key)
        decision = st.selectbox("Decision", ["Go", "Hold", "Clarify"] if recommendation.get("can_deliver") else ["Hold", "Clarify"], key="ba_action_" + decision_key)
        submit = st.form_submit_button("Record BA decision", type="primary", disabled=not reviewer.strip(), key="record_ba_decision")
    if submit:
        if not confirmed or not reviewer.strip() or not comment.strip():
            st.error("Enter the reviewer and rationale, and confirm the review before recording a decision.")
        else:
            try:
                # Freshly read the source before Go; never reuse the reviewed row as its own freshness proof.
                current = {row.request_id: row for row in fresh_items(source, root)}
                if selected_id not in current:
                    raise ValueError("The source request no longer exists. Refresh and estimate again.")
                if any(key not in current for key in chosen) or batch_fingerprint([current[key] for key in chosen]) != batch_fingerprint(selected_items):
                    raise ValueError("The reviewed queue changed. Refresh and estimate again before recording a decision.")
                receipt = service.decide(review_id, selected_id, decision, reviewer.strip(), comment.strip(), current_item=current[selected_id])
                st.session_state["last_ba_decision"] = receipt
                if decision == "Go":
                    st.session_state["intake_handoff"] = {**receipt, "source": source}
                    st.session_state["next_view"] = "1  Request"
                    st.rerun()
                st.session_state["ba_flash"] = "BA decision recorded: " + decision
                st.rerun()
            except (ValueError, OSError) as exc:
                st.error(safe(str(exc)))
    with st.expander("Intake audit"):
        st.json(redact({"review_id": review_id, "events": review.get("events", []), "decisions": review.get("decisions", [])}))
