from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


__all__ = [
    "DatasetState",
    "ViewerState",
    "SettingsState",
    "AppState"
]

@dataclass
class DatasetState:
    path: Optional[Path] = None
    is_open: bool = False

    selected_scan_id: Optional[int] = None
    selected_reco_id: Optional[int] = None


@dataclass
class ViewerState:
    view: str = "axial"  # "axial" | "coronal" | "sagittal"
    slice_index: int = 0
    frame_index: int = 0
    x_index: int = 0
    y_index: int = 0
    z_index: int = 0
    show_crosshair: bool = True
    rgb_mode: bool = False
    zoom: float = 1.0
    flip_x: bool = False
    flip_y: bool = False
    flip_z: bool = False
    slicepack_index: int = 0
    space: str = "scanner"
    subject_type: Optional[str] = None
    subject_pose: Optional[str] = None
    extra_indices: list[int] = field(default_factory=list)
    hook_locked: bool = False


@dataclass
class SettingsState:
    worker_popup: bool = True


@dataclass
class AppState:
    dataset: DatasetState = field(default_factory=DatasetState)
    viewer: ViewerState = field(default_factory=ViewerState)
    settings: SettingsState = field(default_factory=SettingsState)
