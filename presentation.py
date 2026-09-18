import math
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


def content_score(item: dict, *, now: datetime | None = None) -> float:
    """Comparable editorial score for every source; no DB migration required."""
    now = now or datetime.now(timezone.utc)
    published = effective_date(item)
    age_hours = max(0.0, (now - published).total_seconds() / 3600)
    recency = max(0.0, 36.0 - age_hours / 6.0)

    score = recency
    if item.get("sourceTier") == "OFFICIAL":
        score += 8.0

    for field, weight in (("viewCount", 3.0), ("likeCount", 4.0)):
        value = item.get(field)
        if isinstance(value, int) and value > 0:
            score += min(18.0, math.log10(value + 1) * weight)

    trending = item.get("trending")
    if isinstance(trending, int) and trending > 0:
        score += min(30.0, math.log10(trending + 1) * 8.0)

    popularity = item.get("popularity")
    if isinstance(popularity, int) and popularity > 0:
        score += min(18.0, math.log10(popularity + 1) * 3.0)

    favourites = item.get("favourites")
    if isinstance(favourites, int) and favourites > 0:
        score += min(10.0, math.log10(favourites + 1) * 2.0)

    average_score = item.get("averageScore")
    if isinstance(average_score, int):
        score += max(0.0, min(10.0, average_score / 10.0))

    return round(score, 1)


def signal_labels(item: dict) -> list[str]:
    labels = []
    score = content_score(item)
    if score >= 60:
        labels.append("HOT")
    if item.get("trending"):
        labels.append("TREND")
    if item.get("sourceTier") == "OFFICIAL":
        labels.append("OFFICIAL")
    if is_new_today(item):
        labels.append("NEW")
    return labels


def sort_items(
    items: list[dict], *, newest_first: bool = True, recommended: bool = False
) -> list[dict]:
    if recommended:
        return sorted(
            items,
            key=lambda item: (content_score(item), effective_date(item)),
            reverse=True,
        )
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
        return ""
    if len(summary) <= length:
        return summary
    return summary[:length].rstrip() + "…"


def metric_caption(item: dict) -> str:
    parts = []
    for field, label in (
        ("trending", "AniList 트렌딩"),
        ("popularity", "인기도"),
        ("favourites", "즐겨찾기"),
        ("averageScore", "평균점수"),
    ):
        value = item.get(field)
        if value is not None:
            parts.append(
                f"{label} {value:,}" if isinstance(value, int)
                else f"{label} {value}"
            )
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
