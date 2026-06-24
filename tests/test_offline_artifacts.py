import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.offline_artifacts import extract_archive, pack_directory, verify_manifest
from scripts.verify_offline_wheelhouse import inspect_wheel as inspect_linux_wheel
from scripts.wheelhouse_manifest import inspect_wheel


class OfflineArtifactTests(unittest.TestCase):
    def test_pack_split_verify_and_restore(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "package.whl").write_bytes(b"a" * 512)
            (source / "metadata.json").write_text("{}", encoding="utf-8")

            manifest = pack_directory(
                source,
                root / "bundles" / "wheels.zip",
                max_part_size=128,
                remove_source=True,
            )
            verify_manifest(manifest)
            restored = extract_archive(manifest, root / "restored")

            self.assertFalse(source.exists())
            self.assertEqual((restored / "package.whl").read_bytes(), b"a" * 512)
            self.assertEqual((restored / "metadata.json").read_text(), "{}")

    def test_failed_restore_preserves_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "restored"
            destination.mkdir()
            sentinel = destination / "existing.whl"
            sentinel.write_bytes(b"keep")

            with self.assertRaises(OSError):
                extract_archive(root / "missing.parts.json", destination)

            self.assertEqual(sentinel.read_bytes(), b"keep")

    def test_wheel_manifest_detects_bundled_claude_cli(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / "claude_agent_sdk-0.2.107-py3-none-test.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr(
                    "claude_agent_sdk-0.2.107.dist-info/METADATA",
                    "Metadata-Version: 2.1\n"
                    "Name: claude-agent-sdk\n"
                    "Version: 0.2.107\n"
                    "License: MIT\n",
                )
                archive.writestr(
                    "claude_agent_sdk/_bundled/claude",
                    b"binary",
                )

            metadata = inspect_wheel(wheel)

            self.assertEqual(metadata["name"], "claude-agent-sdk")
            self.assertEqual(metadata["version"], "0.2.107")
            self.assertEqual(
                metadata["bundled_cli"],
                ["claude_agent_sdk/_bundled/claude"],
            )

    def test_linux_wheel_validation_rejects_windows_wheel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / "demo-1.0-py3-none-win_amd64.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr(
                    "demo-1.0.dist-info/METADATA",
                    "Metadata-Version: 2.1\nName: demo\nVersion: 1.0\n",
                )

            with self.assertRaisesRegex(ValueError, "unsupported platform"):
                inspect_linux_wheel(wheel)

    def test_linux_wheel_manifest_includes_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / "demo-1.0-py3-none-any.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr(
                    "demo-1.0.dist-info/METADATA",
                    "Metadata-Version: 2.1\nName: demo\nVersion: 1.0\n",
                )

            metadata = inspect_linux_wheel(wheel)

            self.assertEqual(metadata["name"], "demo")
            self.assertEqual(len(metadata["sha256"]), 64)
