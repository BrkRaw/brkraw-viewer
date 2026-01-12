from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Mapping
import json
import logging
import zipfile
import datetime as dt

from brkraw.apps.loader import BrukerLoader
from brkraw.core.fs import DatasetFS
from brkraw.dataclasses.study import Study

from .frames.viewer_config import registry_path

logger = logging.getLogger("brkraw.viewer")


@dataclass(frozen=True)
class RegistryEntry:
    path: str
    basename: str
    study: Dict[str, Any]
    num_scans: int
    kind: str
    added_at: str
    last_seen: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "basename": self.basename,
            "study": _json_safe(self.study),
            "num_scans": self.num_scans,
            "kind": self.kind,
            "added_at": self.added_at,
            "last_seen": self.last_seen,
        }


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def normalize_path(path: Path) -> str:
    path = path.expanduser()
    try:
        return str(path.resolve())
    except FileNotFoundError:
        return str(path)


def _ensure_registry_path(root: Optional[Path] = None) -> Path:
    reg_path = registry_path(root)
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    if not reg_path.exists():
        reg_path.write_text("", encoding="utf-8")
    return reg_path


def load_registry(root: Optional[Path] = None) -> List[Dict[str, Any]]:
    reg_path = registry_path(root)
    if not reg_path.exists():
        return []
    entries: List[Dict[str, Any]] = []
    for line in reg_path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Skipping invalid registry line: %s", text)
            continue
        if isinstance(payload, dict):
            entries.append(payload)
    return entries


def write_registry(entries: Iterable[Dict[str, Any]], root: Optional[Path] = None) -> None:
    reg_path = _ensure_registry_path(root)
    lines = [json.dumps(_json_safe(entry), ensure_ascii=True) for entry in entries]
    reg_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _discover_study_paths(path: Path) -> List[Path]:
    fs = DatasetFS.from_path(path)
    studies = Study.discover(fs)
    if not studies:
        return []
    if len(studies) == 1:
        study = studies[0]
        return [fs.root / study.relroot if study.relroot else fs.root]
    if fs._mode == "dir":
        return [fs.root / study.relroot if study.relroot else fs.root for study in studies]
    raise ValueError("Multiple studies found in archive; extract or point to a single study.")


def _discover_dataset_paths(path: Path) -> List[Path]:
    logger.info("Scanning for datasets under %s", path)
    if _is_archive(path):
        logger.debug("Found archive dataset: %s", path)
        return [path]
    if path.is_dir():
        direct = _discover_study_paths(path)
        if direct:
            logger.info("Found study dataset: %s", path)
            return direct
        discovered: List[Path] = []
        for child in sorted(path.iterdir()):
            if child.name.startswith("."):
                continue
            if _is_archive(child):
                logger.debug("Found archive dataset: %s", child)
                discovered.append(child)
                continue
            if child.is_dir():
                try:
                    studies = _discover_study_paths(child)
                except ValueError as exc:
                    logger.warning("Skipping %s: %s", child, exc)
                    continue
                if studies:
                    for study in studies:
                        logger.info("Found study dataset: %s", study)
                discovered.extend(studies)
        logger.info("Discovery complete: %d dataset(s) under %s", len(discovered), path)
        return discovered
    return []


def _is_archive(path: Path) -> bool:
    return path.is_file() and zipfile.is_zipfile(path)


def _load_study_info(loader: BrukerLoader) -> Dict[str, Any]:
    info: Dict[str, Any] = {}
    try:
        subject = loader.subject
        if isinstance(subject, dict):
            study = subject.get("Study", {})
            if isinstance(study, dict):
                info = dict(study)
    except Exception:
        info = {}
    return info


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    return str(value)


def build_entry(path: Path) -> RegistryEntry:
    norm = normalize_path(path)
    basename = path.name
    kind = "archive" if _is_archive(path) else "study"
    loader = BrukerLoader(path)
    study_info = _load_study_info(loader)
    num_scans = len(loader.avail)
    timestamp = _now_iso()
    return RegistryEntry(
        path=norm,
        basename=basename,
        study=study_info,
        num_scans=num_scans,
        kind=kind,
        added_at=timestamp,
        last_seen=timestamp,
    )


def _merge_entries(
    existing: Dict[str, Dict[str, Any]],
    new_entries: Iterable[RegistryEntry],
) -> Tuple[Dict[str, Dict[str, Any]], int]:
    added = 0
    for entry in new_entries:
        current = existing.get(entry.path)
        if current is None:
            existing[entry.path] = entry.as_dict()
            added += 1
        else:
            updated = dict(current)
            updated.update(entry.as_dict())
            updated["added_at"] = current.get("added_at", entry.added_at)
            existing[entry.path] = updated
    return existing, added


def register_paths(paths: Iterable[Path], root: Optional[Path] = None) -> List[RegistryEntry]:
    entries: List[RegistryEntry] = []
    for raw in paths:
        expanded = raw.expanduser()
        if not expanded.exists():
            raise FileNotFoundError(expanded)
        logger.debug("Registering dataset path: %s", expanded)
        try:
            dataset_paths = _discover_dataset_paths(expanded)
        except ValueError as exc:
            raise exc
        if not dataset_paths:
            raise ValueError(f"No Paravision study found under {expanded}")
        for study_path in dataset_paths:
            logger.info("Building registry entry: %s", study_path)
            entries.append(build_entry(study_path))
    existing = {entry["path"]: entry for entry in load_registry(root)}
    merged, _ = _merge_entries(existing, entries)
    write_registry(merged.values(), root=root)
    return entries


def unregister_paths(paths: Iterable[Path], root: Optional[Path] = None) -> int:
    normalized = {normalize_path(path) for path in paths}
    entries = load_registry(root)
    kept = [entry for entry in entries if entry.get("path") not in normalized]
    removed = len(entries) - len(kept)
    write_registry(kept, root=root)
    return removed


def registry_status(root: Optional[Path] = None) -> List[Dict[str, Any]]:
    entries = load_registry(root)
    for entry in entries:
        path = entry.get("path", "")
        entry["missing"] = not Path(str(path)).exists()
    return entries


def resolve_entry_value(entry: Mapping[str, Any], key: str) -> str:
    if key == "basename":
        return str(entry.get("basename", ""))
    if key == "path":
        return str(entry.get("path", ""))
    if key == "num_scans":
        return str(entry.get("num_scans", ""))
    if key == "kind":
        return str(entry.get("kind", ""))
    if key == "missing":
        return "Yes" if entry.get("missing") else "No"
    if key.startswith("Study."):
        study = entry.get("study", {})
        if isinstance(study, dict):
            field = key.split(".", 1)[1]
            return str(study.get(field, ""))
    return str(entry.get(key, ""))
