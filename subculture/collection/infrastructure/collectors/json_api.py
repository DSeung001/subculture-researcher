from datetime import datetime

import requests
from bs4 import BeautifulSoup

from subculture.collection.domain.content_rules import normalize_url
from subculture.collection.infrastructure.collectors.common import save_records
from subculture.collection.infrastructure.collectors.http import page_url, pause_between_requests, request_headers
from subculture.collection.infrastructure.collectors.images import first_image
from subculture.shared.image_urls import clean_image_url


def _dig(obj, path: str):
    for key in path.split("."):
        if obj is None:
            return None
        obj = obj[int(key)] if key.isdigit() else obj.get(key)
    return obj


def _entry_image(entry, source: dict, base_url: str) -> str | None:
    """`image_field` holds a URL; `image_html_field` holds HTML whose first usable <img> is used."""
    deny = source.get("image_deny_patterns", [])
    if source.get("image_field"):
        url = clean_image_url(_dig(entry, source["image_field"]), base_url, deny)
        if url:
            return url
    if source.get("image_html_field"):
        html = _dig(entry, source["image_html_field"])
        if isinstance(html, str):
            return first_image(BeautifulSoup(html, "html.parser"), "img", base_url, deny)
    return None


def _fetch_page(source: dict, page: int):
    """Response JSON of `page`; `page_param` is a query key of the configured URL."""
    pause_between_requests(source)
    response = requests.get(
        page_url(source["url"], source.get("page_param"), page),
        headers=request_headers(), timeout=source.get("timeout_seconds", 15),
    )
    response.raise_for_status()
    return response.json()


def json_api_items(source: dict):
    limit = int(source.get("max_items", 50))
    if limit <= 0:
        return
    max_pages = max(1, int(source.get("max_pages", 1))) if source.get("page_param") else 1
    count = 0
    for page in range(1, max_pages + 1):
        payload = _fetch_page(source, page)
        entries = _dig(payload, source["items_path"]) if source.get("items_path") else payload
        if not entries:
            return
        for entry in entries:
            title = _dig(entry, source["title_field"])
            item_id = _dig(entry, source["id_field"])
            if not title or item_id is None:
                continue
            try:
                url = normalize_url(source["detail_url_template"].format(id=item_id), source["url"])
            except ValueError:
                continue
            published_at = _dig(entry, source["date_field"]) if source.get("date_field") else None
            if published_at and source.get("date_format"):
                try:
                    published_at = datetime.strptime(published_at, source["date_format"]).date().isoformat()
                except ValueError:
                    pass
            item = {"url": url, "title": title, "publishedAt": published_at, "_errors": []}
            if source.get("summary_field"):
                item["summary"] = (_dig(entry, source["summary_field"]) or "")[:500]
            image = _entry_image(entry, source, url)
            if image:
                item["imageUrl"] = image
            yield item
            count += 1
            if count >= limit:
                return
        page_count = _dig(payload, source["page_count_field"]) if source.get("page_count_field") else None
        if isinstance(page_count, int) and page >= page_count:
            return


def collect_json_api(db, source: dict, store=None) -> dict:
    return save_records(json_api_items(source), db, source, store)
