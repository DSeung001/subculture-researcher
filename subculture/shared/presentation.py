import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

from subculture.shared.image_urls import clean_image_url, http_url

KST = ZoneInfo("Asia/Seoul")
CATEGORY_LABELS = {
    "ANIME": "애니",
    "CHARACTER": "캐릭터",
    "FIGURE": "피규어",
    "GOODS": "굿즈",
    "COLLECTION": "컬렉션",
    "FESTIVAL": "페스티벌",
    "UNKNOWN": "미분류",
}
STATUS_LABELS = {
    "NEW": "새 항목",
    "KEEP": "채택",
    "HOLD": "보류",
    "IGNORE": "무시",
}
ANGLE_LABELS = {
    "NEWS": "뉴스",
    "COMPARE": "비교",
    "SIZE": "크기",
    "PRICE": "가격",
    "QUESTION": "질문/고민",
    "GUIDE": "가이드",
    "COLLECTION": "컬렉션",
}
TIER_LABELS = {
    "OFFICIAL": "공식",
    "MEDIA": "미디어",
}
REGION_LABELS = {
    "JP": "일본",
    "KR": "국내",
    "US": "미국",
    "CN": "중국",
}
LANGUAGE_TAGS = {
    "en": "EN",
    "ja": "JA",
    "zh": "CH",
    "zh-cn": "CH",
    "zh-tw": "CH",
    "ko": "KO",
}
SALE_STATUS_LABELS = {
    "PREORDER": "예약중",
    "IN_STOCK": "판매중",
    "SOLD_OUT": "품절",
    "UNKNOWN": "상태 미확인",
}
# A document copied as JSON carries its timestamps as ISO strings.
DATETIME_FIELDS = ("collectedAt", "postedAt")
_LEADING_DATE = re.compile(
    r"^(?P<date>\d{4}[./-]\d{1,2}[./-]\d{1,2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?)\s+(?P<title>.+)$"
)
LIMITED_KEYWORDS = ("한정판", "한정수량", "한정 수량", "한정발매", "한정 발매", "限定")


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
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
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
        return collected_at if collected_at.tzinfo else collected_at.replace(tzinfo=timezone.utc)
    return datetime.min.replace(tzinfo=timezone.utc)


# Freshness is normalized to 0-100 and weighted; flat bonuses (below) add a little more
# on top, uncapped.
FRESHNESS_WEIGHT = 0.35


def _freshness_subscore(item: dict, now: datetime) -> float:
    published = effective_date(item)
    age_hours = max(0.0, (now - published).total_seconds() / 3600)
    return max(0.0, 100.0 - age_hours / 2.16)  # zero after 216h (9 days), same horizon as before


def _flat_bonuses(item: dict) -> list[tuple[str, float]]:
    """Small additive bonuses that don't suffer the cross-category data-availability bias:
    each is a plain yes/no signal, not "how much data happens to exist"."""
    bonuses = []
    if item.get("sourceTier") == "OFFICIAL":
        bonuses.append(("공식 소스", 6.0))
    if item.get("region") == "KR":
        bonuses.append(("국내", 4.0))
    if item.get("entityType") == "PRODUCT":
        # Preorders and limited runs are time-sensitive and sell out, so
        # they're worth surfacing over an always-available in-stock item.
        if item.get("saleStatus") == "PREORDER":
            bonuses.append(("예약 임박", 3.0))
        title_text = f"{item.get('title') or ''} {item.get('titleKo') or ''}"
        if any(keyword in title_text for keyword in LIMITED_KEYWORDS):
            bonuses.append(("한정판", 3.0))
    return bonuses


def score_components(item: dict, *, now: datetime | None = None) -> list[tuple[str, float]]:
    """(label, weighted points) for every non-zero contribution to `content_score`,
    in a fixed order; `content_score` and `score_breakdown` both derive from this."""
    now = now or datetime.now(timezone.utc)
    components = [
        ("신선도", _freshness_subscore(item, now) * FRESHNESS_WEIGHT),
        *_flat_bonuses(item),
    ]
    return [(label, round(points, 1)) for label, points in components if points > 0]


def content_score(item: dict, *, now: datetime | None = None) -> float:
    """Comparable editorial score for every source; no DB migration required."""
    return round(sum(points for _, points in score_components(item, now=now)), 1)


