import unittest
from pathlib import Path
from types import SimpleNamespace

from ai_code_review.diagnostics import build_config_report


class ConfigurationDiagnosticsTests(unittest.TestCase):
    def test_docker_rejects_loopback_model_gateway(self) -> None:
        settings = self._settings(
            anthropic_base_url="http://127.0.0.1:4000",
            allowed_local_repo_roots=[Path("/data/repositories")],
        )

        report = build_config_report(settings, deployment="docker")

        self.assertEqual(report["status"], "error")
        self.assertIn("container loopback", " ".join(report["errors"]))

    def test_report_masks_mongodb_password_and_auth_key(self) -> None:
        settings = self._settings(
            mongodb_uri="mongodb://reviewer:secret@mongo:27017/?authSource=admin",
            anthropic_base_url="http://llm.internal:4000",
            anthropic_api_key="top-secret",
        )

        report = build_config_report(settings, deployment="docker")
        rendered = str(report)

        self.assertEqual(report["status"], "ok")
        self.assertIn("reviewer:***", report["mongodb"]["uri"])
        self.assertNotIn("secret", rendered)
        self.assertNotIn("top-secret", rendered)

    def test_native_linux_warns_about_docker_hostname(self) -> None:
        settings = self._settings(
            anthropic_base_url="http://host.docker.internal:4000",
        )

        report = build_config_report(settings, deployment="native")

        self.assertIn("native Linux", " ".join(report["warnings"]))

    @staticmethod
    def _settings(**overrides: object) -> SimpleNamespace:
        values: dict[str, object] = {
            "anthropic_api_key": None,
            "anthropic_auth_token": None,
            "anthropic_base_url": None,
            "claude_model": "claude-sonnet-4-6",
            "claude_effort": "high",
            "claude_timeout_seconds": 600,
            "claude_max_turns": 12,
            "service_api_key": None,
            "allowed_local_repo_roots": [],
            "allowed_repo_hosts": [],
            "mongodb_uri": "mongodb://localhost:27017",
            "mongodb_database": "ai_code_review",
            "workspace_root": Path("workspaces"),
            "knowledge_root": Path("knowledge/standards"),
            "api_host": "0.0.0.0",
            "api_port": 8080,
        }
        values.update(overrides)
        return SimpleNamespace(**values)
