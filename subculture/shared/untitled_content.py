"""Placeholder-titled leftovers that the store should not keep."""

from urllib.parse import urlsplit


UNTITLED_TITLE = "(제목 없음)"
_X_STATUS_HOSTS = {"x.com", "twitter.com", "www.x.com", "www.twitter.com"}


def is_untitled_x_post(url: str, title: str) -> bool:
    """True only for X/Twitter status URLs stored with the untitled placeholder."""
    if (title or "") != UNTITLED_TITLE:
        return False
    try:
        parsed = urlsplit((url or "").strip())
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if host not in _X_STATUS_HOSTS:
        return False
    return "/status/" in (parsed.path or "")


_LAFTEL_HOSTS = {"laftel.net", "www.laftel.net"}


def is_untitled_laftel_home(url: str, title: str) -> bool:
    """True only for the bare laftel.net home stored with the untitled placeholder.

    The retired 「라프텔 인기·신작」 browser collection left these behind; real
    Laftel product pages have their own path and title.
    """
    if (title or "") != UNTITLED_TITLE:
        return False
    try:
        parsed = urlsplit((url or "").strip())
    except ValueError:
        return False
    return (parsed.hostname or "").lower() in _LAFTEL_HOSTS and parsed.path in ("", "/")


def is_untitled_leftover(url: str, title: str) -> bool:
    return is_untitled_x_post(url, title) or is_untitled_laftel_home(url, title)
