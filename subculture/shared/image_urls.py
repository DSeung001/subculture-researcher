"""Image link rules shared by the collectors, the store and the templates.

Only links are kept (never image bytes). A stored link must be a plain http(s)
URL, and site chrome (logos, icons, placeholders, sitewide share images) is
never treated as the article or product photo.
"""

import re
from html import unescape
from urllib.parse import urljoin, urlsplit

MAX_URL_LENGTH = 2000
# Lazy-loading pages keep the real photo in data-* and a placeholder in src.
# Cafe24 editor bodies use `ec-data-src`.
LAZY_ATTRS = ("data-src", "data-original", "data-lazy-src", "data-lazy", "data-echo", "ec-data-src", "src")
# Unrendered shop template tokens such as `{$js-src}` (raw or URL-encoded).
TEMPLATE_TOKEN = re.compile(r"\{\$|%7B%24", re.I)
# Path/query tokens that mark UI assets, trackers and default share images.
NOT_A_PHOTO = re.compile(
    r"(?:^|[/_.\-=])(?:logo|icon|ico|favicon|sprite|blank|spacer|pixel|placeholder|"
    r"no[_-]?(?:image|img|photo|thumb)|dummy|loading|ogp|ogimage|share-image|default)(?:[/_.\-?=&]|$)"
    r"|\.(?:svg|ico)(?:$|[?#])",
    re.I,
)


def http_url(value) -> str | None:
    """The URL if it is a plain absolute http(s) link, otherwise None."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > MAX_URL_LENGTH:
        return None
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    return value


def clean_image_url(value, base_url: str = "", deny=()) -> str | None:
    """Absolute http(s) URL of a photo, or None for empty values and non-photo assets.

    `deny` holds extra per-source regexes matched against the path and query.
    """
    if not isinstance(value, str):
        return None
    value = unescape(value.strip())
    if not value or value.lower().startswith(("data:", "javascript:", "blob:")):
        return None
    if TEMPLATE_TOKEN.search(value):
        return None
    url = http_url(urljoin(base_url, value))
    if url is None:
        return None
    parsed = urlsplit(url)
    target = f"{parsed.path}?{parsed.query}" if parsed.query else parsed.path
    if NOT_A_PHOTO.search(target) or any(re.search(pattern, target, re.I) for pattern in deny):
        return None
    return url
