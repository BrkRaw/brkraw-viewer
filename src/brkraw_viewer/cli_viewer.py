from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
from typing import List

from brkraw_viewer.app.bootstrap import run_app


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
    logger = logging.getLogger("brkraw.viewer")
    paths: List[str] = list(args.path or [])
    if len(paths) > 1:
        print("Error: too many paths provided for viewer launch.", flush=True)
        return 2
    path = paths[0] if paths else os.environ.get("BRKRAW_PATH")
    if not paths and path:
        logger.debug("Using BRKRAW_PATH for viewer launch: %s", path)
    scan_id = args.scan
    reco_id = args.reco
    if scan_id is None:
        env_scan = os.environ.get("BRKRAW_SCAN_ID")
        if env_scan:
            try:
                scan_id = int(env_scan)
                logger.debug("Using BRKRAW_SCAN_ID for viewer launch: %s", env_scan)
            except ValueError:
                print(f"Error: invalid BRKRAW_SCAN_ID: {env_scan}", flush=True)
                return 2
    if reco_id is None:
        env_reco = os.environ.get("BRKRAW_RECO_ID")
        if env_reco:
            try:
                reco_id = int(env_reco)
                logger.debug("Using BRKRAW_RECO_ID for viewer launch: %s", env_reco)
            except ValueError:
                print(f"Error: invalid BRKRAW_RECO_ID: {env_reco}", flush=True)
                return 2
    run_app(
        path=path,
        scan_id=scan_id,
        reco_id=reco_id,
        info_spec=args.info_spec,
    )
    return 0
