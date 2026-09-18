"""Draft post writing via the Gemini Flash API (free-tier friendly).

GEMINI_API_KEY comes from the environment: a local .env file (loaded with
python-dotenv) during development, a repository secret in GitHub Actions.
"""

import os
import re
from collections import Counter

import requests

from presentation import product_caption


GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-3.6-flash:generateContent"
)
TIMEOUT_SECONDS = 30
SUMMARY_CHARS = 300
REGION_LABELS = {"KR": "국내", "JP": "일본", "US": "미국", "CN": "중국", "GLOBAL": "해외"}

# Stage 1: pick which candidates are worth writing about at all. Kept as a
# separate call (rather than folding selection into the write prompt) because
# the candidate pool can be much larger than what's worth spending the write
# prompt's context on, and picking well needs different criteria (virality,
# specificity, domestic-first) than writing well does.
SELECT_PROMPT_TEMPLATE = (
    "너는 애니메이션/피규어 서브컬처 X(트위터) 계정을 운영하는 소셜 미디어 에디터야. "
    "아래 소재 목록 중에서 X에 올렸을 때 반응(좋아요/리트윗/댓글)이 가장 좋을 만한 소재를 "
    "{size}개 골라줘. 화제성과 구체성(가격·사이즈·일정 등 정보가 있는지)을 중요하게 보고, "
    "[국내]로 표시된 국내(한국) 사이트 소재를 해외 소재보다 우선해줘. "
    "애니메이션 소재는 AniList 지표(트렌딩·인기도·즐겨찾기·평균점수)가 높을수록 인지도가 높은 "
    "작품이니 그런 소재를 우선해줘. "
    "구매정보에 예약중이거나 한정 수량이라고 나온 제품은 놓치면 못 사는 소재니까 우선해줘. "
    "번호만 쉼표로 구분해서 출력해 (예: 3,7,1). 다른 설명은 쓰지 마.\n\n"
    "소재:\n{material}"
)

# Stage 2: write the actual post for the items Stage 1 picked. The shared
# structure/format rules stay one template; only the emphasis line varies by
# the draft's dominant category, so a FIGURE draft leans on price/size/release
# info while a FESTIVAL draft leans on date/venue, etc.
PROMPT_TEMPLATE = (
    "너는 애니메이션/피규어 서브컬처 X(트위터) 계정을 운영하는 소셜 미디어 에디터야. "
    "아래 소재로 X 유저들이 반응하기 좋은 한국어 게시글 초안을 하나 써줘. "
    "글의 각도는 '{angle}'야.\n"
    "형식 규칙:\n"
    "- 첫 줄은 시선을 끄는 한 문장으로 시작해줘.\n"
    "- 문장을 짧게 끊고, 필요하면 줄바꿈으로 가독성을 높여줘.\n"
    "- {category_hint}\n"
    "- 과장된 광고 문구 없이 담백하게, 이모지는 최대 1개까지만 써줘.\n"
    "- 본문은 120자 이내로 써줘 (해시태그 제외).\n"
    "- 마지막 줄에 본문 내용과 직접 관련된 해시태그를 2~4개 붙여줘 (띄어쓰기 없이, 예: #피규어 #굿스마일컴퍼니).\n"
    "- 번호로 준 소재를 모두 본문에 반영해줘 (하나라도 빼지 마).\n"
    "- 제공된 소재에 있는 사실만 쓰고, 없는 일정·가격·설정은 지어내지 마.\n"
    "- 본문과 해시태그만 출력하고 링크는 쓰지 마 (링크는 따로 붙일 거야).\n\n"
    "소재:\n{material}"
)

CATEGORY_HINTS = {
    "ANIME": "화제성과 방영/공개 소식 위주로, 왜 지금 이 작품이 주목받는지 짚어줘.",
    "CHARACTER": "캐릭터의 매력 포인트(설정, 인기 이유)를 짚어줘.",
    "FIGURE": "소재에 가격·사이즈·발매(입고)일 정보가 있으면 자연스럽게 녹여줘.",
    "GOODS": "소재에 판매처·가격·한정 여부 정보가 있으면 자연스럽게 녹여줘.",
    "COLLECTION": "여러 소재를 하나의 흐름으로 묶어 큐레이션하듯 소개해줘.",
    "FESTIVAL": "소재에 행사 일정·장소 정보가 있으면 자연스럽게 녹여줘.",
}
DEFAULT_CATEGORY_HINT = "핵심 정보를 짚어줘."


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
        # Structured product fields (price/예약 여부/사이즈/발매일 등), not just
        # whatever the scraped summary text happens to mention, so the model
        # can state reservation urgency accurately.
        product = product_caption(item)
        if product:
            lines.append(f"   구매정보: {product}")
    return "\n".join(lines)


