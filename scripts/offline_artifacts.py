from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any


BUFFER_SIZE = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(BUFFER_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def pack_directory(
    source: Path,
    output: Path,
    *,
    max_part_size: int,
    remove_source: bool,
) -> Path:
    source = source.resolve()
    output = output.resolve()
    if not source.is_dir():
        raise ValueError(f"Source directory does not exist: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    files = sorted(path for path in source.rglob("*") if path.is_file())
    if not files:
        raise ValueError(f"Source directory is empty: {source}")

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in files:
            archive.write(path, path.relative_to(source).as_posix())

    archive_size = output.stat().st_size
    archive_hash = sha256_file(output)
    parts: list[dict[str, Any]] = []
    with output.open("rb") as source_handle:
        index = 1
        while chunk := source_handle.read(max_part_size):
            part_name = f"{output.name}.part{index:03d}"
            part_path = output.parent / part_name
            part_path.write_bytes(chunk)
            parts.append(
                {
                    "name": part_name,
                    "size": len(chunk),
                    "sha256": sha256_file(part_path),
                }
            )
            index += 1

    manifest = {
        "format_version": 1,
        "archive_name": output.name,
        "archive_size": archive_size,
        "archive_sha256": archive_hash,
        "source_name": source.name,
        "parts": parts,
    }
    manifest_path = output.with_name(f"{output.name}.parts.json")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    output.unlink()
    if remove_source:
        shutil.rmtree(source)
    return manifest_path


def load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format_version") != 1 or not isinstance(data.get("parts"), list):
        raise ValueError(f"Unsupported artifact manifest: {path}")
    return data


def restore_archive(manifest_path: Path, output_directory: Path) -> Path:
    manifest_path = manifest_path.resolve()
    manifest = load_manifest(manifest_path)
    output_directory = output_directory.resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    archive_path = output_directory / str(manifest["archive_name"])

    with archive_path.open("wb") as destination:
        for part in manifest["parts"]:
            part_path = manifest_path.parent / str(part["name"])
            verify_part(part_path, part)
            with part_path.open("rb") as source:
                shutil.copyfileobj(source, destination, length=BUFFER_SIZE)

    if archive_path.stat().st_size != int(manifest["archive_size"]):
        archive_path.unlink(missing_ok=True)
        raise ValueError(f"Restored archive size mismatch: {archive_path}")
    if sha256_file(archive_path) != manifest["archive_sha256"]:
        archive_path.unlink(missing_ok=True)
        raise ValueError(f"Restored archive checksum mismatch: {archive_path}")
    return archive_path


def extract_archive(manifest_path: Path, destination: Path) -> Path:
    destination = destination.resolve()
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    archive_path = restore_archive(manifest_path, destination.parent / ".archives")
    with zipfile.ZipFile(archive_path) as archive:
        root = destination.resolve()
        for member in archive.infolist():
            candidate = (root / member.filename).resolve()
            if candidate != root and not candidate.is_relative_to(root):
                raise ValueError(f"Unsafe archive member: {member.filename}")
        archive.extractall(destination)
    return destination


def verify_part(path: Path, metadata: dict[str, Any]) -> None:
    if not path.is_file():
        raise ValueError(f"Artifact part is missing: {path}")
    if path.stat().st_size != int(metadata["size"]):
        raise ValueError(f"Artifact part size mismatch: {path}")
    if sha256_file(path) != metadata["sha256"]:
        raise ValueError(f"Artifact part checksum mismatch: {path}")


def verify_manifest(manifest_path: Path) -> None:
    manifest_path = manifest_path.resolve()
    manifest = load_manifest(manifest_path)
    for part in manifest["parts"]:
        verify_part(manifest_path.parent / str(part["name"]), part)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pack and restore offline artifacts")
    commands = parser.add_subparsers(dest="command", required=True)

    pack = commands.add_parser("pack")
    pack.add_argument("--source", type=Path, required=True)
    pack.add_argument("--output", type=Path, required=True)
    pack.add_argument("--max-part-size-mb", type=int, default=90)
    pack.add_argument("--remove-source", action="store_true")

    restore = commands.add_parser("restore")
    restore.add_argument("--manifest", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)
    restore.add_argument("--extract", action="store_true")

    verify = commands.add_parser("verify")
    verify.add_argument("--manifest", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "pack":
            manifest = pack_directory(
                args.source,
                args.output,
                max_part_size=args.max_part_size_mb * 1024 * 1024,
                remove_source=args.remove_source,
            )
            print(manifest)
        elif args.command == "restore":
            if args.extract:
                print(extract_archive(args.manifest, args.destination))
            else:
                print(restore_archive(args.manifest, args.destination))
        else:
            verify_manifest(args.manifest)
            print(f"verified: {args.manifest}")
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"offline artifact error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
