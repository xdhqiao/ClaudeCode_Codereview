from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from ai_code_review.domain.models import (
    FileReviewRecord,
    ReviewTask,
    ReviewTaskCreate,
    TaskStatus,
    TaskSummary,
)


class MongoReviewRepository:
    def __init__(self, uri: str, database_name: str) -> None:
        self.client: MongoClient[dict[str, Any]] = MongoClient(uri, tz_aware=True)
        self.database: Database[dict[str, Any]] = self.client[database_name]
        self.tasks: Collection[dict[str, Any]] = self.database.review_tasks
        self.results: Collection[dict[str, Any]] = self.database.review_results

    async def ping(self) -> None:
        await asyncio.to_thread(self.client.admin.command, "ping")

    async def ensure_indexes(self) -> None:
        await asyncio.gather(
            asyncio.to_thread(
                self.tasks.create_index,
                [("status", ASCENDING), ("scheduled_at", ASCENDING), ("priority", DESCENDING)],
                name="task_claim",
            ),
            asyncio.to_thread(
                self.tasks.create_index,
                [("lease_until", ASCENDING)],
                name="task_lease",
            ),
            asyncio.to_thread(
                self.results.create_index,
                [("task_id", ASCENDING), ("file_name", ASCENDING)],
                unique=True,
                name="task_file_unique",
            ),
        )

    async def enqueue(self, request: ReviewTaskCreate) -> ReviewTask:
        task = ReviewTask(**request.model_dump())
        document = task.model_dump(by_alias=True, mode="python")
        await asyncio.to_thread(self.tasks.insert_one, document)
        return task

    async def get_task(self, task_id: str) -> ReviewTask | None:
        document = await asyncio.to_thread(self.tasks.find_one, {"_id": task_id})
        return ReviewTask.model_validate(document) if document else None

    async def claim_next(
        self, worker_id: str, lease_seconds: int, max_attempts: int
    ) -> ReviewTask | None:
        now = datetime.now(UTC)
        await asyncio.to_thread(
            self.tasks.update_many,
            {
                "status": TaskStatus.RUNNING.value,
                "lease_until": {"$lt": now},
                "attempts": {"$gte": max_attempts},
            },
            {
                "$set": {
                    "status": TaskStatus.FAILED.value,
                    "error": "Task lease expired after the maximum number of attempts",
                    "completed_at": now,
                    "updated_at": now,
                    "lease_owner": None,
                    "lease_until": None,
                }
            },
        )
        query = {
            "attempts": {"$lt": max_attempts},
            "$or": [
                {"status": TaskStatus.PENDING.value, "scheduled_at": {"$lte": now}},
                {"status": TaskStatus.RUNNING.value, "lease_until": {"$lt": now}},
            ]
        }
        update = {
            "$set": {
                "status": TaskStatus.RUNNING.value,
                "lease_owner": worker_id,
                "lease_until": now + timedelta(seconds=lease_seconds),
                "started_at": now,
                "updated_at": now,
                "error": None,
            },
            "$inc": {"attempts": 1},
        }
        document = await asyncio.to_thread(
            self.tasks.find_one_and_update,
            query,
            update,
            sort=[("priority", DESCENDING), ("scheduled_at", ASCENDING), ("created_at", ASCENDING)],
            return_document=ReturnDocument.AFTER,
        )
        return ReviewTask.model_validate(document) if document else None

    async def complete(self, task_id: str, worker_id: str, summary: TaskSummary) -> bool:
        now = datetime.now(UTC)
        result = await asyncio.to_thread(
            self.tasks.update_one,
            {
                "_id": task_id,
                "status": TaskStatus.RUNNING.value,
                "lease_owner": worker_id,
            },
            {
                "$set": {
                    "status": TaskStatus.COMPLETED.value,
                    "summary": summary.model_dump(mode="python"),
                    "completed_at": now,
                    "updated_at": now,
                    "lease_owner": None,
                    "lease_until": None,
                }
            },
        )
        return result.modified_count == 1

    async def renew_lease(self, task_id: str, worker_id: str, lease_seconds: int) -> bool:
        now = datetime.now(UTC)
        result = await asyncio.to_thread(
            self.tasks.update_one,
            {
                "_id": task_id,
                "status": TaskStatus.RUNNING.value,
                "lease_owner": worker_id,
            },
            {
                "$set": {
                    "lease_until": now + timedelta(seconds=lease_seconds),
                    "updated_at": now,
                }
            },
        )
        return result.modified_count == 1

    async def fail(
        self,
        task: ReviewTask,
        worker_id: str,
        error: str,
        max_attempts: int,
    ) -> bool:
        now = datetime.now(UTC)
        terminal = task.attempts >= max_attempts
        update: dict[str, Any] = {
            "status": TaskStatus.FAILED.value if terminal else TaskStatus.PENDING.value,
            "error": error[:8000],
            "updated_at": now,
            "lease_owner": None,
            "lease_until": None,
        }
        if terminal:
            update["completed_at"] = now
        else:
            update["scheduled_at"] = now + timedelta(seconds=min(30 * 2**task.attempts, 1800))
        result = await asyncio.to_thread(
            self.tasks.update_one,
            {
                "_id": task.id,
                "status": TaskStatus.RUNNING.value,
                "lease_owner": worker_id,
            },
            {"$set": update},
        )
        return result.modified_count == 1

    async def save_result(self, record: FileReviewRecord) -> bool:
        now = datetime.now(UTC)
        document = record.model_dump(by_alias=True, mode="python")
        record_id = document.pop("_id")
        created_at = document.pop("created_at")
        document["updated_at"] = now
        try:
            result = await asyncio.to_thread(
                self.results.update_one,
                {
                    "task_id": record.task_id,
                    "file_name": record.file_name,
                    "$or": [
                        {"attempt": {"$lte": record.attempt}},
                        {"attempt": {"$exists": False}},
                    ],
                },
                {
                    "$set": document,
                    "$setOnInsert": {
                        "_id": record_id,
                        "created_at": created_at,
                    },
                },
                upsert=True,
            )
        except DuplicateKeyError:
            return False
        return result.matched_count == 1 or result.upserted_id is not None

    async def list_results(
        self, task_id: str, *, offset: int = 0, limit: int = 1000
    ) -> list[FileReviewRecord]:
        def fetch() -> list[dict[str, Any]]:
            cursor = (
                self.results.find({"task_id": task_id})
                .sort("file_name", ASCENDING)
                .skip(offset)
                .limit(limit)
            )
            return list(cursor)

        documents = await asyncio.to_thread(fetch)
        return [FileReviewRecord.model_validate(document) for document in documents]

    async def get_result(self, task_id: str, file_name: str) -> FileReviewRecord | None:
        document = await asyncio.to_thread(
            self.results.find_one,
            {"task_id": task_id, "file_name": file_name},
        )
        return FileReviewRecord.model_validate(document) if document else None

    def close(self) -> None:
        self.client.close()
