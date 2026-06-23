from __future__ import annotations

import asyncio
import logging
import socket
from uuid import uuid4

from ai_code_review.application.review_service import ReviewService
from ai_code_review.config import Settings
from ai_code_review.domain.errors import NonRetryableReviewError
from ai_code_review.domain.interfaces import TaskRepository


logger = logging.getLogger(__name__)


class TaskLeaseLostError(RuntimeError):
    pass


class ReviewWorker:
    def __init__(
        self,
        *,
        settings: Settings,
        storage: TaskRepository,
        review_service: ReviewService,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.review_service = review_service
        self.stop_event = asyncio.Event()
        self.worker_prefix = f"{socket.gethostname()}-{uuid4().hex[:8]}"

    async def run_forever(self) -> None:
        workers = [
            asyncio.create_task(self._run_slot(index), name=f"review-worker-{index}")
            for index in range(self.settings.worker_concurrency)
        ]
        try:
            await self.stop_event.wait()
        finally:
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

    async def _run_slot(self, index: int) -> None:
        worker_id = f"{self.worker_prefix}-{index}"
        while not self.stop_event.is_set():
            try:
                task = await self.storage.claim_next(
                    worker_id,
                    self.settings.task_lease_seconds,
                    self.settings.task_max_attempts,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Unable to claim a review task")
                await self._wait_for_next_poll()
                continue
            if task is None:
                await self._wait_for_next_poll()
                continue
            try:
                logger.info("Review task started", extra={"task_id": task.id})
                review_task = asyncio.create_task(
                    self.review_service.execute(task),
                    name=f"review-task-{task.id}",
                )
                heartbeat = asyncio.create_task(
                    self._heartbeat(task.id, worker_id),
                    name=f"lease-heartbeat-{task.id}",
                )
                try:
                    done, _ = await asyncio.wait(
                        {review_task, heartbeat},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if heartbeat in done:
                        await heartbeat
                        raise TaskLeaseLostError("Task lease heartbeat stopped unexpectedly")
                    summary = await review_task
                    completed = await self.storage.complete(task.id, worker_id, summary)
                    if not completed:
                        raise TaskLeaseLostError("Task lease was lost before completion")
                finally:
                    if not review_task.done():
                        review_task.cancel()
                    await asyncio.gather(review_task, return_exceptions=True)
                    heartbeat.cancel()
                    await asyncio.gather(heartbeat, return_exceptions=True)
                logger.info("Review task completed", extra={"task_id": task.id})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Review task failed", extra={"task_id": task.id})
                try:
                    updated = await self.storage.fail(
                        task,
                        worker_id,
                        str(exc),
                        task.attempts
                        if isinstance(exc, NonRetryableReviewError)
                        else self.settings.task_max_attempts,
                    )
                    if not updated:
                        logger.warning(
                            "Task failure was not recorded because the lease is no longer owned",
                            extra={"task_id": task.id},
                        )
                except Exception:
                    logger.exception(
                        "Unable to persist task failure",
                        extra={"task_id": task.id},
                    )

    async def _heartbeat(self, task_id: str, worker_id: str) -> None:
        interval = max(self.settings.task_lease_seconds // 3, 20)
        while True:
            await asyncio.sleep(interval)
            renewed = await self.storage.renew_lease(
                task_id, worker_id, self.settings.task_lease_seconds
            )
            if not renewed:
                raise TaskLeaseLostError(f"Task lease could not be renewed: {task_id}")

    def stop(self) -> None:
        self.stop_event.set()

    async def _wait_for_next_poll(self) -> None:
        try:
            await asyncio.wait_for(
                self.stop_event.wait(),
                timeout=self.settings.poll_interval_seconds,
            )
        except TimeoutError:
            pass
