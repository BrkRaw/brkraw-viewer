#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
import re

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"


def get_version() -> str:
    text = PYPROJECT_PATH.read_text(encoding="utf-8")
    data = tomllib.loads(text)
    version = data.get("project", {}).get("version")
    if not version:
        raise SystemExit("Failed to detect version in pyproject.toml")
    if not re.search(r"[0-9A-Za-z]", str(version)):
        raise SystemExit("Invalid version in pyproject.toml")
    return str(version)


def run_git(args: list[str]) -> None:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        msg = result.stderr.strip() or result.stdout.strip()
        raise SystemExit(f"git {' '.join(args)} failed: {msg}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Tag and push the current version.")
    parser.add_argument("--remote", default="origin", help="Remote to push tag to.")
    args = parser.parse_args()

    version = get_version()
    run_git(["tag", version])
    run_git(["push", args.remote, version])
    print(f"Pushed tag {version} to {args.remote}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
