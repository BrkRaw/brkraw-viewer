from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from brkraw.core import config as config_core
from brkraw.core import formatter

from brkraw_viewer.app.services import registry as registry_service
from brkraw_viewer.app.services.viewer_config import ensure_viewer_config, registry_columns, registry_path


def _middle_ellipsis(text: object, max_len: int = 40) -> object:
    if not isinstance(text, str):
        return text
    if max_len < 5 or len(text) <= max_len:
        return text
    left = (max_len - 4) // 2
    right = max_len - 4 - left
    return f"{text[:left]}....{text[-right:]}"


def _normalize_output_path(output: Optional[str]) -> Optional[str]:
    if output is None:
        return None
    trimmed = output.strip()
    if not trimmed:
        return None
    path = Path(trimmed)
    if not path.suffix:
        path = path.with_suffix(".jsonl")
    return str(path)


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[name-defined]
    parser = subparsers.add_parser(
        "viewer-registry",
        help="Manage BrkRaw viewer registry/config.",
    )
    parser.add_argument(
        "command",
        choices=("init", "add", "rm", "scan", "list", "clear"),
        help="Viewer config command.",
    )
    parser.add_argument(
        "path",
        nargs="?",
        help="Dataset path for add/rm/scan.",
    )
    parser.add_argument(
        "-t",
        "--target",
        default=None,
        help="External registry JSONL path (use instead of viewer.registry.path from config).",
    )
    parser.set_defaults(func=_run_command)


def _run_command(args: argparse.Namespace) -> int:
    command = args.command
    path = args.path
    output = _normalize_output_path(args.target)

    if command == "init":
        ensure_viewer_config()
        reg_path = registry_path(registry_file=output)
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        if not reg_path.exists():
            reg_path.write_text("", encoding="utf-8")
        print(f"Viewer registry initialized: {reg_path}")
        return 0

    if command == "add":
        if not path:
            print("Error: missing path to add.")
            return 2
        added, skipped = registry_service.register_paths(
            [Path(path)],
            registry_file=output,
        )
        print(f"Registered {added} dataset(s), skipped {skipped}.")
        return 0

    if command == "rm":
        if not path:
            print("Error: missing path to remove.")
            return 2
        removed = registry_service.unregister_paths(
            [Path(path)],
            registry_file=output,
        )
        print(f"Removed {removed} dataset(s).")
        return 0

    if command == "scan":
        if not path:
            print("Error: missing path to scan.")
            return 2
        added, skipped = registry_service.scan_registry(
            [Path(path)],
            registry_file=output,
        )
        print(f"Added {added} dataset(s), skipped {skipped}.")
        return 0

    if command == "clear":
        registry_service.write_registry([], registry_file=output)
        print("Viewer registry cleared.")
        return 0

    if command == "list":
        rows = registry_service.registry_status(registry_file=output).get("entries", [])
        width = config_core.output_width(root=None)
        columns = [dict(col) for col in registry_columns()]
        if not any(col.get("key") == "missing" for col in columns):
            columns.append({"key": "missing", "title": "Missing", "width": 80})
        visible = [col for col in columns if not col.get("hidden") and col.get("key") != "path"]
        keys = [col["key"] for col in visible]
        formatted_rows = []
        for entry in rows:
            row: dict[str, object] = {}
            for col in visible:
                key = col["key"]
                value = registry_service.resolve_entry_value(entry, key)
                if key == "basename":
                    value = _middle_ellipsis(value, max_len=40)
                if key == "missing" and entry.get("missing"):
                    row[key] = {"value": value, "color": "red"}
                else:
                    row[key] = value
            formatted_rows.append(row)
        table = formatter.format_table(
            "Viewer Registry",
            tuple(keys),
            formatted_rows,
            width=width,
            title_color="cyan",
            col_widths=formatter.compute_column_widths(tuple(keys), formatted_rows),
        )
        print(table)
        return 0

    return 2
