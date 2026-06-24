from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Restore a repository offline bundle")
    parser.add_argument(
        "--platform",
        choices=["linux-x86_64-py312", "windows-x86_64-py312"],
        required=True,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parent.parent
    manifest = root / "vendor" / "bundles" / f"{args.platform}-wheels.zip.parts.json"
    destination_name = (
        "linux-x86_64"
        if args.platform == "linux-x86_64-py312"
        else "windows-x86_64"
    )
    destination = root / "vendor" / "wheels" / destination_name
    command = [
        sys.executable,
        str(root / "scripts" / "offline_artifacts.py"),
        "restore",
        "--manifest",
        str(manifest),
        "--destination",
        str(destination),
        "--extract",
    ]
    return subprocess.call(command, cwd=root)


if __name__ == "__main__":
    raise SystemExit(main())
