from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


IssueType = Literal["logic", "performance", "security", "readable", "code_style"]
Score = Annotated[int, Field(ge=0, le=100)]
LineNumber = Annotated[int, Field(ge=1)]
MAX_REVIEW_COMMENTS_LENGTH = 8000


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewIssue(StrictModel):
    description: str = Field(min_length=1, max_length=4000)
    type: IssueType
    severity: int = Field(ge=1, le=5)
    confidence_level: float = Field(ge=0.0, le=1.0)
    suggestion: str = Field(min_length=1, max_length=4000)
    issue_line_number: list[LineNumber] = Field(min_length=1, max_length=2)

    @field_validator("issue_line_number", mode="before")
    @classmethod
    def normalize_line_numbers(cls, value: object) -> list[int]:
        if value is None or value == "":
            raise ValueError("issue_line_number must contain at least one line number")
        if isinstance(value, int):
            return [value]
        if isinstance(value, str):
            return [int(part.strip()) for part in value.split(",") if part.strip()]
        if isinstance(value, (list, tuple, set)):
            return [int(item) for item in value]
        raise ValueError("issue_line_number must be an integer or a list of integers")


class ReviewResult(StrictModel):
    """The exact externally visible review payload required by the legacy service."""

    comments: str = Field(min_length=1, max_length=MAX_REVIEW_COMMENTS_LENGTH)
    logic_score: Score
    performance_score: Score
    security_score: Score
    readable_score: Score
    code_style_score: Score
    comment_line_number: int = Field(ge=0)
    issues: list[ReviewIssue] = Field(default_factory=list, max_length=200)


class ReviewMode(StrEnum):
    DIFF = "diff"
    FULL = "full"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ReviewTaskCreate(StrictModel):
    project_id: str = Field(min_length=1, max_length=200)
    repo_url: str | None = Field(default=None, min_length=1, max_length=4096)
    local_path: str | None = Field(default=None, min_length=1, max_length=4096)
    base_ref: str | None = Field(default=None, min_length=1, max_length=512)
    target_ref: str = Field(default="HEAD", min_length=1, max_length=512)
    mode: ReviewMode = ReviewMode.DIFF
    code_style_profile: str = Field(default="default", min_length=1, max_length=128)
    include_globs: list[str] = Field(default_factory=list, max_length=200)
    exclude_globs: list[str] = Field(default_factory=list, max_length=200)
    scheduled_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    priority: int = Field(default=0, ge=-100, le=100)

    @field_validator("scheduled_at")
    @classmethod
    def make_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_source_and_mode(self) -> ReviewTaskCreate:
        if bool(self.repo_url) == bool(self.local_path):
            raise ValueError("Exactly one of repo_url or local_path must be provided")
        if self.mode == ReviewMode.DIFF and not self.base_ref:
            raise ValueError("base_ref is required for diff review")
        return self


class ReviewTask(ReviewTaskCreate):
    id: str = Field(default_factory=lambda: str(uuid4()), alias="_id")
    status: TaskStatus = TaskStatus.PENDING
    attempts: int = 0
    lease_owner: str | None = None
    lease_until: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    summary: dict[str, object] | None = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class AgentMetrics(StrictModel):
    session_id: str | None = None
    duration_ms: int | None = None
    num_turns: int | None = None
    total_cost_usd: float | None = None
    usage: dict[str, object] | None = None
    model_usage: dict[str, object] | None = None


class FileReviewRecord(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()), alias="_id")
    task_id: str
    attempt: int = Field(ge=1)
    project_id: str
    file_name: str
    language: str
    base_commit: str | None
    target_commit: str
    review: ReviewResult
    metrics: AgentMetrics = Field(default_factory=AgentMetrics)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class TaskSummary(StrictModel):
    files_discovered: int = 0
    files_reviewed: int = 0
    files_skipped: int = 0
    issues_found: int = 0
    agent_calls: int = 0
    total_cost_usd: float = 0.0
