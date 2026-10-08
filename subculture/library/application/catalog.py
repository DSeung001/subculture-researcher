"""The work/IP dictionary in work_catalog.yaml: canonical names and their matching keywords."""

from pathlib import Path

import yaml

CATALOG = Path(__file__).resolve().parents[1] / "work_catalog.yaml"


def load_catalog(path=CATALOG):
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    works = data.get("works") or []
    if not isinstance(works, list):
        raise ValueError("work_catalog.yaml의 works는 목록이어야 합니다.")
    for entry in works:
        aliases = entry.get("aliases") or []
        for alias in [aliases] if isinstance(aliases, str) else aliases:
            # An unquoted "Name: value" alias parses as a mapping and would be stored as "{'Name': 'value'}".
            if isinstance(alias, (dict, list)):
                raise ValueError(f"{entry.get('name')}의 별칭 {alias!r}: 콜론이 든 별칭은 따옴표로 감싸주세요.")
    return works
