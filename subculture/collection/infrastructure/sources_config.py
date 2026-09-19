"""Single place to load sources.yaml, shared by collect.py and app.py."""

from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[1] / "sources.yaml"


def load_sources() -> list[dict]:
    if not CONFIG_PATH.exists():
        raise SystemExit("sources.yaml 파일이 없습니다.")
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    return config.get("sources", [])


def is_manual_source(source: dict) -> bool:
    return bool(source.get("manual_only") or source.get("local_only"))


def automatic_sources(sources: list[dict] | None = None) -> list[dict]:
    items = sources if sources is not None else load_sources()
    return [source for source in items if not is_manual_source(source)]


def manual_sources(sources: list[dict] | None = None) -> list[dict]:
    items = sources if sources is not None else load_sources()
    return [source for source in items if is_manual_source(source)]
