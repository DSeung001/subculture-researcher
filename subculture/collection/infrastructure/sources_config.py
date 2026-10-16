"""Single place to load sources.yaml, shared by collect.py and app.py."""

from pathlib import Path

import yaml

from subculture.collection.infrastructure.extractors_config import merge_sources_with_extractors

CONFIG_PATH = Path(__file__).resolve().parents[1] / "sources.yaml"


def load_sources_yaml() -> list[dict]:
    """Sources from sources.yaml only (no extractors/ overlays)."""
    if not CONFIG_PATH.exists():
        raise SystemExit("sources.yaml 파일이 없습니다.")
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    return config.get("sources", [])


def load_sources() -> list[dict]:
    """sources.yaml plus extractors/*.yaml overlays and standalone sources."""
    return merge_sources_with_extractors(load_sources_yaml())


def is_manual_source(source: dict) -> bool:
    return bool(source.get("manual_only") or source.get("local_only"))


def automatic_sources(sources: list[dict] | None = None) -> list[dict]:
    items = sources if sources is not None else load_sources()
    return [source for source in items if not is_manual_source(source)]


def manual_sources(sources: list[dict] | None = None) -> list[dict]:
    items = sources if sources is not None else load_sources()
    return [source for source in items if is_manual_source(source)]