def _dominant_category(items: list[dict]) -> str:
    counts = Counter(item.get("category") for item in items if item.get("category"))
    return counts.most_common(1)[0][0] if counts else "UNKNOWN"


def _anilist_metrics(item: dict) -> str:
    parts = []
    for field, label in (
        ("trending", "트렌딩"),
        ("popularity", "인기도"),
        ("favourites", "즐겨찾기"),
        ("averageScore", "평균점수"),
    ):
        value = item.get(field)
        if isinstance(value, int) and value > 0:
            parts.append(f"{label} {value:,}")
    return ", ".join(parts)


def _selection_block(items: list[dict]) -> str:
    # Original title (not the Korean translation) here so a title's actual
    # name/notation lines up with how it's known (e.g. AniList's titles).
    lines = []
    for idx, item in enumerate(items, start=1):
        title = (item.get("title") or item.get("titleKo") or "").strip()
        summary = (item.get("summaryKo") or item.get("summary") or "").strip()
        region_label = REGION_LABELS.get(item.get("region"), "해외")
        lines.append(f"{idx}. [{region_label}] {title}")
        if summary:
            lines.append(f"   요약: {summary[:SUMMARY_CHARS]}")
        metrics = _anilist_metrics(item)
        if metrics:
            lines.append(f"   AniList 지표: {metrics}")
        product = product_caption(item)
        if product:
            lines.append(f"   구매정보: {product}")
    return "\n".join(lines)


def _call_gemini(prompt: str, key: str) -> str:
    try:
        response = requests.post(
            GEMINI_URL,
            params={"key": key},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                # Neither selection nor draft writing needs multi-step
                # reasoning; skip it to save quota.
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
        raise AiWriterError(f"Gemini가 응답을 생성하지 못했습니다: {reason}")
    return text


def select_top_items(items: list[dict], size: int) -> list[dict]:
    """Ask Gemini which candidates are most likely to perform well on X.

    Falls back to the input order (already score-sorted by the caller) if
    there's no API key or the call fails/returns nothing parseable, so a
    selection hiccup never blocks draft creation.
    """
    if len(items) <= size:
        return items[:size]

    key = api_key()
    if not key:
        return items[:size]

    prompt = SELECT_PROMPT_TEMPLATE.format(size=size, material=_selection_block(items))
    try:
        text = _call_gemini(prompt, key)
    except AiWriterError:
        return items[:size]

    picked = []
    seen = set()
    for token in re.findall(r"\d+", text):
        idx = int(token) - 1
        if 0 <= idx < len(items) and idx not in seen:
            seen.add(idx)
            picked.append(items[idx])
        if len(picked) == size:
            break

    return picked if picked else items[:size]


def _append_source_block(body: str, items: list[dict]) -> str:
    """Append real source titles/URLs after the model text (never model-generated)."""
    lines = [body.rstrip(), "", "출처"]
    appended = False
    for item in items:
        url = (item.get("url") or "").strip()
        if not url:
            continue
        title = (item.get("titleKo") or item.get("title") or "").strip()
        if title:
            lines.append(f"- {title}")
            lines.append(f"  {url}")
        else:
            lines.append(f"- {url}")
        appended = True
    if not appended:
        return f"{body.rstrip()}\n"
    return "\n".join(lines) + "\n"


def write_draft_body(items: list[dict], angle: str) -> str:
    """Ask Gemini Flash for a short Korean X-post draft, then attach real source URLs.

    The model writes body + hashtags only (no links). After the call, this
    function appends a 출처 block built from each item's actual `url` /
    `titleKo` fields so the draft body always carries the bundled sources
    without hallucinated links.
    """
    key = api_key()
    if not key:
        raise AiWriterError("GEMINI_API_KEY가 설정되어 있지 않습니다.")
    if not items:
        raise AiWriterError("초안을 쓸 재료가 없습니다.")

    category_hint = CATEGORY_HINTS.get(_dominant_category(items), DEFAULT_CATEGORY_HINT)
    prompt = PROMPT_TEMPLATE.format(
        angle=angle, category_hint=category_hint, material=_material_block(items)
    )
    text = _call_gemini(prompt, key)
    return _append_source_block(text, items)