def score_breakdown(item: dict, *, now: datetime | None = None) -> list[tuple[str, float]]:
    """`score_components`, sorted by contribution, for showing "why" on a card."""
    return sorted(score_components(item, now=now), key=lambda pair: pair[1], reverse=True)


def signal_labels(item: dict) -> list[str]:
    labels = []
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


def price_text(item: dict) -> str:
    """The stored product price as text (`12,000원`, `30 USD`), empty when there is none."""
    price = item.get("price")
    if item.get("entityType") != "PRODUCT" or not isinstance(price, int):
        return ""
    currency = item.get("currency") or "KRW"
    return f"{price:,}원" if currency == "KRW" else f"{price:,} {currency}"


def product_caption(item: dict, *, today: str | None = None) -> str:
    if item.get("entityType") != "PRODUCT":
        return ""
    parts = []
    if item.get("shop"):
        parts.append(str(item["shop"]))
    status = item.get("saleStatus")
    if status:
        parts.append(SALE_STATUS_LABELS.get(status, str(status)))
    price = price_text(item)
    if price:
        parts.append(price)
    if item.get("preorderEndAt"):
        today = today or datetime.now(KST).date().isoformat()
        deadline = str(item["preorderEndAt"])
        # A stored PREORDER status can be stale; make an elapsed deadline visible.
        parts.append(f"예약마감 {deadline}" + (" (마감 지남)" if deadline[:10] < today else ""))
    if item.get("releaseWindowText"):
        parts.append(f"입고 {item['releaseWindowText']}")
    if item.get("manufacturer"):
        parts.append(str(item["manufacturer"]))
    if item.get("sizeText"):
        parts.append(str(item["sizeText"]))
    return " · ".join(parts)


def _with_datetimes(item: dict) -> dict:
    data = dict(item)
    for field in DATETIME_FIELDS:
        if isinstance(data.get(field), str):
            data[field] = parse_published_at(data[field]) or data[field]
    return data


def card_view(item: dict) -> dict:
    """Everything an item card shows, from one Firestore-shaped document.

    The inbox and the static site (site_builder) both render through this, so the
    two lists cannot drift apart.
    """
    data = _with_datetimes(item)
    category = data.get("category", "UNKNOWN")
    angle = data.get("contentAngle", "NEWS")
    status = data.get("status", "NEW")
    tier = data.get("sourceTier") or "MEDIA"
    posted_at = data.get("postedAt")

    original_title = data.get("title") or "(제목 없음)"
    title_ko = (data.get("titleKo") or "").strip()
    display_title = title_ko or original_title
    title_date, title_text = split_leading_date(display_title)
    original_date, original_text = split_leading_date(original_title)
    shows_original = bool(title_ko and title_ko != original_title)
    language = (data.get("sourceLanguage") or "").strip().lower()
    posted_label = (
        f"발행 {format_date_kst(posted_at)}"
        if isinstance(posted_at, datetime)
        else ("발행됨" if posted_at else "미발행")
    )
    meta = " · ".join(
        value for value in [
            data.get("source"),
            CATEGORY_LABELS.get(category, category),
            ANGLE_LABELS.get(angle, angle),
            TIER_LABELS.get(tier, tier),
            STATUS_LABELS.get(status, status),
            posted_label,
            date_caption(data),
        ] if value
    )
    return {
        "title_text": title_text,
        "title_date": title_date,
        "original_title": original_title if shows_original else "",
        "original_text": original_text,
        "original_date": original_date,
        "lang_tag": (
            LANGUAGE_TAGS.get(language, language.upper())
            if shows_original and language and language != "unknown" else ""
        ),
        "url": http_url(data.get("url")) or "",
        "image_url": http_url(data.get("imageUrl")) or "",
        "detail_image_urls": [
            # Same photo rule as collection, so galleries stored before a rule change
            # (e.g. unrendered `{$js-src}` placeholders) are not shown as broken images.
            url for url in (clean_image_url(value) for value in data.get("detailImageUrls") or []) if url
        ],
        "category_label": CATEGORY_LABELS.get(category, category),
        "is_new_today": is_new_today(data),
        "meta": meta,
        "summary": summary_preview(data),
        "product_caption": product_caption(data),
        "signal_score": content_score(data),
        "signal_labels": signal_labels(data),
        "score_breakdown": score_breakdown(data),
    }
