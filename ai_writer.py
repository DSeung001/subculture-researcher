"""Draft post writing via the Gemini Flash API (free-tier friendly).

GEMINI_API_KEY comes from the environment: a local .env file (loaded with
python-dotenv) during development, a repository secret in GitHub Actions.
"""

import os

import requests


GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-3.6-flash:generateContent"
)
TIMEOUT_SECONDS = 30
SUMMARY_CHARS = 300

PROMPT_TEMPLATE = (
    "너는 애니메이션/피규어 서브컬처 X(트위터) 계정을 운영하는 소셜 미디어 에디터야. "
    "아래 소재 중에서 반응이 좋을 만한 내용을 골라 한국어 게시글 초안을 하나 써줘. "
    "글의 각도는 '{angle}'야. "
    "300자 이내, 과장된 광고 문구 없이 담백하게, 이모지는 최대 1개까지만 써줘. "
    "본문만 출력하고 링크는 쓰지 마 (링크는 따로 붙일 거야).\n\n"
    "소재:\n{material}"
)


class AiWriterError(RuntimeError):
    pass


def api_key() -> str:
    return (os.environ.get("GEMINI_API_KEY") or "").strip()


def _material_block(items: list[dict]) -> str:
    lines = []
    for idx, item in enumerate(items, start=1):
        title = (item.get("titleKo") or item.get("title") or "").strip()
        summary = (item.get("summaryKo") or item.get("summary") or "").strip()
        source = item.get("source") or ""
        lines.append(f"{idx}. {title}")
        if summary:
            lines.append(f"   요약: {summary[:SUMMARY_CHARS]}")
        if source:
            lines.append(f"   출처: {source}")
    return "\n".join(lines)


def _reference_links(items: list[dict]) -> str:
    lines = [
        f"- ({item['source']}) {item['url']}" if item.get("source") else f"- {item['url']}"
        for item in items
        if item.get("url")
    ]
    return "\n".join(lines)


def write_draft_body(items: list[dict], angle: str) -> str:
    """Ask Gemini Flash for a short Korean draft, then append every source link.

    The reference-link section is assembled locally (not by the model) so a
    draft can never lose or hallucinate the data it was built from.
    """
    key = api_key()
    if not key:
        raise AiWriterError("GEMINI_API_KEY가 설정되어 있지 않습니다.")
    if not items:
        raise AiWriterError("초안을 쓸 재료가 없습니다.")

    prompt = PROMPT_TEMPLATE.format(angle=angle, material=_material_block(items))

    try:
        response = requests.post(
            GEMINI_URL,
            params={"key": key},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                # Draft writing doesn't need multi-step reasoning; skip it to save quota.
                "generationConfig": {"thinkingConfig": {"thinkingBudget": 0}},
            },
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise AiWriterError(f"Gemini 요청 실패: {exc}") from exc

    candidates = payload.get("candidates") or []
    parts = (candidates[0].get("content") or {}).get("parts") if candidates else []
    text = "".join(part.get("text", "") for part in (parts or [])).strip()
    if not text:
        reason = (candidates[0].get("finishReason") if candidates else None) or "빈 응답"
        raise AiWriterError(f"Gemini가 초안을 생성하지 못했습니다: {reason}")

    links = _reference_links(items)
    return f"{text}\n\n참고 링크:\n{links}\n" if links else f"{text}\n"
