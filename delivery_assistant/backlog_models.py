from typing import Literal
from pydantic import Field

from .models import ChangeRequest, StrictModel


class BacklogItem(ChangeRequest):
    category: str = Field(default="BI report change", max_length=80)
    requester_team: str = Field(default="", max_length=120)
    requested_on: str = Field(default="", max_length=10)
    business_impact: int | None = Field(default=None, ge=1, le=5)
    desired_by: str = Field(default="", max_length=10)
    priority: Literal["A", "B", "C", "Unassigned"] = "Unassigned"
    effort: Literal["S", "M", "L", "Unknown"] = "Unknown"
    ba_status: Literal["New", "Discussing", "Ready", "On hold", "Delivered"] = "New"
    ba_notes: str = Field(default="", max_length=4000)
    ba_decision: Literal["Pending", "Go", "Hold", "Clarify"] = "Pending"
    planned_start: str = Field(default="", max_length=10)
    planned_finish: str = Field(default="", max_length=10)
    actual_start: str = Field(default="", max_length=10)
    actual_finish: str = Field(default="", max_length=10)
    delivery_reference: str = Field(default="", max_length=500)

    def to_change_request(self) -> ChangeRequest:
        return ChangeRequest.model_validate({key: getattr(self,key) for key in ChangeRequest.model_fields})


class TriageRecommendation(StrictModel):
    request_id: str
    rank: int
    suggested_action: Literal["Go", "Hold", "Clarify", "Scope review"]
    rationale: str
    concerns: list[str]
    estimated_impact: Literal["High", "Low", "Unknown"]
    estimated_change_volume: Literal["Small", "Large", "Unknown"]
    impact_rationale: str
    change_rationale: str
    confidence: Literal["High", "Medium", "Low"]
    evidence_paths: list[str]
    affected_files: list[str]


class TriageOutput(StrictModel):
    summary: str
    recommendations: list[TriageRecommendation]


BACKLOG_HEADERS = [
    "Request ID", "Category", "Request", "Business requirement", "Impact (1-5)",
    "Priority", "Desired by", "Requesting team", "Requested on", "BA status",
    "BA notes", "Acceptance criteria", "Effort", "Target metric", "BA decision",
    "Planned start", "Planned finish", "Actual start", "Actual finish", "Delivery reference",
]

BACKLOG_FIELDS = [
    "request_id", "category", "title", "description", "business_impact",
    "priority", "desired_by", "requester_team", "requested_on", "ba_status",
    "ba_notes", "acceptance_criteria", "effort", "target_metric", "ba_decision",
    "planned_start", "planned_finish", "actual_start", "actual_finish", "delivery_reference",
]
