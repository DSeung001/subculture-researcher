"""The two posts of a draft: the content post and the reply that carries the links (no I/O).

URLs never come from the model. The reply is always assembled here from each source's own
`url`, so a model can neither break nor invent a link.
"""

import re
from dataclasses import dataclass

from subculture.shared.image_urls import http_url

# The content post is meant to read like one normal post; longer than this only warns.
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
class DraftPosts:
    body: str
    reply: str


def post_length(text: str) -> int:
    """Characters X would count: every URL is `URL_LENGTH` long."""
    return len(_URL.sub("x" * URL_LENGTH, text))


def _title(item: dict) -> str:
    return ((item.get("titleKo") or "").strip() or (item.get("title") or "").strip())


def short_product_name(item: dict) -> str:
    """A shop listing title without its `[예약]` tags and the shop/maker names.

    Only a fallback for sources the model gave no name for.
    """
    title = _title(item)
    name = _TRAILING_BRACKETS.sub("", _LEADING_BRACKETS.sub("", title))
    for extra in (item.get("manufacturer"), item.get("shop")):
        extra = str(extra or "").strip()
        if len(extra) >= 2:
            name = re.sub(re.escape(extra), " ", name, flags=re.I)
    name = " ".join(name.split()).strip(" -·|,/")
    return name or title


def _clean_name(name: str) -> str:
    return " ".join(_URL.sub(" ", name or "").split())


def reply_header(items: list[dict]) -> str:
    """Fixed opening line of the reply; sources that are not products get a plain one."""
    return PRODUCT_LINKS_HEADER if any(item.get("entityType") == "PRODUCT" for item in items) else PLAIN_LINKS_HEADER


def build_reply(items: list[dict], names: dict[int, str] | None = None) -> str:
    """`header`, then `name` + `url` per source that has a link.

    `names` maps a source's position in `items` to a display name. A source without one keeps its
    link under `short_product_name`, so a missing name never drops a link.
    """
    names = names or {}
    blocks = []
    for position, item in enumerate(items):
        url = http_url(item.get("url"))
        if not url:
            continue
        name = _clean_name(names.get(position, "")) or short_product_name(item)
        blocks.append(f"{name}\n{url}" if name else url)
    if not blocks:
        return ""
    return "\n\n".join([reply_header(items), *blocks]) + "\n"
