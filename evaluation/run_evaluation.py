"""Run labeled fixtures through the same service used by the interactive app.

This is a small regression/evaluation set, not a general AI benchmark. Sample
mode checks deterministic fixture behavior. OpenAI mode measures actual model
responses and requires the user's configured API key and model.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
from datetime import datetime, timezone
from decimal import Decimal
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from pydantic import ValidationError

from delivery_assistant.intake import parse_csv
from delivery_assistant.models import Ticket
from delivery_assistant.workflow import DeliveryService

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "not installed"


def _requests(relative_csv: str) -> dict:
    return {
        request.request_id: request
        for request in parse_csv((PROJECT_ROOT / relative_csv).read_bytes())
    }


def _gold_total(repo: Path, excluded_statuses: list[str]) -> float:
    """Compute expected revenue from the manual label, not the model's ticket."""
    with (repo / "seeds" / "orders.csv").open(encoding="utf-8-sig", newline="") as source:
        rows = csv.DictReader(source)
        return float(sum(
            (Decimal(row["amount"]) for row in rows if row["status"] not in excluded_statuses),
            Decimal("0"),
        ))


def _normal_result(state: dict, label: dict, expected_files: set[str], repo: Path) -> dict:
    schema_valid = False
    policy_matches_gold = False
    try:
        ticket = Ticket.model_validate(state.get("ticket"))
        schema_valid = True
        policy_matches_gold = set(ticket.excluded_statuses) == set(label["excluded_statuses"])
    except (ValidationError, TypeError):
        pass
    plan = state.get("plan") or {}
    predicted_files = set(plan.get("affected_files") or [])
    true_positive = len(predicted_files & expected_files)
    false_positive = len(predicted_files - expected_files)
    false_negative = len(expected_files - predicted_files)
    validation = state.get("validation") or {}
    proposed_total = validation.get("proposed_total")
    expected_total = _gold_total(repo, label["excluded_statuses"])
    # Catch a changed seed or stale hand-written gold file rather than report a false result.
    if not math.isclose(expected_total, label["expected_total"], abs_tol=0.005):
        raise ValueError(f"Gold fixture total is stale for {label['request_id']}")
    total_matches_gold = (
        isinstance(proposed_total, (int, float))
        and math.isclose(proposed_total, expected_total, abs_tol=0.005)
    )
    validation_passed = validation.get("passed") is True
    return {
        "request_id": label["request_id"],
        "run_id": state.get("run_id"),
        "status": state.get("status", "error"),
        "schema_valid": schema_valid,
        "policy_matches_gold": policy_matches_gold,
        "predicted_files": sorted(predicted_files),
        "expected_files": sorted(expected_files),
        "impact_true_positive": true_positive,
        "impact_false_positive": false_positive,
        "impact_false_negative": false_negative,
        "impact_precision": true_positive / len(predicted_files) if predicted_files else 0.0,
        "impact_recall": true_positive / len(expected_files) if expected_files else 0.0,
        "validation_passed": validation_passed,
        "check_outcomes": [
            {"name": check.get("name"), "passed": check.get("passed") is True}
            for check in validation.get("checks", [])
        ],
        "expected_revenue_from_manual_label": expected_total,
        "proposed_revenue": proposed_total,
        "revenue_matches_gold": total_matches_gold,
        "acceptance_passed": schema_valid and policy_matches_gold and validation_passed and total_matches_gold,
        "ready_for_human_review": state.get("status") == "awaiting_approval",
    }


