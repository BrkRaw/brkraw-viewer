from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

from brkraw.core import config as config_core
from brkraw.core import formatter

from brkraw_viewer.app.services import registry as registry_service
from brkraw_viewer.app.services.viewer_config import ensure_viewer_config, registry_columns, registry_path


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[name-defined]
    parser = subparsers.add_parser(
        "viewer-config",
        help="Manage BrkRaw viewer registry/config.",
    )
    parser.add_argument(
        "command",
        choices=("init", "register", "unregister", "list"),
        help="Viewer config command.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Dataset path(s) for register/unregister.",
    )
    parser.set_defaults(func=_run_command)


def _run_command(args: argparse.Namespace) -> int:
    command = args.command
    paths: List[str] = list(args.paths or [])

    if command == "init":
        ensure_viewer_config()
        reg_path = registry_path()
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        if not reg_path.exists():
            reg_path.write_text("", encoding="utf-8")
        print(f"Viewer registry initialized: {reg_path}")
        return 0

    if command == "register":
        if not paths:
            print("Error: missing path to register.")
            return 2
        added, skipped = registry_service.register_paths([Path(p) for p in paths])
        print(f"Registered {added} dataset(s), skipped {skipped}.")
        return 0

    if command == "unregister":
        if not paths:
            print("Error: missing path to unregister.")
            return 2
        removed = registry_service.unregister_paths([Path(p) for p in paths])
        print(f"Removed {removed} dataset(s).")
        return 0

    if command == "list":
        rows = registry_service.registry_status().get("entries", [])
        width = config_core.output_width(root=None)
        columns = [dict(col) for col in registry_columns()]
        if not any(col.get("key") == "missing" for col in columns):
            columns.append({"key": "missing", "title": "Missing", "width": 80})
        visible = [col for col in columns if not col.get("hidden")]
        keys = [col["key"] for col in visible]
        formatted_rows = []
        for entry in rows:
            row: dict[str, object] = {}
            for col in visible:
                key = col["key"]
                value = registry_service.resolve_entry_value(entry, key)
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
