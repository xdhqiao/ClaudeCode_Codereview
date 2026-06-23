from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ai_code_review.domain.models import (
    AgentMetrics,
    FileReviewRecord,
    ReviewResult,
    ReviewTask,
    ReviewTaskCreate,
    TaskSummary,
)


class TaskRepository(Protocol):
    async def ensure_indexes(self) -> None: ...

    async def enqueue(self, request: ReviewTaskCreate) -> ReviewTask: ...

    async def get_task(self, task_id: str) -> ReviewTask | None: ...

    async def claim_next(
        self, worker_id: str, lease_seconds: int, max_attempts: int
    ) -> ReviewTask | None: ...

    async def renew_lease(self, task_id: str, worker_id: str, lease_seconds: int) -> bool: ...

    async def complete(self, task_id: str, worker_id: str, summary: TaskSummary) -> bool: ...

    async def fail(
        self, task: ReviewTask, worker_id: str, error: str, max_attempts: int
    ) -> bool: ...

    async def save_result(self, record: FileReviewRecord) -> bool: ...

    async def list_results(
        self, task_id: str, *, offset: int = 0, limit: int = 1000
    ) -> list[FileReviewRecord]: ...

    async def get_result(self, task_id: str, file_name: str) -> FileReviewRecord | None: ...


class ReviewAgent(Protocol):
    async def review(self, prompt: str, repository_path: Path) -> tuple[ReviewResult, AgentMetrics]:
        ...
