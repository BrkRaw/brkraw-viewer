from __future__ import annotations

import argparse

from .app import launch


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[name-defined]
    parser = subparsers.add_parser(
        "viewer",
        help="Launch the BrkRaw scan viewer GUI.",
    )
    parser.add_argument(
        "path",
        nargs="?",
        help="Path to the Bruker study root directory.",
    )
    parser.add_argument("--scan", type=int, default=None, help="Initial scan id.")
    parser.add_argument("--reco", type=int, default=None, help="Initial reco id.")
    parser.add_argument(
        "--axis",
        default="axial",
        choices=("axial", "coronal", "sagittal"),
        help="Initial viewing axis.",
    )
    parser.add_argument("--slice", type=int, default=None, help="Initial slice index.")
    parser.set_defaults(func=_run_viewer)


def _run_viewer(args: argparse.Namespace) -> int:
    return launch(
        path=args.path,
        scan_id=args.scan,
        reco_id=args.reco,
        axis=args.axis,
        slice_index=args.slice,
    )
