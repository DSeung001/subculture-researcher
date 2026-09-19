"""Products and articles saved by hand instead of by a collector."""

from urllib.parse import urlsplit

from subculture.collection.domain.content_rules import normalize_url
from subculture.collection.infrastructure.content_store import ContentStore
from subculture.shared.image_urls import http_url


# Shops whose product URLs are saved by hand as products: (host, path prefix, source label, shop).
# The Naver brand store is here because its robots.txt forbids automatic collection.
MANUAL_SHOPS = (
    ("laftel.net", "", "Laftel Store", "Laftel"),
    ("brand.naver.com", "/kotobukiyamall", "Kotobukiya Mall (Naver)", "코토부키야 몰(네이버)"),
)


def manual_shop(url: str) -> tuple[str, str] | None:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    for suffix, prefix, source, shop in MANUAL_SHOPS:
        if (host == suffix or host.endswith("." + suffix)) and parsed.path.startswith(prefix):
            return source, shop
    return None


def add_manual_content(
    db, url: str, title: str, category: str, angle: str, source_tier: str = "MEDIA",
    image_url: str = "",
) -> bool:
    # Refresh the legacy index on submission, not on every page render.
    normalized = normalize_url(url)
    image_url = (image_url or "").strip()
    if image_url and not http_url(image_url):
        raise ValueError("이미지 URL은 http:// 또는 https:// 주소여야 합니다.")
    shop = manual_shop(normalized) if category == "FIGURE" else None
    result = ContentStore(db).save({
        "url": normalized, "title": title.strip() or "(제목 없음)", "summary": "",
        "source": shop[0] if shop else "수동 입력",
        "sourceType": "manual_product" if shop else "manual",
        "category": category,
        "contentAngle": angle, "sourceTier": source_tier,
        "entityType": "PRODUCT" if shop else None,
        "shop": shop[1] if shop else None,
        "saleStatus": "UNKNOWN" if shop else None,
        "imageUrl": image_url or None,
        "note": "", "postedAt": None, "publishedAt": None,
    })
    return bool(result["inserted"])
