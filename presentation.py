from datetime import datetime
from zoneinfo import ZoneInfo


def metric_caption(item: dict) -> str:
    parts = []
    for field, label in (("viewCount", "조회수"), ("likeCount", "좋아요")):
        value = item.get(field)
        if value is None:
            parts.append(f"{label} 미제공")
            continue
        checked = item.get(f"{field}CheckedAt")
        if isinstance(checked, datetime):
            checked = checked.astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M KST")
        suffix = f" · 확인 {checked}" if checked else " · 확인 시각 없음"
        parts.append(f"{label} {value:,}{suffix}")
    return " | ".join(parts)
