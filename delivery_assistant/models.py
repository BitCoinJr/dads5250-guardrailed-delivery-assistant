from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChangeRequest(StrictModel):
    request_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=6000)
    acceptance_criteria: str = Field(default="", max_length=3000)
    target_metric: str = Field(default="revenue", max_length=80)


class Ticket(StrictModel):
    request_id: str
    title: str
    summary: str
    metric: str
    excluded_statuses: list[Literal["canceled", "refunded", "pending", "completed"]]
    acceptance_criteria: list[str]
    clarification_questions: list[str]
    supported: bool


class Evidence(StrictModel):
    path: str
    content: str
    score: float
    reason: str


class ImpactPlan(StrictModel):
    summary: str
    affected_files: list[str]
    steps: list[str]
    risks: list[str]
    evidence_paths: list[str]


class FileChange(StrictModel):
    path: str
    content: str
    reason: str


class Proposal(StrictModel):
    plan: ImpactPlan
    changes: list[FileChange]


class CheckResult(StrictModel):
    name: str
    passed: bool
    details: str


class ValidationReport(StrictModel):
    passed: bool
    checks: list[CheckResult]
    baseline_total: float | None = None
    proposed_total: float | None = None
    expected_total: float | None = None
    executed_commands: list[str] = Field(default_factory=list)
