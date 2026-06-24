from __future__ import annotations

import argparse
import email
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from typing import Any


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
EXPECTED_SDK_VERSION = "0.2.107"
UNSUPPORTED_PLATFORM_MARKERS = (
    "win32",
    "win_amd64",
    "macosx",
    "musllinux",
    "aarch64",
    "arm64",
    "i686",
    "ppc64",
    "s390x",
)


def normalize_name(name: str) -> str:
    return name.lower().replace("_", "-").replace(".", "-")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate_linux_wheel_filename(path: Path) -> None:
    filename = path.name.lower()
    marker = next(
        (item for item in UNSUPPORTED_PLATFORM_MARKERS if item in filename),
        None,
    )
    if marker:
        raise ValueError(
            f"{path.name}: unsupported platform marker '{marker}' "
            "for Linux x86_64/glibc"
        )
    if not (filename.endswith("-any.whl") or "manylinux" in filename):
        raise ValueError(
            f"{path.name}: wheel is not portable or tagged for manylinux x86_64"
        )


def inspect_wheel(path: Path) -> dict[str, Any]:
    validate_linux_wheel_filename(path)
    with zipfile.ZipFile(path) as archive:
        metadata_files = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_files) != 1:
            raise ValueError(f"{path.name}: missing unique wheel METADATA")
        metadata = email.message_from_bytes(archive.read(metadata_files[0]))
        raw_name = metadata.get("Name")
        version = metadata.get("Version")
        if not raw_name or not version:
            raise ValueError(f"{path.name}: METADATA is missing Name or Version")
        name = normalize_name(raw_name)
        bundled_cli = any(
            member == "claude_agent_sdk/_bundled/claude"
            for member in archive.namelist()
        )
        return {
            "file": path.name,
            "name": name,
            "version": version,
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
            "bundled_cli": bundled_cli,
        }


def validate_wheelhouse(wheelhouse: Path) -> dict[str, Any]:
    wheelhouse = wheelhouse.resolve()
    wheels = sorted(wheelhouse.glob("*.whl"))
    if not wheels:
        raise ValueError(f"No wheels found in {wheelhouse}")

    packages: dict[str, str] = {}
    wheel_records: list[dict[str, Any]] = []
    cli_found = False
    for wheel in wheels:
        record = inspect_wheel(wheel)
        name = str(record["name"])
        version = str(record["version"])
        if name in packages:
            raise ValueError(
                f"Duplicate wheel for {name}: versions {packages[name]} and {version}"
            )
        packages[name] = version
        wheel_records.append(record)
        if name == "claude-agent-sdk":
            if version != EXPECTED_SDK_VERSION:
                raise ValueError(
                    f"Expected claude-agent-sdk {EXPECTED_SDK_VERSION}, found {version}"
                )
            cli_found = bool(record["bundled_cli"])

    missing = sorted(REQUIRED_PACKAGES - packages.keys())
    if missing:
        raise ValueError(f"Missing required wheels: {', '.join(missing)}")
    if not cli_found:
        raise ValueError(
            "claude-agent-sdk wheel does not contain the Linux Claude Code CLI"
        )

    return {
        "platform": "linux-x86_64",
        "python": "3.12",
        "claude_agent_sdk": packages["claude-agent-sdk"],
        "bundled_claude_cli": True,
        "wheel_count": len(wheels),
        "packages": dict(sorted(packages.items())),
        "wheels": wheel_records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the Linux offline wheelhouse")
    parser.add_argument("wheelhouse", type=Path)
    parser.add_argument("--write-manifest", type=Path)
    args = parser.parse_args()

    try:
        manifest = validate_wheelhouse(args.wheelhouse)
        if args.write_manifest:
            args.write_manifest.parent.mkdir(parents=True, exist_ok=True)
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
