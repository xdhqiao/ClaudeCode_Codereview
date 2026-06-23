from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        enable_decoding=False,
    )

    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_database: str = "ai_code_review"

    anthropic_api_key: SecretStr | None = None
    anthropic_auth_token: SecretStr | None = None
    anthropic_base_url: str | None = None
    claude_model: str = "claude-sonnet-4-6"
    claude_effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    claude_max_turns: int = Field(default=12, ge=1, le=100)
    claude_max_budget_usd: float = Field(default=2.0, gt=0)
    claude_timeout_seconds: int = Field(default=600, ge=30)
    claude_retry_count: int = Field(default=2, ge=0, le=5)

    poll_interval_seconds: float = Field(default=5.0, ge=0.5)
    worker_concurrency: int = Field(default=2, ge=1, le=32)
    review_concurrency_per_task: int = Field(default=2, ge=1, le=16)
    task_lease_seconds: int = Field(default=1800, ge=60)
    task_max_attempts: int = Field(default=3, ge=1, le=20)
    task_max_budget_usd: float = Field(default=20.0, gt=0)
    max_files_per_task: int = Field(default=10_000, ge=1)
    max_agent_calls_per_task: int = Field(default=500, ge=1)

    workspace_root: Path = Path("workspaces")
    knowledge_root: Path = Path("knowledge/standards")
    allowed_local_repo_roots: list[Path] = Field(default_factory=list)
    allowed_repo_hosts: list[str] = Field(default_factory=list)
    git_timeout_seconds: int = Field(default=600, ge=30)
    max_file_bytes: int = Field(default=1_000_000, ge=1024)
    full_scan_chunk_lines: int = Field(default=800, ge=100)
    diff_context_lines: int = Field(default=8, ge=0, le=100)
    max_diff_bytes: int = Field(default=50_000_000, ge=1_000_000)
    max_prompt_diff_chars: int = Field(default=60_000, ge=2_000)
    max_standard_chars: int = Field(default=18_000, ge=1_000)
    max_standard_rules: int = Field(default=20, ge=1, le=200)
    max_issues_per_file: int = Field(default=100, ge=1, le=200)

    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8080, ge=1, le=65535)
    service_api_key: SecretStr | None = None
    log_level: str = "INFO"

    @field_validator(
        "anthropic_api_key",
        "anthropic_auth_token",
        "service_api_key",
        mode="before",
    )
    @classmethod
    def empty_secret_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("anthropic_base_url", mode="before")
    @classmethod
    def empty_url_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("allowed_local_repo_roots", mode="before")
    @classmethod
    def split_path_list(cls, value: object) -> object:
        if isinstance(value, str):
            items = cls._parse_list_value(value)
            return [Path(item) for item in items]
        return value

    @field_validator("allowed_repo_hosts", mode="before")
    @classmethod
    def split_string_list(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.lower() for item in cls._parse_list_value(value)]
        return value

    @staticmethod
    def _parse_list_value(value: str) -> list[str]:
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            decoded = json.loads(stripped)
            if not isinstance(decoded, list) or not all(
                isinstance(item, str) for item in decoded
            ):
                raise ValueError("Expected a JSON array of strings")
            return [item.strip() for item in decoded if item.strip()]
        return [item.strip() for item in stripped.split(",") if item.strip()]

    def claude_environment(self, config_dir: Path) -> dict[str, str]:
        env = {
            "CLAUDE_CONFIG_DIR": str(config_dir),
            "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "CLAUDE_AGENT_SDK_CLIENT_APP": "ai-code-review/0.1.0",
        }
        if self.anthropic_api_key:
            env["ANTHROPIC_API_KEY"] = self.anthropic_api_key.get_secret_value()
        if self.anthropic_auth_token:
            env["ANTHROPIC_AUTH_TOKEN"] = self.anthropic_auth_token.get_secret_value()
        if self.anthropic_base_url:
            env["ANTHROPIC_BASE_URL"] = self.anthropic_base_url.rstrip("/")
        return env
