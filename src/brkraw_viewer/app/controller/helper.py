import datetime as dt
from typing import Iterable


def format_value(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def lookup_nested(info: dict, path: tuple[str, ...]) -> object:
    cur: object = info
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur.get(key)
    return cur


def flatten_keys(obj: object, prefix: str = "") -> list[str]:
    keys: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = str(k)
            path = f"{prefix}.{key}" if prefix else key
            keys.append(path)
            keys.extend(flatten_keys(v, path))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            keys.extend(flatten_keys(v, prefix))
    return keys


def filter_layout_keys(keys: Iterable[str]) -> list[str]:
    filtered: list[str] = []
    for key in keys:
        parts = key.split(".")
        if any(part.isdigit() for part in parts):
            continue
        filtered.append(key)
    return filtered


def format_study_date(value: object) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, dt.datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time.min).strftime("%Y-%m-%d %H:%M")
    text = str(value).strip()
    for fmt in (
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d",
        "%Y%m%d%H%M",
        "%Y%m%d%H%M%S",
        "%Y%m%d",
    ):
        try:
            parsed = dt.datetime.strptime(text, fmt)
            return parsed.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    try:
        parsed = dt.datetime.fromisoformat(text)
        return parsed.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return text


def crop_view(img, *, center: tuple[int, int], zoom: float):
    if zoom <= 1.0:
        return img
    h, w = img.shape[:2]
    if h <= 0 or w <= 0:
        return img
    window_h = max(2, int(round(h / zoom)))
    window_w = max(2, int(round(w / zoom)))
    window_h = min(window_h, h)
    window_w = min(window_w, w)
    center_row = int(max(0, min(h - 1, center[0])))
    center_col = int(max(0, min(w - 1, center[1])))
    r0 = center_row - window_h // 2
    c0 = center_col - window_w // 2
    r0 = max(0, min(h - window_h, r0))
    c0 = max(0, min(w - window_w, c0))
    return img[r0 : r0 + window_h, c0 : c0 + window_w]
