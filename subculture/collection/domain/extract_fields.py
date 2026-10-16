"""Parse field values from extractor-selected text (no HTML I/O)."""

import re
from datetime import datetime, timezone

PRICE_RE = re.compile(r"(?<!\d)(\d{1,3}(?:,\d{3})+)\s*원")
PREORDER_WORDS = ("예약", "PRE-ORDER", "PREORDER", "予約")
SOLD_OUT_WORDS = ("품절", "SOLD OUT", "판매 종료")
KOREAN_DATE_RE = re.compile(
    r"(\d{4})[.\-](\d{1,2})[.\-](\d{1,2})"
    r"|(\d{2})년\s*(\d{1,2})월\s*(\d{1,2})일"
)

PARSE_KINDS = frozenset({"text", "krw", "sale_status", "date"})
LIST_FIELD_NAMES = frozenset({
    "link", "title", "price", "image", "status", "deadline", "published",
})
DETAIL_FIELD_NAMES = frozenset({"gallery", "price", "status", "deadline", "image", "title"})


def parse_krw(text: str) -> int | None:
    """First amount of 1,000원 or more in `text`, or None."""
    values = [int(value.replace(",", "")) for value in PRICE_RE.findall(text or "")]
    return next((value for value in values if value >= 1000), None)


def parse_sale_status(text: str, extra_preorder: tuple[str, ...] = ()) -> str:
    """Sold-out wins over preorder; otherwise in stock."""
    upper = (text or "").upper()
    if any(word.upper() in upper for word in SOLD_OUT_WORDS):
        return "SOLD_OUT"
    preorder_words = PREORDER_WORDS + tuple(extra_preorder)
    if any(word.upper() in upper for word in preorder_words):
        return "PREORDER"
    return "IN_STOCK"


def parse_date(text: str) -> str | None:
    """ISO date from Korean date patterns near the start of `text`."""
    match = KOREAN_DATE_RE.search(text or "")
    if not match:
        return None
    if match.group(1):
        year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
    else:
        year, month, day = 2000 + int(match.group(4)), int(match.group(5)), int(match.group(6))
    if 2000 <= year <= 2099 and 1 <= month <= 12 and 1 <= day <= 31:
        return f"{year:04d}-{month:02d}-{day:02d}"
    return None


def apply_parse(kind: str, text: str, *, preorder_words: tuple[str, ...] = ()):
    """Return the parsed value for `kind`, or the stripped text for `text`."""
    kind = kind or "text"
    if kind == "krw":
        return parse_krw(text)
    if kind == "sale_status":
        return parse_sale_status(text, preorder_words)
    if kind == "date":
        return parse_date(text)
    return " ".join((text or "").split())


def product_fields_from_extract(
    source: dict,
    *,
    price: int | None,
    status: str | None = None,
    deadline: str | None = None,
    image_url: str | None = None,
) -> dict:
    """Build PRODUCT fields when an extract profile already resolved price/status."""
    if price is None or price < 1000:
        return {}
    fields = {
        "entityType": "PRODUCT",
        "shop": source.get("shop") or source["name"],
        "saleStatus": status or "IN_STOCK",
        "price": price,
        "currency": "KRW",
        "preorderEndAt": deadline,
        "productCheckedAt": datetime.now(timezone.utc),
    }
    if image_url:
        fields["imageUrl"] = image_url
    return fields