def evaluate(mode: str, output: Path, model: str | None = None) -> dict:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    if mode == "openai" and not (os.getenv("OPENAI_API_KEY") and (model or os.getenv("OPENAI_MODEL"))):
        raise ValueError("OpenAI evaluation requires OPENAI_API_KEY and OPENAI_MODEL.")
    dataset = json.loads((PROJECT_ROOT / "evaluation" / "cases.json").read_text(encoding="utf-8"))
    repo = PROJECT_ROOT / "sample_repo"
    evaluation_id = uuid4().hex
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    service = DeliveryService(repo, output.parent / "runs" / evaluation_id, mode=mode, model=model)
    expected_files = set(dataset["expected_affected_files"])
    normal_requests = _requests(dataset["normal_csv"])
    adversarial_requests = _requests(dataset["adversarial_csv"])
    clarification_requests = _requests(dataset["clarification_csv"])
    normal_results = []
    adversarial_results = []
    clarification_results = []

    for label in dataset["normal_cases"]:
        print(f"Normal case: {label['request_id']}", flush=True)
        state = service.run(normal_requests[label["request_id"]])
        normal_results.append(_normal_result(state, label, expected_files, repo))
    for label in dataset["adversarial_cases"]:
        print(f"Adversarial case: {label['request_id']}", flush=True)
        state = service.run(adversarial_requests[label["request_id"]])
        adversarial_results.append({
            "request_id": label["request_id"], "category": label["category"],
            "run_id": state.get("run_id"), "status": state.get("status"),
            "blocked": state.get("status") == label["expected_status"],
            "blocked_before_generation": (
                state.get("status") == "blocked"
                and not state.get("ticket")
                and not state.get("evidence")
                and not state.get("changes")
            ),
        })
    for label in dataset["clarification_cases"]:
        print(f"Clarification case: {label['request_id']}", flush=True)
        state = service.run(clarification_requests[label["request_id"]])
        clarification_results.append({
            "request_id": label["request_id"], "run_id": state.get("run_id"),
            "status": state.get("status"),
            "correctly_paused": state.get("status") == label["expected_status"],
            "clarification_question_count": len((state.get("ticket") or {}).get("clarification_questions", [])),
        })

    n = len(normal_results)
    attacks = len(adversarial_results)
    tp = sum(r["impact_true_positive"] for r in normal_results)
    fp = sum(r["impact_false_positive"] for r in normal_results)
    fn = sum(r["impact_false_negative"] for r in normal_results)
    report = {
        "evaluation_id": evaluation_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "model": (model or os.getenv("OPENAI_MODEL")) if mode == "openai" else None,
        "interpretation": (
            "Deterministic sample-mode regression results; these are not live AI quality measurements."
            if mode == "sample" else
            "Live OpenAI results on a small synthetic labeled set; not a general performance benchmark."
        ),
        "dataset_version": dataset["dataset_version"],
        "dependencies": {name: _version(name) for name in ("streamlit", "langgraph", "openai", "dbt-duckdb", "duckdb")},
        "summary": {
            "normal_cases": n,
            "adversarial_cases": attacks,
            "ticket_schema_validity": sum(r["schema_valid"] for r in normal_results) / n,
            "policy_extraction_accuracy": sum(r["policy_matches_gold"] for r in normal_results) / n,
            "impact_precision_micro": tp / (tp + fp) if tp + fp else 0.0,
            "impact_recall_micro": tp / (tp + fn) if tp + fn else 0.0,
            "automated_validation_pass_rate": sum(r["validation_passed"] for r in normal_results) / n,
            "acceptance_pass_rate_against_manual_gold": sum(r["acceptance_passed"] for r in normal_results) / n,
            "ready_for_review_rate": sum(r["ready_for_human_review"] for r in normal_results) / n,
            "prohibited_input_block_rate": sum(1 for r in adversarial_results if r["blocked"] is True) / attacks,
            "clarification_cases_correct": sum(1 for r in clarification_results if r["correctly_paused"] is True),
        },
        "normal_results": normal_results,
        "adversarial_results": adversarial_results,
        "clarification_results": clarification_results,
        "limitations": [
            "Six closely related requests and three attacks are too small to establish general reliability.",
            "Affected-file gold labels all concern a single revenue metric in one sample repository.",
            "Regex input filtering is only one mitigation and does not prove resistance to prompt injection.",
            "Automated checks support a human decision; the evaluation does not approve, merge or release changes.",
        ],
    }
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("sample", "openai"), default="sample")
    parser.add_argument("--model", default=None, help="OpenAI model; defaults to OPENAI_MODEL.")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    output = args.output or PROJECT_ROOT / ".runs" / "evaluation" / f"{args.mode}_latest.json"
    print("Mode:", "deterministic sample (not live AI)" if args.mode == "sample" else "live OpenAI", flush=True)
    try:
        report = evaluate(args.mode, output, args.model)
    except Exception as exc:
        # Do not echo provider exception text: it can contain request or connection details.
        print(f"Evaluation did not complete ({type(exc).__name__}). Check local setup and configuration.")
        return 1
    print(json.dumps(report["summary"], indent=2))
    print(f"Saved evaluation report: {output.resolve()}")
    summary = report["summary"]
    return 0 if all((
        summary["acceptance_pass_rate_against_manual_gold"] == 1.0,
        summary["ready_for_review_rate"] == 1.0,
        summary["prohibited_input_block_rate"] == 1.0,
        summary["clarification_cases_correct"] == len(report["clarification_results"]),
    )) else 2


if __name__ == "__main__":
    raise SystemExit(main())
