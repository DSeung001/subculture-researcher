"""A comparison post for X from several items: the facts post and the reply with the links (no I/O).

Both texts are assembled from stored fields only and are never saved; each link is the
source's own `url`.
"""

import re
from dataclasses import dataclass

from subculture.shared.image_urls import http_url
from subculture.shared.presentation import product_caption

MAX_SOURCES = 20
# The facts post is meant to read like one normal post; longer than this only warns.
BODY_TARGET = 260
PRODUCT_LINKS_HEADER = "상품 페이지 참고 ↓"
PLAIN_LINKS_HEADER = "링크 ↓"

# X counts every link as this many characters, whatever its real length.
URL_LENGTH = 23

_URL = re.compile(r"https?://\S+")
_BRACKET_TOKEN = r"[\[【『「][^\]】』」]*[\]】』」]"
_LEADING_BRACKETS = re.compile(rf"^(?:\s*{_BRACKET_TOKEN})+")
_TRAILING_BRACKETS = re.compile(rf"(?:{_BRACKET_TOKEN}\s*)+$")


@dataclass(frozen=True)
class ComparePosts:
    body: str
    reply: str


def post_length(text: str) -> int:
    """Characters X would count: every URL is `URL_LENGTH` long."""
    return len(_URL.sub("x" * URL_LENGTH, text))


def _title(item: dict) -> str:
    return (item.get("titleKo") or "").strip() or (item.get("title") or "").strip()


def short_product_name(item: dict) -> str:
    """A shop listing title without its `[예약]` tags and the shop/maker names."""
    title = _title(item)
    name = _TRAILING_BRACKETS.sub("", _LEADING_BRACKETS.sub("", title))
    for extra in (item.get("manufacturer"), item.get("shop")):
        extra = str(extra or "").strip()
        if len(extra) >= 2:
            name = re.sub(re.escape(extra), " ", name, flags=re.I)
    name = " ".join(_URL.sub(" ", name).split()).strip(" -·|,/")
    return name or title or "(제목 없음)"


def _facts(item: dict) -> str:
    """Shop, sale status, price and dates of a product; the source name for anything else."""
    return product_caption(item) or str(item.get("source") or "").strip()


def post_piece(item: dict) -> dict:
    """Name, facts and link for one item. The static site ships this and only numbers the lines."""
    return {
        "name": short_product_name(item),
        "facts": _facts(item),
        "url": http_url(item.get("url")) or "",
        "product": item.get("entityType") == "PRODUCT",
    }


def build_compare_posts(items: list[dict]) -> ComparePosts:
    """Numbered names with their facts (no links), and the same numbers with links for the reply."""
    body = []
    links = []
    pieces = [post_piece(item) for item in items]
    for number, piece in enumerate(pieces, start=1):
        name = piece["name"]
        body.append(f"{number}. {name}")
        if piece["facts"]:
            body.append(f"   {piece['facts']}")
        if piece["url"]:
            links.append(f"{number}. {name}\n{piece['url']}")
    header = PRODUCT_LINKS_HEADER if any(piece["product"] for piece in pieces) else PLAIN_LINKS_HEADER
    reply = "\n\n".join([header, *links]) + "\n" if links else ""
    return ComparePosts("\n".join(body) + "\n" if body else "", reply)
