"""LangGraph workflow with a separate, persisted human approval boundary."""
from __future__ import annotations

import difflib
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
from datetime import datetime, timezone
from typing import Any, Mapping
from typing_extensions import TypedDict
from uuid import UUID, uuid4
import zipfile

from langgraph.graph import END, START, StateGraph

from .models import ChangeRequest, Ticket, Evidence, FileChange, Proposal, ValidationReport
from .provider import ALLOWED_CHANGE_PATHS, OpenAIProvider, SampleProvider, explicit_excluded_statuses, redact, request_clarifications, safety_issues
from .repository import RepoTools


class FlowState(TypedDict, total=False):
    run_id: str
    run_dir: str
    request: dict
    feedback: str
    status: str
    mode: str
    ticket: dict | None
    evidence: list[dict]
    plan: dict | None
    changes: list[dict]
    diff: str
    validation: dict | None
    warnings: list[str]
    events: list[dict]
    source_hashes: dict[str, str]
    decision: dict | None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _proposal_digest(state: dict) -> str:
    fields = ("run_id", "mode", "request", "feedback", "ticket", "evidence", "plan", "changes", "diff", "validation", "source_hashes")
    return hashlib.sha256(_json_bytes({key: state.get(key) for key in fields})).hexdigest()


class DeliveryService:
    def __init__(self, repo_root: Path, runs_root: Path, mode: str = "sample", model: str | None = None):
        if mode not in {"sample", "openai"}:
            raise ValueError("Choose sample or openai mode.")
        self.repo_root = Path(repo_root).resolve(strict=True)
        self.runs_root = Path(runs_root).resolve()
        if self.repo_root == self.runs_root or self.repo_root in self.runs_root.parents:
            raise ValueError("Run storage must be outside the read-only source repository.")
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self.mode, self.model = mode, model
        self.tools = RepoTools(self.repo_root)
        self.provider = None
        # LangGraph supports TypedDict state; ty cannot yet satisfy its internal StateLike protocol bound.
        graph = StateGraph(FlowState)  # ty: ignore[invalid-argument-type]
        graph.add_node("parse_request", self._parse)
        graph.add_node("retrieve_evidence", self._retrieve)
        graph.add_node("plan_and_generate", self._generate)
        graph.add_node("validate_changes", self._validate)
        graph.add_edge(START, "parse_request")
        graph.add_conditional_edges("parse_request", lambda s: "next" if s["status"] == "processing" else "stop", {"next": "retrieve_evidence", "stop": END})
        graph.add_conditional_edges("retrieve_evidence", lambda s: "next" if s["status"] == "processing" else "stop", {"next": "plan_and_generate", "stop": END})
        graph.add_conditional_edges("plan_and_generate", lambda s: "next" if s["status"] == "processing" else "stop", {"next": "validate_changes", "stop": END})
        graph.add_edge("validate_changes", END)
        self.graph = graph.compile()

    def _run_path(self, run_id: str, must_exist: bool = True) -> Path:
        try:
            parsed = UUID(run_id)
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Invalid run ID.") from None
        if str(parsed) != run_id:
            raise ValueError("Invalid run ID.")
        path = self.runs_root / run_id
        if path.is_symlink() or path.resolve().parent != self.runs_root:
            raise ValueError("Run path is outside the allowed run storage.")
        if must_exist and not path.is_dir():
            raise ValueError("Run not found.")
        return path

    def _event(self, state: Mapping[str, Any], stage: str, detail: str, status: str | None = None) -> list[dict]:
        events = list(state.get("events", []))
        events.append({"sequence": len(events) + 1, "at": _utc_now(), "stage": stage,
                       "status": status or state.get("status", "processing"), "detail": redact(detail)})
        return events

    def _save(self, state: dict) -> None:
        clean = redact(state)
        run_path = self._run_path(clean["run_id"])
        target = run_path / "state.json"
        if target.is_symlink() or (run_path / "audit.jsonl").is_symlink():
            raise ValueError("Run artifacts cannot be symbolic links.")
        self._write_run_text(run_path, "state.json", json.dumps(clean, ensure_ascii=False, indent=2))
        self._write_run_text(run_path, "audit.jsonl", "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in clean.get("events", [])))

    def _write_run_text(self, run_path: Path, filename: str, content: str) -> None:
        """Never follow an existing artifact link or a predictable temporary path."""
        if filename != Path(filename).name or run_path.is_symlink() or run_path.resolve().parent != self.runs_root:
            raise ValueError("Run artifact path is outside the allowed storage.")
        target = run_path / filename
        if target.is_symlink() or target.resolve().parent != run_path.resolve():
            raise ValueError("Run artifacts cannot be symbolic links or leave their run directory.")
        temp = run_path / (".write-" + str(uuid4()) + ".tmp")
        created = False
        try:
            # Exclusive creation prevents following a pre-existing hard/symbolic link.
            with temp.open("x", encoding="utf-8", newline="\n") as stream:
                created = True
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, target)
        finally:
            if created:
                temp.unlink(missing_ok=True)

    def _source_hashes(self, root: Path | None = None) -> dict[str, str]:
        root = root or self.repo_root
        hashes = {}
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            if any(p in {".git", "target", "logs", "dbt_packages", "__pycache__"} for p in relative.parts):
                continue
            if path.is_symlink():
                raise ValueError("The sample repository cannot contain symbolic links.")
            if path.is_file() and path.suffix.lower() in {".sql", ".yml", ".yaml", ".csv", ".md", ".json", ".py"}:
                if path.stat().st_size > 2_000_000:
                    raise ValueError("A source repository file exceeds the MVP size limit.")
                hashes[relative.as_posix()] = _hash_file(path)
        return hashes

    def _get_provider(self):
        if self.provider is None:
            self.provider = SampleProvider() if self.mode == "sample" else OpenAIProvider(self.model)
        return self.provider

    def run(self, request: ChangeRequest, feedback: str = "") -> dict:
        request = ChangeRequest.model_validate(request)
        if len(feedback) > 3000:
            raise ValueError("Revision feedback must be at most 3000 characters.")
        run_id = str(uuid4())
        run_dir = self._run_path(run_id, must_exist=False)
        run_dir.mkdir(exist_ok=False)
        state: dict[str, Any] = {
            "run_id": run_id, "run_dir": str(run_dir), "created_at": _utc_now(),
            "request": request.model_dump(), "feedback": feedback, "mode": self.mode,
            "model": (self.model or os.getenv("OPENAI_MODEL", "")) if self.mode == "openai" else None,
            "status": "processing", "ticket": None, "evidence": [], "plan": None,
            "changes": [], "diff": "", "validation": None, "events": [], "decision": None,
            "warnings": ["Sample mode uses deterministic fixtures and does not call an AI model."] if self.mode == "sample" else [],
            "source_hashes": {},
        }
        try:
            state["source_hashes"] = self._source_hashes()
            for step_update in self.graph.stream(state, stream_mode="updates"):
                for update in step_update.values():
                    state.update(update)
                self._save(state)
            if state.get("status") == "awaiting_approval":
                self._seal(redact(state))
        except Exception as exc:
            # Never persist exception bodies from third-party libraries or model data.
            if isinstance(exc, (ValueError, RuntimeError)) and str(exc).startswith(("Set OPENAI_", "OpenAI request did not complete")):
                message = str(exc)
            else:
                message = f"The run stopped safely ({type(exc).__name__}). Review the request and setup, then retry."
            state["status"] = "error"
            state["warnings"] = [*state.get("warnings", []), message]
            state["events"] = self._event(state, "error", message, "error")
        state = redact(state)
        self._save(state)
        return state

    def _parse(self, state: FlowState) -> dict:
        raw_text = json.dumps({"request": state["request"], "feedback": state["feedback"]}, ensure_ascii=False)
        issues = safety_issues(raw_text)
        if issues:
            return {"status": "blocked", "warnings": state["warnings"] + issues,
                    "events": self._event(state, "guardrails", "Input blocked before any model call or repository retrieval.", "blocked")}
        request = ChangeRequest.model_validate(state["request"])
        preflight_questions = request_clarifications(request)
        if preflight_questions:
            ticket = SampleProvider().extract(request)
            return {"ticket": ticket.model_dump(), "status": "needs_clarification",
                    "events": self._event(state, "requirements_preflight", "Original request needs clarification before any model call or retrieval.", "needs_clarification")}
        ticket = self._get_provider().extract(request, state["feedback"])
        if ticket.request_id != request.request_id:
            raise ValueError("Generated ticket request ID does not match its input.")
        ticket_issues = safety_issues(ticket.model_dump_json())
        if ticket_issues:
            return {"status": "blocked", "warnings": state["warnings"] + ticket_issues,
                    "events": self._event(state, "guardrails", "Generated ticket did not pass output filtering.", "blocked")}
        explicit = explicit_excluded_statuses(request.description + "\n" + request.acceptance_criteria)
        if explicit and set(explicit) != set(ticket.excluded_statuses):
            ticket.clarification_questions.append("The extracted status policy differs from the explicit input. Confirm the exclusion list.")
        if ticket.metric != "revenue" or not ticket.excluded_statuses:
            if not ticket.clarification_questions:
                ticket.clarification_questions.append("Specify a supported revenue status-exclusion policy.")
        status = "processing" if ticket.supported and not ticket.clarification_questions else "needs_clarification"
        return {"ticket": ticket.model_dump(), "status": status,
                "events": self._event(state, "structured_output", "Ticket schema validated." if status == "processing" else "Requirements need clarification before generation.", status)}

    def _retrieve(self, state: FlowState) -> dict:
        ticket = Ticket.model_validate(state["ticket"])
        evidence = self.tools.retrieve(" ".join([ticket.title, ticket.summary, ticket.metric, *ticket.excluded_statuses]), limit=8)
        if not evidence:
            return {"status": "blocked", "warnings": [*state["warnings"], "No repository evidence was found. Generation stopped."],
                    "events": self._event(state, "repository_rag", "No evidence was retrieved.", "blocked")}
        if any(safety_issues(e.content) for e in evidence):
            return {"status": "blocked", "warnings": [*state["warnings"], "Retrieved text failed the untrusted-content safety filter."],
                    "events": self._event(state, "repository_rag", "Unsafe retrieved content blocked before generation.", "blocked")}
        return {"evidence": [e.model_dump() for e in evidence],
                "events": self._event(state, "repository_rag", f"Retrieved {len(evidence)} repository evidence records with source paths.")}

    def _generate(self, state: FlowState) -> dict:
        ticket = Ticket.model_validate(state["ticket"])
        evidence = [Evidence.model_validate(item) for item in state["evidence"]]
        proposal = self._get_provider().propose(ticket, evidence, self.tools, state["feedback"])
        proposal = Proposal.model_validate(proposal)
        for change in proposal.changes:
            change.content = change.content.replace("\r\n", "\n")
            if not change.content.endswith("\n"):
                change.content += "\n"
        paths = [change.path for change in proposal.changes]
        allowed = set(ALLOWED_CHANGE_PATHS)
        if len(paths) != 4 or set(paths) != allowed or len(paths) != len(set(paths)):
            return {"status": "blocked", "warnings": [*state["warnings"], "The proposal attempted to change files outside the four-file allowlist."],
                    "events": self._event(state, "guardrails", "Generated file paths failed the allowlist.", "blocked")}
        if set(proposal.plan.affected_files) != allowed:
            return {"status": "blocked", "warnings": [*state["warnings"], "The proposed impact plan does not match the allowed change scope."],
                    "events": self._event(state, "guardrails", "Impact scope did not match the allowed paths.", "blocked")}
        if not proposal.plan.evidence_paths or not set(proposal.plan.evidence_paths).issubset({e.path for e in evidence}):
            return {"status": "blocked", "warnings": [*state["warnings"], "The plan contains missing or unverified repository citations."],
                    "events": self._event(state, "guardrails", "Evidence citations did not match retrieved paths.", "blocked")}
        if any(len(change.content) > 100_000 for change in proposal.changes) or safety_issues(proposal.model_dump_json()):
            return {"status": "blocked", "warnings": [*state["warnings"], "Generated content failed the size or secret/instruction filter."],
                    "events": self._event(state, "guardrails", "Generated content was blocked before validation.", "blocked")}
        diff_parts = []
        for change in proposal.changes:
            original_path = self.repo_root.joinpath(*PurePosixPath(change.path).parts)
            if original_path.is_symlink() or not original_path.resolve().is_relative_to(self.repo_root):
                raise ValueError("Source change path is outside the repository.")
            original = original_path.read_text(encoding="utf-8")
            diff_parts.extend(difflib.unified_diff(original.splitlines(keepends=True), change.content.splitlines(keepends=True), fromfile="a/" + change.path, tofile="b/" + change.path))
        return {"plan": proposal.plan.model_dump(), "changes": [c.model_dump() for c in proposal.changes],
                "diff": "".join(diff_parts),
                "events": self._event(state, "planning_and_generation", "Generated a cited impact plan and four bounded file replacements.")}

    def _validate(self, state: FlowState) -> dict:
        report = self.tools.validate(Ticket.model_validate(state["ticket"]), [FileChange.model_validate(c) for c in state["changes"]], self._run_path(state["run_id"]))
        report = ValidationReport.model_validate(report)
        if report.passed and (not report.checks or not all(check.passed for check in report.checks)):
            raise ValueError("Inconsistent validation report.")
        status = "awaiting_approval" if report.passed else "validation_failed"
        return {"validation": report.model_dump(), "status": status,
                "events": self._event(state, "automated_validation", "Checks passed. Waiting for an explicit human decision." if report.passed else "Checks failed. Approval and patch export are disabled.", status)}

    def _seal(self, state: dict) -> None:
        run_path = self._run_path(state["run_id"])
        workspace = run_path / "workspace"
        if workspace.is_symlink() or not workspace.is_dir():
            raise ValueError("Validated workspace is missing or unsafe.")
        workspace_hashes = {}
        for change in state["changes"]:
            target = workspace.joinpath(*PurePosixPath(change["path"]).parts)
            if target.is_symlink() or not target.is_file() or not target.resolve().is_relative_to(workspace.resolve()):
                raise ValueError("Validated workspace is missing an allowed changed file.")
            expected = hashlib.sha256(change["content"].encode("utf-8")).hexdigest()
            actual = _hash_file(target)
            # Text files are staged with a platform-independent newline convention.
            if actual != expected:
                normalized = target.read_text(encoding="utf-8").replace("\r\n", "\n")
                if normalized != change["content"].replace("\r\n", "\n"):
                    raise ValueError("Validated workspace differs from the generated proposal.")
            workspace_hashes[change["path"]] = actual
        manifest = {"proposal_sha256": _proposal_digest(state), "workspace_hashes": workspace_hashes,
                    "workspace_source_hashes": self._source_hashes(workspace),
                    "sealed_at": _utc_now(), "note": "Local integrity check; not a signature or an authentication mechanism."}
        self._write_run_text(run_path, "validation_manifest.json", json.dumps(manifest, indent=2))

    def load(self, run_id: str) -> dict:
        run_path = self._run_path(run_id)
        state_path = run_path / "state.json"
        if state_path.is_symlink() or not state_path.is_file():
            raise ValueError("Run state not found.")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("run_id") != run_id:
            raise ValueError("Run identity does not match its stored state.")
        return redact(state)

    def _check_integrity(self, state: dict) -> None:
        run_path = self._run_path(state["run_id"])
        manifest_path = run_path / "validation_manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ValueError("Validation evidence is missing. Generate and validate a new run.")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if _proposal_digest(state) != manifest.get("proposal_sha256"):
            raise ValueError("The stored proposal or validation changed. Generate and validate a new run.")
        if state.get("source_hashes") != self._source_hashes():
            raise ValueError("The source repository changed after validation. Generate and validate a new run.")
        expected_paths = set(ALLOWED_CHANGE_PATHS)
        if set(manifest.get("workspace_hashes", {})) != expected_paths:
            raise ValueError("Validation evidence has an invalid file scope.")
        workspace = run_path / "workspace"
        if workspace.is_symlink() or not workspace.is_dir():
            raise ValueError("The validated workspace is missing or unsafe.")
        for relative, expected in manifest["workspace_hashes"].items():
            file_path = workspace.joinpath(*PurePosixPath(relative).parts)
            if file_path.is_symlink() or not file_path.resolve().is_relative_to(workspace.resolve()) or not file_path.is_file() or _hash_file(file_path) != expected:
                raise ValueError("Validated files changed after testing. Generate and validate a new run.")
        if self._source_hashes(workspace) != manifest.get("workspace_source_hashes"):
            raise ValueError("Validated workspace inputs changed after testing. Generate and validate a new run.")

    def decide(self, run_id: str, decision: str, reviewer: str, comment: str = "") -> dict:
        if decision not in {"approved", "rejected", "revision_requested"}:
            raise ValueError("Choose an explicit supported review decision.")
        if not reviewer.strip() or len(reviewer) > 120 or len(comment) > 3000:
            raise ValueError("Enter a reviewer name (max 120 characters) and a bounded review comment.")
        state = self.load(run_id)
        if state["status"] != "awaiting_approval":
            raise ValueError("Only a validated run awaiting approval can receive a decision.")
        self._check_integrity(state)
        validation = ValidationReport.model_validate(state.get("validation"))
        if not validation.passed or not validation.checks or not all(c.passed for c in validation.checks):
            raise ValueError("All checks must pass before a review decision can be recorded.")
        state["status"] = decision
        state["decision"] = redact({"decision": decision, "reviewer": reviewer.strip(), "comment": comment.strip(), "at": _utc_now()})
        state["events"] = self._event(state, "human_review", f"Human decision recorded: {decision}.", decision)
        receipt = {"run_id": run_id, "proposal_sha256": _proposal_digest(state), "decision": state["decision"]}
        self._write_run_text(self._run_path(run_id), "decision_receipt.json", json.dumps(receipt, ensure_ascii=False, indent=2))
        self._save(state)
        return state

    def export_bundle(self, run_id: str) -> bytes:
        state = self.load(run_id)
        if state.get("status") != "approved" or state.get("decision", {}).get("decision") != "approved":
            raise ValueError("Approve the validated proposal before exporting a patch package.")
        self._check_integrity(state)
        receipt_path = self._run_path(run_id) / "decision_receipt.json"
        if receipt_path.is_symlink() or not receipt_path.is_file():
            raise ValueError("The recorded human decision is missing.")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt != {"run_id": run_id, "proposal_sha256": _proposal_digest(state), "decision": state["decision"]}:
            raise ValueError("The human decision does not match its recorded receipt.")
        buffer = io.BytesIO()
        run_path = self._run_path(run_id)
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("changes.patch", state["diff"])
            bundle.writestr("review.json", json.dumps(redact(state), ensure_ascii=False, indent=2))
            bundle.writestr("validation_manifest.json", (run_path / "validation_manifest.json").read_bytes())
            bundle.writestr("decision_receipt.json", receipt_path.read_bytes())
            bundle.writestr("audit.jsonl", (run_path / "audit.jsonl").read_bytes())
            for change in state["changes"]:
                bundle.writestr("proposed_files/" + change["path"], change["content"])
            bundle.writestr("README.txt", "Approved review package for a synthetic demonstration repository.\nNo merge or production release has been executed.\nReview and apply changes through your normal repository process.\n")
        return buffer.getvalue()
