from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    try:
        import claude_agent_sdk
        from claude_agent_sdk import ClaudeSDKClient
        from claude_agent_sdk._cli_version import __cli_version__
    except ImportError as exc:
        print(f"Claude Agent SDK import failed: {exc}", file=sys.stderr)
        return 1

    package_root = Path(claude_agent_sdk.__file__).resolve().parent
    cli = package_root / "_bundled" / "claude"
    if not cli.is_file():
        print(f"Bundled Claude Code CLI is missing: {cli}", file=sys.stderr)
        return 1

    try:
        result = subprocess.run(
            [str(cli), "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print("Bundled Claude Code CLI version check timed out", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Bundled Claude Code CLI could not start: {exc}", file=sys.stderr)
        return 1
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no output"
        print(
            f"Bundled Claude Code CLI failed: {detail}",
            file=sys.stderr,
        )
        return 1
    print(
        f"Claude Agent SDK ready; CLI expected={__cli_version__}, "
        f"actual={result.stdout.strip()}, client={ClaudeSDKClient.__name__}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
