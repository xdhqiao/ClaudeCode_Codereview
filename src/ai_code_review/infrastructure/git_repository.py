from __future__ import annotations

import asyncio
import fnmatch
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from ai_code_review.application.languages import DEFAULT_IGNORED_PARTS, is_supported_source
from ai_code_review.config import Settings
from ai_code_review.domain.errors import NonRetryableReviewError
from ai_code_review.domain.models import ReviewTask


@dataclass(slots=True)
class PreparedRepository:
    path: Path
    base_commit: str | None
    target_commit: str


class GitCommandError(RuntimeError):
    pass


class GitOutputLimitError(NonRetryableReviewError):
    pass


class GitRepositoryManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def _run(
        self,
        *args: str,
        cwd: Path | None = None,
        max_stdout_bytes: int = 4_000_000,
    ) -> str:
        environment = os.environ.copy()
        environment["GIT_TERMINAL_PROMPT"] = "0"
        environment["GCM_INTERACTIVE"] = "Never"
        process = await asyncio.create_subprocess_exec(
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "submodule.recurse=false",
            "-c",
            "core.quotePath=false",
            *args,
            cwd=str(cwd) if cwd else None,
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_task = asyncio.create_task(
            self._read_limited(process.stdout, max_stdout_bytes)
        )
        stderr_task = asyncio.create_task(
            self._read_limited(process.stderr, 4_000_000)
        )
        wait_task = asyncio.create_task(process.wait())
        try:
            _, stdout, stderr = await asyncio.wait_for(
                asyncio.gather(wait_task, stdout_task, stderr_task),
                timeout=self.settings.git_timeout_seconds,
            )
        except TimeoutError:
            await self._terminate(process)
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            raise GitCommandError(f"git command timed out: git {' '.join(args)}") from None
        except GitOutputLimitError:
            await self._terminate(process)
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            raise
        except Exception:
            await self._terminate(process)
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            raise
        if process.returncode != 0:
            message = stderr.decode("utf-8", errors="replace").strip()
            raise GitCommandError(f"git {' '.join(args)} failed: {message}")
        return stdout.decode("utf-8", errors="replace").strip()

    @staticmethod
    async def _read_limited(
        stream: asyncio.StreamReader | None,
        limit: int,
    ) -> bytes:
        if stream is None:
            return b""
        data = bytearray()
        while chunk := await stream.read(64 * 1024):
            data.extend(chunk)
            if len(data) > limit:
                raise GitOutputLimitError(
                    f"Git output exceeded the configured {limit}-byte limit"
                )
        return bytes(data)

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process) -> None:
        if process.returncode is None:
            process.kill()
        await process.wait()

    def _task_directory(self, task_id: str) -> Path:
        try:
            UUID(task_id)
        except ValueError as exc:
            raise NonRetryableReviewError("Task ID must be a UUID") from exc
        workspace = self.settings.workspace_root.expanduser().resolve()
        task_dir = (workspace / task_id).resolve()
        if task_dir.parent != workspace:
            raise NonRetryableReviewError(
                "Task workspace resolved outside WORKSPACE_ROOT"
            )
        return task_dir

    def _validate_local_path(self, local_path: str) -> Path:
        source = Path(local_path).expanduser().resolve()
        if not source.is_dir():
            raise NonRetryableReviewError(
                f"Local repository does not exist: {source}"
            )
        allowed = [
            path.expanduser().resolve()
            for path in self.settings.allowed_local_repo_roots
        ]
        if not allowed:
            raise NonRetryableReviewError(
                "Local repositories are disabled; configure ALLOWED_LOCAL_REPO_ROOTS"
            )
        if not any(source == root or source.is_relative_to(root) for root in allowed):
            raise NonRetryableReviewError(
                "Local repository is outside ALLOWED_LOCAL_REPO_ROOTS"
            )
        return source

    def _validate_remote_url(self, repo_url: str) -> None:
        if re.match(r"^[^@\s]+@[^:\s]+:.+$", repo_url):
            host = repo_url.split("@", 1)[1].split(":", 1)[0].lower()
        else:
            parsed = urlparse(repo_url)
            if parsed.scheme not in {"https", "ssh"}:
                raise NonRetryableReviewError(
                    "Only https:// and ssh:// repository URLs are allowed"
                )
            host = (parsed.hostname or "").lower()
            if parsed.username or parsed.password:
                raise NonRetryableReviewError(
                    "Do not embed credentials in repo_url; use a Git credential helper"
                )
        if not host:
            raise NonRetryableReviewError("Repository URL must include a host")
        allowed_hosts = self.settings.allowed_repo_hosts
        if not allowed_hosts:
            raise NonRetryableReviewError(
                "Remote repositories are disabled; configure ALLOWED_REPO_HOSTS"
            )
        if "*" not in allowed_hosts and host not in allowed_hosts:
            raise NonRetryableReviewError(f"Repository host is not allowed: {host}")

    async def _resolve_commit(self, repository: Path, ref: str) -> str:
        if not ref.strip() or any(character in ref for character in "\r\n\0"):
            raise NonRetryableReviewError(
                "Git ref is empty or contains invalid characters"
            )
        candidates = [ref]
        if not ref.startswith("refs/") and ref != "HEAD":
            candidates.extend(
                [
                    f"refs/remotes/origin/{ref}",
                    f"refs/heads/{ref}",
                    f"refs/tags/{ref}",
                ]
            )
        last_error: GitCommandError | None = None
        for candidate in dict.fromkeys(candidates):
            try:
                return await self._run(
                    "rev-parse",
                    "--verify",
                    "--end-of-options",
                    f"{candidate}^{{commit}}",
                    cwd=repository,
                )
            except GitCommandError as exc:
                last_error = exc
        raise NonRetryableReviewError(f"Unable to resolve Git ref: {ref}") from last_error

    async def prepare(self, task: ReviewTask) -> PreparedRepository:
        task_dir = self._task_directory(task.id)
        repo_dir = task_dir / "repo"
        if task_dir.exists():
            shutil.rmtree(task_dir)
        task_dir.mkdir(parents=True, exist_ok=True)

        if task.local_path:
            source = self._validate_local_path(task.local_path)
            await self._run(
                "clone",
                "--no-hardlinks",
                "--no-checkout",
                "--",
                str(source),
                str(repo_dir),
            )
        else:
            assert task.repo_url
            self._validate_remote_url(task.repo_url)
            await self._run("clone", "--no-checkout", "--", task.repo_url, str(repo_dir))

        target_commit = await self._resolve_commit(repo_dir, task.target_ref)
        await self._run("checkout", "--detach", target_commit, cwd=repo_dir)
        base_commit = None
        if task.base_ref:
            base_commit = await self._resolve_commit(repo_dir, task.base_ref)
        return PreparedRepository(repo_dir, base_commit, target_commit)

    async def diff(self, repository: PreparedRepository, context_lines: int) -> str:
        if not repository.base_commit:
            raise NonRetryableReviewError(
                "base_commit is required for diff review"
            )
        return await self._run(
            "diff",
            "--no-color",
            "--no-ext-diff",
            "--no-textconv",
            "--find-renames",
            f"--unified={context_lines}",
            f"{repository.base_commit}...{repository.target_commit}",
            "--",
            cwd=repository.path,
            max_stdout_bytes=self.settings.max_diff_bytes,
        )

    def list_source_files(
        self,
        root: Path,
        *,
        include_globs: list[str],
        exclude_globs: list[str],
    ) -> list[Path]:
        files: list[Path] = []
        for current_root, dir_names, file_names in os.walk(root):
            dir_names[:] = [
                name
                for name in dir_names
                if name not in DEFAULT_IGNORED_PARTS and not name.startswith(".cache")
            ]
            current = Path(current_root)
            for name in file_names:
                path = current / name
                relative = path.relative_to(root).as_posix()
                if path.is_symlink():
                    continue
                try:
                    resolved = path.resolve(strict=True)
                except OSError:
                    continue
                if not resolved.is_relative_to(root.resolve()):
                    continue
                if not is_supported_source(path):
                    continue
                if include_globs and not any(
                    fnmatch.fnmatch(relative, item) for item in include_globs
                ):
                    continue
                if any(fnmatch.fnmatch(relative, item) for item in exclude_globs):
                    continue
                try:
                    if path.stat().st_size > self.settings.max_file_bytes:
                        continue
                except OSError:
                    continue
                files.append(path)
        return sorted(files)

    def cleanup(self, task_id: str) -> None:
        task_dir = self._task_directory(task_id)
        shutil.rmtree(task_dir, ignore_errors=True)
