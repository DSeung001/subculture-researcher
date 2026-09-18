from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def is_new_today(item: dict, *, now: datetime | None = None) -> bool:
    collected_at = item.get("collectedAt")
    if not isinstance(collected_at, datetime):
        return False
    now = now or datetime.now(timezone.utc)
    return collected_at.astimezone(KST).date() == now.astimezone(KST).date()


def parse_published_at(value) -> datetime | None:
    if not value:
        return None
    for parser in (parsedate_to_datetime, datetime.fromisoformat):
        try:
            parsed = parser(value)
        except (TypeError, ValueError):
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def effective_date(item: dict) -> datetime:
    published = parse_published_at(item.get("publishedAt"))
    if published:
        return published
    collected_at = item.get("collectedAt")
    if isinstance(collected_at, datetime):
        return collected_at
    return datetime.min.replace(tzinfo=timezone.utc)


def sort_items(items: list[dict], *, newest_first: bool = True) -> list[dict]:
    return sorted(items, key=effective_date, reverse=newest_first)


def format_date_kst(value: datetime) -> str:
    return value.astimezone(KST).strftime("%Y-%m-%d %H:%M")


def summary_preview(item: dict, length: int = 120) -> str:
    summary = (item.get("summary") or "").strip()
    if not summary:
        return "요약 없음"
    if len(summary) <= length:
        return summary
    return summary[:length].rstrip() + "…"


def metric_caption(item: dict) -> str:
    parts = []
    for field, label in (("viewCount", "조회수"), ("likeCount", "좋아요")):
        value = item.get(field)
        if value is None:
            parts.append(f"{label} 미제공")
            continue
        checked = item.get(f"{field}CheckedAt")
        if isinstance(checked, datetime):
            checked = checked.astimezone(KST).strftime("%Y-%m-%d %H:%M KST")
        suffix = f" · 확인 {checked}" if checked else " · 확인 시각 없음"
        parts.append(f"{label} {value:,}{suffix}")
    return " | ".join(parts)
