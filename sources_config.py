"""Single place to load sources.yaml, shared by collect.py and app.py."""

from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).with_name("sources.yaml")


def load_sources() -> list[dict]:
    if not CONFIG_PATH.exists():
        raise SystemExit("sources.yaml 파일이 없습니다.")
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    return config.get("sources", [])


def community_source_names() -> set[str]:
    """Names of every source configured with source_tier: COMMUNITY.

    Used to filter out legacy Firestore documents collected before the
    sourceTier field existed (they have no sourceTier value to match on).
    """
    return {
        source["name"] for source in load_sources()
        if source.get("source_tier") == "COMMUNITY"
    }
