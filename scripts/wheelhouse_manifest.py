from __future__ import annotations

import argparse
import email
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_wheel(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        metadata_names = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_names) != 1:
            raise ValueError(f"Wheel has no unique METADATA file: {path.name}")
        metadata = email.message_from_bytes(archive.read(metadata_names[0]))
        license_files = metadata.get_all("License-File", [])
        bundled_cli = [
            name
            for name in archive.namelist()
            if name.endswith("/claude_agent_sdk/_bundled/claude")
            or name.endswith("/claude_agent_sdk/_bundled/claude.exe")
            or name.startswith("claude_agent_sdk/_bundled/claude")
        ]
        return {
            "file": path.name,
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
            "name": metadata.get("Name"),
            "version": metadata.get("Version"),
            "license": metadata.get("License"),
            "license_files": license_files,
            "bundled_cli": bundled_cli,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an offline wheelhouse manifest")
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-claude-cli", action="store_true")
    args = parser.parse_args()

    try:
        wheels = sorted(args.wheelhouse.glob("*.whl"))
        if not wheels:
            raise ValueError(f"No wheels found in {args.wheelhouse}")
        packages = [inspect_wheel(path) for path in wheels]
        if args.require_claude_cli:
            sdk = [
                package
                for package in packages
                if str(package["name"]).lower() == "claude-agent-sdk"
            ]
            if len(sdk) != 1 or not sdk[0]["bundled_cli"]:
                raise ValueError(
                    "claude-agent-sdk wheel does not contain a bundled Claude Code CLI"
                )
        manifest = {
            "format_version": 1,
            "python": "3.12",
            "packages": packages,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"wheelhouse manifest error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
