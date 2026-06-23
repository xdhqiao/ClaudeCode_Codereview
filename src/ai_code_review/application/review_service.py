from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from ai_code_review.application.aggregator import aggregate_metrics, aggregate_results
from ai_code_review.application.comment_counter import (
    comment_line_numbers,
    count_comment_lines,
)
from ai_code_review.application.diff_parser import (
    DiffHunk,
    FileDiff,
    batch_hunks,
    parse_unified_diff,
)
from ai_code_review.application.languages import detect_language
from ai_code_review.application.prompt_builder import build_diff_prompt, build_full_scan_prompt
from ai_code_review.config import Settings
from ai_code_review.domain.errors import NonRetryableReviewError
from ai_code_review.domain.interfaces import ReviewAgent, TaskRepository
from ai_code_review.domain.models import (
    AgentMetrics,
    FileReviewRecord,
    ReviewMode,
    ReviewResult,
    ReviewTask,
    TaskSummary,
)
from ai_code_review.infrastructure.git_repository import GitRepositoryManager, PreparedRepository
from ai_code_review.infrastructure.knowledge import KnowledgeBase


@dataclass(slots=True)
class BatchResult:
    review: ReviewResult
    metrics: AgentMetrics
    weight: int


@dataclass(slots=True)
class FileReviewOutcome:
    record: FileReviewRecord
    agent_calls: int


class TaskBudgetTracker:
    def __init__(
        self,
        *,
        agent: ReviewAgent,
        max_cost_usd: float,
        max_calls: int,
    ) -> None:
        self.agent = agent
        self.max_cost_usd = max_cost_usd
        self.max_calls = max_calls
        self.calls = 0
        self.spent_usd = 0.0
        self._lock = asyncio.Lock()

    async def review(
        self,
        prompt: str,
        repository_path: Path,
    ) -> tuple[ReviewResult, AgentMetrics]:
        async with self._lock:
            if self.calls >= self.max_calls:
                raise NonRetryableReviewError(
                    f"Task exceeded MAX_AGENT_CALLS_PER_TASK={self.max_calls}"
                )
            if self.spent_usd >= self.max_cost_usd:
                raise NonRetryableReviewError(
                    f"Task reached TASK_MAX_BUDGET_USD=${self.max_cost_usd:.4f}"
                )
            self.calls += 1

        review, metrics = await self.agent.review(prompt, repository_path)
        async with self._lock:
            self.spent_usd += metrics.total_cost_usd or 0.0
            if self.spent_usd > self.max_cost_usd:
                raise NonRetryableReviewError(
                    f"Task cost ${self.spent_usd:.4f} exceeded "
                    f"TASK_MAX_BUDGET_USD=${self.max_cost_usd:.4f}"
                )
        return review, metrics


