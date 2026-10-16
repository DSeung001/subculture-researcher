"""Load and persist per-source extract profiles from extractors/*.yaml."""

from pathlib import Path

import yaml

from subculture.collection.domain.extract_profile import ExtractProfileError, normalize_extract, slug_for_name

EXTRACTORS_DIR = Path(__file__).resolve().parents[1] / "extractors"


def _load_file(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ExtractProfileError(f"{path.name}: 루트는 객체여야 합니다.")
    name = (data.get("name") or "").strip()
    if not name:
        raise ExtractProfileError(f"{path.name}: name이 필요합니다.")
    extract = normalize_extract(data.get("extract")) if data.get("extract") is not None else None
    return {**data, "name": name, "extract": extract, "_extractor_path": str(path)}


def load_extractor_files(directory: Path | None = None) -> list[dict]:
    root = directory if directory is not None else EXTRACTORS_DIR
    if not root.is_dir():
        return []
    items = []
    for path in sorted(root.glob("*.yaml")):
        items.append(_load_file(path))
    for path in sorted(root.glob("*.yml")):
        items.append(_load_file(path))
    return items


def merge_sources_with_extractors(
    sources: list[dict],
    extractors: list[dict] | None = None,
) -> list[dict]:
    """Overlay extract maps onto matching source names; append new extractor-only sources."""
    overlays = extractors if extractors is not None else load_extractor_files()
    by_name = {item["name"]: item for item in overlays}
    merged = []
    seen = set()
    for source in sources:
        name = source.get("name")
        copy = dict(source)
        overlay = by_name.get(name)
        if overlay is not None:
            if overlay.get("extract") is not None:
                copy["extract"] = overlay["extract"]
            # Extractor-only keys that extend a yaml source stay out of the base file.
            for key in ("shop",):
                if key in overlay and key not in copy:
                    copy[key] = overlay[key]
            copy["_extractor_path"] = overlay.get("_extractor_path")
        merged.append(copy)
        if name:
            seen.add(name)
    for overlay in overlays:
        name = overlay["name"]
        if name in seen:
            continue
        # Standalone source definition living only under extractors/.
        entry = {k: v for k, v in overlay.items() if not str(k).startswith("_")}
        entry.setdefault("type", "html")
        entry.setdefault("enabled", False)
        entry.setdefault("respect_robots", True)
        entry["_extractor_path"] = overlay.get("_extractor_path")
        entry["_from_extractor"] = True
        if "url" not in entry:
            raise ExtractProfileError(f"새 소스 '{name}'에 url이 필요합니다.")
        merged.append(entry)
    return merged


def extractor_path_for(name: str, directory: Path | None = None) -> Path:
    root = directory if directory is not None else EXTRACTORS_DIR
    return root / f"{slug_for_name(name)}.yaml"


def _compact_extract(extract: dict | None) -> dict | None:
    """Drop null attr / false many flags so saved YAML stays short."""
    if extract is None:
        return None

    def compact_fields(fields: dict) -> dict:
        out = {}
        for name, spec in fields.items():
            entry = {"selector": spec["selector"], "parse": spec.get("parse") or "text"}
            if spec.get("attr"):
                entry["attr"] = spec["attr"]
            if spec.get("many"):
                entry["many"] = True
            out[name] = entry
        return out

    result = {
        "list": {
            "item": extract["list"]["item"],
            "fields": compact_fields(extract["list"]["fields"]),
        },
    }
    detail = extract.get("detail")
    if detail and detail.get("fields"):
        result["detail"] = {"fields": compact_fields(detail["fields"])}
    return result


def save_extractor(
    data: dict,
    *,
    directory: Path | None = None,
    path: Path | None = None,
) -> Path:
    """Write an extractor YAML (name + extract, plus full source fields when new)."""
    name = (data.get("name") or "").strip()
    if not name:
        raise ExtractProfileError("name이 필요합니다.")
    extract = _compact_extract(normalize_extract(data.get("extract")))
    payload = {k: v for k, v in data.items() if not str(k).startswith("_") and k != "extract"}
    payload["name"] = name
    if extract is not None:
        payload["extract"] = extract
    root = directory if directory is not None else EXTRACTORS_DIR
    root.mkdir(parents=True, exist_ok=True)
    target = path if path is not None else extractor_path_for(name, root)
    # Prefer a stable dump without YAML anchors; keep unicode readable.
    target.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    return target


def supports_visual_extract(source: dict) -> bool:
    """Whether the local picker UI can configure this source."""
    return source.get("type") == "html"
