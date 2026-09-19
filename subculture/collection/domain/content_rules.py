"""URL identity and the stored-field vocabulary of collected content (no I/O)."""

import hashlib
from urllib.parse import unquote_plus, urljoin, urlsplit, urlunsplit

from subculture.collection.domain.url_identity import canonicalize


TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_source_platform", "utm_creative_format", "utm_marketing_tactic",
    "fbclid", "gclid", "dclid", "msclkid",
}
METRICS = ("viewCount", "likeCount")
SIGNAL_FIELDS = (
    "trending", "popularity", "favourites", "averageScore",
    "nextAiringAt", "episode", "signalCheckedAt",
)
# Also carries imageUrl/detailCheckedAt: these refresh on re-collection of an existing document.
PRODUCT_FIELDS = (
    "entityType", "shop", "saleStatus", "preorderEndAt", "releaseWindowText",
    "manufacturer", "sizeText", "price", "currency", "imageUrl", "productCheckedAt",
    "detailCheckedAt",
)
# Fields read into the per-run URL index so collectors can skip detail pages they need not refetch.
INDEX_FIELDS = ("url", "status", "imageUrl", "price", "productCheckedAt", "detailCheckedAt")
DEFAULT_DETAIL_REFRESH_HOURS = 72.0


def normalize_url(url: str, base_url: str = "") -> str:
    parsed = urlsplit(urljoin(base_url, url.strip()))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("http:// 또는 https:// 기사 URL을 입력해주세요.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("인증 정보가 포함된 URL은 저장할 수 없습니다.")
    # Validate the port, but preserve it along with path/query spelling and order.
    _ = parsed.port
    query = "&".join(
        part for part in parsed.query.split("&")
        if unquote_plus(part.split("=", 1)[0]).lower() not in TRACKING_PARAMS
    )
    cleaned = urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path, query, ""))
    # Host-specific short forms (e.g. Cafe24 product_no) so SEO and detail URLs share an id.
    return canonicalize(urlsplit(cleaned)) or cleaned


def doc_id(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()