class ReviewService:
    def __init__(
        self,
        *,
        settings: Settings,
        repository_manager: GitRepositoryManager,
        knowledge: KnowledgeBase,
        agent: ReviewAgent,
        storage: TaskRepository,
    ) -> None:
        self.settings = settings
        self.repository_manager = repository_manager
        self.knowledge = knowledge
        self.agent = agent
        self.storage = storage

    async def execute(self, task: ReviewTask) -> TaskSummary:
        prepared: PreparedRepository | None = None
        try:
            prepared = await self.repository_manager.prepare(task)
            if task.mode == ReviewMode.DIFF:
                return await self._review_diff(task, prepared)
            return await self._review_full(task, prepared)
        finally:
            self.repository_manager.cleanup(task.id)

    async def _review_diff(
        self, task: ReviewTask, repository: PreparedRepository
    ) -> TaskSummary:
        diff_text = await self.repository_manager.diff(
            repository, self.settings.diff_context_lines
        )
        file_diffs = parse_unified_diff(diff_text)
        supported = [
            item for item in file_diffs if not item.is_binary and detect_language(item.path)
        ]
        self._validate_file_count(len(supported))
        summary = TaskSummary(
            files_discovered=len(file_diffs),
            files_skipped=len(file_diffs) - len(supported),
        )
        budget = self._new_budget_tracker()
        agent_semaphore = asyncio.Semaphore(self.settings.review_concurrency_per_task)
        window_size = max(self.settings.review_concurrency_per_task * 2, 1)
        for offset in range(0, len(supported), window_size):
            window = supported[offset : offset + window_size]
            outcomes = await asyncio.gather(
                *(
                    self._review_diff_file_and_save(
                        task,
                        repository,
                        item,
                        agent_semaphore,
                        budget,
                    )
                    for item in window
                )
            )
            for outcome in outcomes:
                record = outcome.record
                summary.files_reviewed += 1
                summary.issues_found += len(record.review.issues)
                summary.agent_calls += outcome.agent_calls
                summary.total_cost_usd += record.metrics.total_cost_usd or 0.0
            self._validate_task_budget(summary)
        return summary

    async def _review_diff_file_and_save(
        self,
        task: ReviewTask,
        repository: PreparedRepository,
        file_diff: FileDiff,
        agent_semaphore: asyncio.Semaphore,
        budget: TaskBudgetTracker,
    ) -> FileReviewOutcome:
        outcome = await self._review_diff_file(
            task,
            repository,
            file_diff,
            agent_semaphore,
            budget,
        )
        saved = await self.storage.save_result(outcome.record)
        if not saved:
            raise RuntimeError("A newer task attempt already saved this file result")
        return outcome

    async def _review_diff_file(
        self,
        task: ReviewTask,
        repository: PreparedRepository,
        file_diff: FileDiff,
        agent_semaphore: asyncio.Semaphore,
        budget: TaskBudgetTracker,
    ) -> FileReviewOutcome:
        language = detect_language(file_diff.path)
        assert language
        batches = batch_hunks(file_diff, self.settings.max_prompt_diff_chars)
        added_line_numbers = {
            line.new_line
            for hunk in file_diff.hunks
            for line in hunk.lines
            if line.marker == "+" and line.new_line is not None
        }
        comment_count = self._count_added_comments(
            repository.path,
            file_diff,
            language,
            added_line_numbers,
        )

        async def run_batch(hunks: list[DiffHunk]) -> BatchResult:
            rendered = "\n".join(hunk.render() for hunk in hunks)
            standards = self.knowledge.search(
                language=language,
                profile=task.code_style_profile,
                query=f"{file_diff.path}\n{rendered}",
            )
            prompt = build_diff_prompt(
                file_name=file_diff.path,
                language=language,
                base_ref=task.base_ref or repository.base_commit or "",
                target_ref=task.target_ref,
                hunks=hunks,
                standards=standards,
            )
            async with agent_semaphore:
                review, metrics = await budget.review(prompt, repository.path)
            eligible = {line for hunk in hunks for line in hunk.eligible_line_numbers}
            review.issues = [
                issue
                for issue in review.issues
                if all(line_number in eligible for line_number in issue.issue_line_number)
            ]
            return BatchResult(
                review=review,
                metrics=metrics,
                weight=sum(hunk.changed_line_count for hunk in hunks),
            )

        batch_results: list[BatchResult] = []
        limit = self.settings.review_concurrency_per_task
        for offset in range(0, len(batches), limit):
            batch_results.extend(
                await asyncio.gather(
                    *(run_batch(batch) for batch in batches[offset : offset + limit])
                )
            )
        final_review = aggregate_results(
            [(item.review, item.weight) for item in batch_results],
            comment_line_number=comment_count,
            max_issues=self.settings.max_issues_per_file,
        )
        return FileReviewOutcome(
            record=FileReviewRecord(
                task_id=task.id,
                attempt=task.attempts,
                project_id=task.project_id,
                file_name=file_diff.path,
                language=language,
                base_commit=repository.base_commit,
                target_commit=repository.target_commit,
                review=final_review,
                metrics=aggregate_metrics(item.metrics for item in batch_results),
            ),
            agent_calls=len(batch_results),
        )

    async def _review_full(
        self, task: ReviewTask, repository: PreparedRepository
    ) -> TaskSummary:
        paths = self.repository_manager.list_source_files(
            repository.path,
            include_globs=task.include_globs,
            exclude_globs=task.exclude_globs,
        )
        self._validate_file_count(len(paths))
        summary = TaskSummary(files_discovered=len(paths))
        budget = self._new_budget_tracker()
        agent_semaphore = asyncio.Semaphore(self.settings.review_concurrency_per_task)
        window_size = max(self.settings.review_concurrency_per_task * 2, 1)
        for offset in range(0, len(paths), window_size):
            window = paths[offset : offset + window_size]
            outcomes = await asyncio.gather(
                *(
                    self._review_full_file_and_save(
                        task,
                        repository,
                        path,
                        agent_semaphore,
                        budget,
                    )
                    for path in window
                )
            )
            for outcome in outcomes:
                record = outcome.record
                summary.files_reviewed += 1
                summary.issues_found += len(record.review.issues)
                summary.agent_calls += outcome.agent_calls
                summary.total_cost_usd += record.metrics.total_cost_usd or 0.0
            self._validate_task_budget(summary)
        return summary

    async def _review_full_file_and_save(
        self,
        task: ReviewTask,
        repository: PreparedRepository,
        path: Path,
        agent_semaphore: asyncio.Semaphore,
        budget: TaskBudgetTracker,
    ) -> FileReviewOutcome:
        outcome = await self._review_full_file(
            task,
            repository,
            path,
            agent_semaphore,
            budget,
        )
        saved = await self.storage.save_result(outcome.record)
        if not saved:
            raise RuntimeError("A newer task attempt already saved this file result")
        return outcome

    async def _review_full_file(
        self,
        task: ReviewTask,
        repository: PreparedRepository,
        path: Path,
        agent_semaphore: asyncio.Semaphore,
        budget: TaskBudgetTracker,
    ) -> FileReviewOutcome:
        relative = path.relative_to(repository.path).as_posix()
        language = detect_language(path)
        assert language
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        comment_count = count_comment_lines(lines, language)
        chunk_size = self.settings.full_scan_chunk_lines
        ranges = [
            (start, min(start + chunk_size - 1, max(len(lines), 1)))
            for start in range(1, max(len(lines), 1) + 1, chunk_size)
        ]

        async def run_range(start: int, end: int) -> BatchResult:
            query_text = "\n".join(lines[start - 1 : end])
            standards = self.knowledge.search(
                language=language,
                profile=task.code_style_profile,
                query=f"{relative}\n{query_text}",
            )
            prompt = build_full_scan_prompt(
                file_name=relative,
                language=language,
                start_line=start,
                end_line=end,
                standards=standards,
            )
            async with agent_semaphore:
                review, metrics = await budget.review(prompt, repository.path)
            review.issues = [
                issue
                for issue in review.issues
                if all(start <= line_number <= end for line_number in issue.issue_line_number)
            ]
            return BatchResult(
                review=review,
                metrics=metrics,
                weight=max(end - start + 1, 1),
            )

        batch_results: list[BatchResult] = []
        limit = self.settings.review_concurrency_per_task
        for offset in range(0, len(ranges), limit):
            batch_results.extend(
                await asyncio.gather(
                    *(run_range(*line_range) for line_range in ranges[offset : offset + limit])
                )
            )
        final_review = aggregate_results(
            [(item.review, item.weight) for item in batch_results],
            comment_line_number=comment_count,
            max_issues=self.settings.max_issues_per_file,
        )
        return FileReviewOutcome(
            record=FileReviewRecord(
                task_id=task.id,
                attempt=task.attempts,
                project_id=task.project_id,
                file_name=relative,
                language=language,
                base_commit=repository.base_commit,
                target_commit=repository.target_commit,
                review=final_review,
                metrics=aggregate_metrics(item.metrics for item in batch_results),
            ),
            agent_calls=len(batch_results),
        )

    def _validate_file_count(self, file_count: int) -> None:
        if file_count > self.settings.max_files_per_task:
            raise NonRetryableReviewError(
                f"Task contains {file_count} supported files; "
                f"limit is {self.settings.max_files_per_task}"
            )

    def _new_budget_tracker(self) -> TaskBudgetTracker:
        return TaskBudgetTracker(
            agent=self.agent,
            max_cost_usd=self.settings.task_max_budget_usd,
            max_calls=self.settings.max_agent_calls_per_task,
        )

    def _validate_task_budget(self, summary: TaskSummary) -> None:
        if summary.total_cost_usd > self.settings.task_max_budget_usd:
            raise NonRetryableReviewError(
                f"Task cost ${summary.total_cost_usd:.4f} exceeded "
                f"TASK_MAX_BUDGET_USD=${self.settings.task_max_budget_usd:.4f}"
            )

    @staticmethod
    def _count_added_comments(
        repository_path: Path,
        file_diff: FileDiff,
        language: str,
        added_line_numbers: set[int],
    ) -> int:
        if not added_line_numbers or file_diff.is_deleted:
            return 0
        root = repository_path.resolve()
        target = root / file_diff.new_path
        try:
            resolved = target.resolve(strict=True)
        except OSError:
            return 0
        if resolved != root and not resolved.is_relative_to(root):
            return 0
        if not resolved.is_file():
            return 0
        lines = resolved.read_text(encoding="utf-8", errors="replace").splitlines()
        comment_lines = comment_line_numbers(lines, language)
        return len(added_line_numbers & comment_lines)
