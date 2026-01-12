from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import List

from brkraw.core import config as config_core
from brkraw.core import formatter

from .apps.viewer import launch
from .registry import registry_status, register_paths, unregister_paths, resolve_entry_value
from .frames.viewer_config import ensure_viewer_config, registry_columns, registry_path


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[name-defined]
    parser = subparsers.add_parser(
        "viewer",
        help="Launch the BrkRaw scan viewer GUI.",
    )
    parser.add_argument(
        "path",
        nargs="*",
        help="Path to the Bruker study root directory.",
    )
    parser.add_argument("--scan", type=int, default=None, help="Initial scan id.")
    parser.add_argument("--reco", type=int, default=None, help="Initial reco id.")
    parser.add_argument(
        "--info-spec",
        default=None,
        help="Optional scan info spec YAML path (use instead of the default mapping).",
    )
    parser.set_defaults(func=_run_viewer)


def _run_viewer(args: argparse.Namespace) -> int:
    commands = {"init", "register", "unregister", "list"}
    paths: List[str] = list(args.path or [])
    if paths and paths[0] in commands:
        command = paths.pop(0)
        if command == "init":
            return _cmd_init()
        if command == "register":
            return _cmd_register(paths)
        if command == "unregister":
            return _cmd_unregister(paths)
        if command == "list":
            return _cmd_list()
        return 2
    if len(paths) > 1:
        print("Error: too many paths provided for viewer launch.", flush=True)
        return 2
    path = paths[0] if paths else None
    return launch(
        path=path,
        scan_id=args.scan,
        reco_id=args.reco,
        info_spec=args.info_spec,
    )


def _cmd_init() -> int:
    ensure_viewer_config()
    reg_path = registry_path()
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    if not reg_path.exists():
        reg_path.write_text("", encoding="utf-8")
    print(f"Viewer registry initialized: {reg_path}")
    return 0


def _cmd_register(paths: List[str]) -> int:
    if not paths:
        print("Error: missing path to register.")
        return 2
    targets = [Path(p) for p in paths]
    try:
        entries = register_paths(targets)
    except Exception as exc:
        print(f"Error: failed to register dataset(s): {exc}")
        return 2
    print(f"Registered {len(entries)} dataset(s).")
    return 0


def _cmd_unregister(paths: List[str]) -> int:
    if not paths:
        print("Error: missing path to unregister.")
        return 2
    targets = [Path(p) for p in paths]
    removed = unregister_paths(targets)
    print(f"Removed {removed} dataset(s).")
    return 0


def _cmd_list() -> int:
    logger = logging.getLogger("brkraw.viewer")
    rows = registry_status()
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
            value = resolve_entry_value(entry, key)
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
    logger.info("%s", table)
    return 0
