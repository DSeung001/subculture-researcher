import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
_LEADING_DATE = re.compile(
    r"^(?P<date>\d{4}[./-]\d{1,2}[./-]\d{1,2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?)\s+(?P<title>.+)$"
)


def split_leading_date(text: str) -> tuple[str, str]:
    """Split a leading YYYY.MM.DD-style date from a title, if present."""
    match = _LEADING_DATE.match((text or "").strip())
    if not match:
        return "", text or ""
    return match.group("date"), match.group("title")


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


def date_caption(item: dict) -> str:
    """Label the shown timestamp as original publish date and/or collection time."""
    parts = []
    published_raw = item.get("publishedAt")
    published = parse_published_at(published_raw)
    if published:
        if isinstance(published_raw, str) and len(published_raw.strip()) <= 10:
            parts.append(f"게시 {published.date().isoformat()}")
        else:
            parts.append(f"게시 {format_date_kst(published)}")
    collected = item.get("collectedAt")
    if isinstance(collected, datetime):
        parts.append(f"수집 {format_date_kst(collected)}")
    return " · ".join(parts)


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
