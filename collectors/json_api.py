from datetime import datetime

import requests
from bs4 import BeautifulSoup

from content_store import normalize_url
from collectors.common import save_records
from collectors.http import pause_between_requests, request_headers
from collectors.images import first_image
from image_urls import clean_image_url


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


def json_api_items(source: dict):
    pause_between_requests(source)
    response = requests.get(
        source["url"], headers=request_headers(), timeout=source.get("timeout_seconds", 15),
    )
    response.raise_for_status()
    payload = response.json()
    entries = _dig(payload, source["items_path"]) if source.get("items_path") else payload
    limit = int(source.get("max_items", 50))
    if limit <= 0:
        return
    count = 0
    for entry in entries or []:
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


def collect_json_api(db, source: dict, store=None) -> dict:
    return save_records(json_api_items(source), db, source, store)
