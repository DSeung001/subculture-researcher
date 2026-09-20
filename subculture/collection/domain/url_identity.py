"""Host-specific URL canonicalizers so the same product shares one identity.

Cafe24 shops expose a short detail URL (`/product/detail.html?product_no=N`)
and an SEO path (`/product/{slug}/N/`). Both resolve to the same product; we
rewrite to the short form so ContentStore dedup and allow_patterns stay stable.
Add a new Cafe24 host by appending one HostRule; other platforms get a new
rule type here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlunsplit

# Cafe24 SEO product path: /product/{slug...}/{id}/ — not detail.html itself. List pages append
# /category/{n}/display/{n}/, so the id is the first numeric segment and only that tail may follow it
# (a greedy match would return the display number instead).
_CAFE24_SEO_PATH = re.compile(
    r"^/product/(?!detail\.html)(?:[^/]+/)*?(\d+)(?:/category/\d+)?(?:/display/\d+)?/?$"
)


@dataclass(frozen=True)
class HostRule:
    """Map one or more hosts onto a single canonical host for a shop."""

    hosts: frozenset[str]
    canonical_host: str


CAFE24_SHOPS = (
    HostRule(
        frozenset({"m.figurepresso.com", "figurepresso.com", "www.figurepresso.com"}),
        "m.figurepresso.com",
    ),
    HostRule(
        frozenset({"ttabbaemall.co.kr", "www.ttabbaemall.co.kr", "m.ttabbaemall.co.kr"}),
        "ttabbaemall.co.kr",
    ),
    HostRule(
        frozenset({"comics-art.co.kr", "www.comics-art.co.kr", "m.comics-art.co.kr"}),
        "comics-art.co.kr",
    ),
    HostRule(
        frozenset({"maniahouse.co.kr", "www.maniahouse.co.kr", "m.maniahouse.co.kr"}),
        "maniahouse.co.kr",
    ),
    HostRule(
        frozenset({"herotime.co.kr", "www.herotime.co.kr", "m.herotime.co.kr"}),
        "herotime.co.kr",
    ),
    HostRule(
        frozenset({"dokidokigoods.co.kr", "www.dokidokigoods.co.kr", "m.dokidokigoods.co.kr"}),
        "dokidokigoods.co.kr",
    ),
)


def _shop_for(host: str) -> HostRule | None:
    for shop in CAFE24_SHOPS:
        if host in shop.hosts:
            return shop
    return None


def _product_no(parsed) -> str | None:
    """Extract Cafe24 product_no from query or SEO path; else None."""
    values = parse_qs(parsed.query).get("product_no")
    if values and values[0].isdigit():
        return values[0]
    match = _CAFE24_SEO_PATH.match(parsed.path or "")
    if match:
        return match.group(1)
    return None


def canonicalize(parsed) -> str | None:
    """Return a short canonical URL string, or None if no rule applies.

    `parsed` is a urlsplit result that has already had tracking params stripped
    and hostname lowercased (as produced by normalize_url before this step).
    """
    host = (parsed.hostname or "").lower()
    shop = _shop_for(host)
    if shop is None:
        return None
    product_no = _product_no(parsed)
    if product_no is None:
        return None
    scheme = parsed.scheme if parsed.scheme in {"http", "https"} else "https"
    return urlunsplit((
        scheme,
        shop.canonical_host,
        "/product/detail.html",
        f"product_no={product_no}",
        "",
    ))
