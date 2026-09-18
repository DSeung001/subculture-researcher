"""Korean translation of foreign titles/summaries via the free MyMemory API."""

import html
import os
import re
import time
from datetime import datetime, timezone

import requests


MYMEMORY_URL = "https://api.mymemory.translated.net/get"
MAX_QUERY_BYTES = 500
REQUEST_GAP_SECONDS = 0.35
TIMEOUT_SECONDS = 15

# Letters we use to decide whether a title is already Korean.
_HANGUL = re.compile(r"[\uac00-\ud7a3]")
_SCRIPT = re.compile(r"[A-Za-z\u00c0-\u024f\uac00-\ud7a3\u3040-\u30ff\u3400-\u9fff]")

_session = requests.Session()
_last_request_at = 0.0
_quota_exhausted = False


def needs_translation(text: str) -> bool:
    """True when the text has letters and is not mostly Hangul."""
    chars = _SCRIPT.findall((text or "").strip())
    if not chars:
        return False
    hangul = sum(1 for char in chars if _HANGUL.fullmatch(char))
    return hangul / len(chars) < 0.5


def enrich_translation(item: dict) -> dict:
    """Return Firestore translation fields, or {} if skipped/failed.

    Never raises: collection should continue with the original title.
    """
    title = (item.get("title") or "").strip()
    summary = (item.get("summary") or "").strip()
    translate_title = needs_translation(title)
    translate_summary = needs_translation(summary)
    if not translate_title and not translate_summary:
        return {}

    title_ko, language = ("", "unknown")
    if translate_title:
        title_ko, language = translate_text(title)
        if not title_ko:
            print(f"[번역] 제목 번역 실패: {title[:80]}")
            return {}

    summary_ko = ""
    if translate_summary:
        summary_ko, summary_language = translate_text(summary)
        if summary_ko and language == "unknown":
            language = summary_language
        elif not summary_ko:
            print(f"[번역] 요약 번역 실패: {summary[:80]}")

    return {
        "titleKo": title_ko,
        "summaryKo": summary_ko,
        "sourceLanguage": language or "unknown",
        "translatedAt": datetime.now(timezone.utc).isoformat(),
    }


def translate_text(text: str) -> tuple[str, str]:
    """Translate to Korean. Returns (translated_text, source_language)."""
    global _last_request_at, _quota_exhausted
    text = (text or "").strip()
    if not text or _quota_exhausted:
        return "", "unknown"

    wait = REQUEST_GAP_SECONDS - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)

    params = {"q": _utf8_limit(text), "langpair": "autodetect|ko"}
    email = (os.environ.get("MYMEMORY_EMAIL") or "").strip()
    if email:
        params["de"] = email

    try:
        response = _session.get(MYMEMORY_URL, params=params, timeout=TIMEOUT_SECONDS)
        _last_request_at = time.monotonic()
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"[번역] MyMemory 요청 실패: {exc}")
        return "", "unknown"

    if payload.get("quotaFinished"):
        _mark_quota_exhausted()
        return "", "unknown"

    status = payload.get("responseStatus")
    if status not in (200, "200"):
        details = payload.get("responseDetails") or status
        print(f"[번역] MyMemory 응답 오류: {details}")
        return "", "unknown"

    translated = html.unescape(
        str((payload.get("responseData") or {}).get("translatedText") or "")
    ).strip()
    if _is_quota_message(translated):
        _mark_quota_exhausted()
        return "", "unknown"
    if not translated:
        return "", "unknown"

    language = "unknown"
    matches = payload.get("matches") or []
    if matches and isinstance(matches[0], dict):
        source = str(matches[0].get("source") or "")
        if source and source.lower() not in {"autodetect", "auto"}:
            language = source.split("-", 1)[0].lower()
    return translated, language


def _utf8_limit(text: str, max_bytes: int = MAX_QUERY_BYTES) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip()


def _is_quota_message(text: str) -> bool:
    upper = text.upper()
    return "MYMEMORY WARNING" in upper or "ALL AVAILABLE FREE TRANSLATIONS" in upper


def _mark_quota_exhausted() -> None:
    global _quota_exhausted
    if not _quota_exhausted:
        print("[번역] 오늘 MyMemory 무료 할당량을 모두 사용했습니다.")
    _quota_exhausted = True
