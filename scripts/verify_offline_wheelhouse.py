from __future__ import annotations

import argparse
import email
import json
import sys
import zipfile
from pathlib import Path


REQUIRED_PACKAGES = {
    "claude-agent-sdk",
    "fastapi",
    "hatchling",
    "pydantic",
    "pydantic-settings",
    "pymongo",
    "python-docx",
    "uvicorn",
}


def normalize_name(name: str) -> str:
    return name.lower().replace("_", "-").replace(".", "-")


def inspect_wheel(path: Path) -> tuple[str, str, bool]:
    with zipfile.ZipFile(path) as archive:
        metadata_files = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_files) != 1:
            raise ValueError(f"{path.name}: missing unique wheel METADATA")
        metadata = email.message_from_bytes(archive.read(metadata_files[0]))
        name = normalize_name(str(metadata["Name"]))
        version = str(metadata["Version"])
        bundled_cli = any(
            member == "claude_agent_sdk/_bundled/claude"
            for member in archive.namelist()
        )
        return name, version, bundled_cli


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the Linux offline wheelhouse")
    parser.add_argument("wheelhouse", type=Path)
    parser.add_argument("--write-manifest", type=Path)
    args = parser.parse_args()

    try:
        wheelhouse = args.wheelhouse.resolve()
        wheels = sorted(wheelhouse.glob("*.whl"))
        if not wheels:
            raise ValueError(f"No wheels found in {wheelhouse}")

        packages: dict[str, str] = {}
        cli_found = False
        for wheel in wheels:
            name, version, bundled_cli = inspect_wheel(wheel)
            packages[name] = version
            if name == "claude-agent-sdk":
                if version != "0.2.107":
                    raise ValueError(
                        f"Expected claude-agent-sdk 0.2.107, found {version}"
                    )
                cli_found = bundled_cli

        missing = sorted(REQUIRED_PACKAGES - packages.keys())
        if missing:
            raise ValueError(f"Missing required wheels: {', '.join(missing)}")
        if not cli_found:
            raise ValueError(
                "claude-agent-sdk wheel does not contain the Linux Claude Code CLI"
            )

        manifest = {
            "platform": "linux-x86_64",
            "python": "3.12",
            "claude_agent_sdk": packages["claude-agent-sdk"],
            "bundled_claude_cli": True,
            "wheel_count": len(wheels),
            "packages": dict(sorted(packages.items())),
        }
        if args.write_manifest:
            args.write_manifest.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(manifest, ensure_ascii=False))
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"wheelhouse validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
