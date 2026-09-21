"""Draft post writing via the Gemini Flash API (free-tier friendly).

GEMINI_API_KEY comes from the environment: a local .env file (loaded with
python-dotenv) during development, a repository secret in GitHub Actions.
"""

import json
import os
import re
import time
from collections import Counter
from datetime import datetime

import requests

from subculture.drafts.domain.posts import BODY_TARGET, DraftPosts, build_reply
from subculture.shared.presentation import KST, price_text, product_caption


GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-3.6-flash:generateContent"
)
TIMEOUT_SECONDS = 30
SUMMARY_CHARS = 300

# Free-tier quota guards. Requests are spaced at least MIN_INTERVAL_SECONDS
# apart (~9/min, under the 10 RPM free limit). 429/5xx responses are retried
# after the server-suggested delay (or exponential backoff); a delay longer
# than MAX_RETRY_WAIT_SECONDS is not worth blocking a CLI run or web request
# for, so it fails instead. A per-day quota 429 trips a breaker so the rest of
# the process stops calling Gemini.
MIN_INTERVAL_SECONDS = 6.5
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 5.0
MAX_RETRY_WAIT_SECONDS = 30.0
RETRYABLE_STATUS = {429, 500, 503}
RETRY_DELAY_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*s\s*$")

_last_call_at: float | None = None
_quota_exhausted = False
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

# Stage 2: write the posts for the items Stage 1 picked. A draft is two posts: a content post
# (no links) and a reply that lists the links. The model writes only the content post and a short
# display name per source; the reply and every URL are assembled in code from the sources, so the
# model never sees or writes a URL. The shared structure/format rules stay one template; only the
# emphasis line varies by the draft's dominant category, so a FIGURE draft leans on price/size/
# release info while a FESTIVAL draft leans on date/venue, etc.
PROMPT_TEMPLATE = (
    "너는 X(트위터)에서 애니메이션/피규어 서브컬처 소식을 모아 공유하는 큐레이션 계정의 운영자야. "
    "물건을 파는 판매자가 아니라, 좋은 소식을 찾아 알려주는 정보 공유자의 시점으로 써. "
    "아래 소재로 게시물 1개(post1)를 쓰고, 소재마다 짧은 이름(display_name)을 붙여줘. "
    "글의 각도는 '{angle}'야. 실제 사람이 새 소식을 발견해서 소개하는 것처럼 자연스럽게 쓰고, "
    "광고 문구나 상품 DB를 그대로 요약한 것처럼 보이면 안 돼. "
    "링크는 별도 답글에 코드가 붙일 거야.\n"
    "[post1: 콘텐츠 글]\n"
    "- URL, 링크, 쇼핑몰 이름은 절대 넣지 마.\n"
    "- 소재를 단순 나열하지 말고 공통점이나 차이점 1~2개만 골라 이야기해줘. "
    "모든 소재의 이름·스케일을 한 문장에 억지로 나열하지 마. 가격은 아래 [가격 정보] 규칙을 따라.\n"
    "- 첫 문장은 짧고 자연스러운 관심 유도 문장으로 써줘.\n"
    "- 3~6줄, 줄바꿈으로 가독성을 높이고, {body_target}자 이내로 써줘 (해시태그 포함).\n"
    "- 마지막 줄에 관련성 높은 해시태그를 2~3개 붙여줘 (띄어쓰기 없이, 예: #피규어 #굿스마일컴퍼니).\n"
    "- 이모지는 최대 1개까지만 써줘.\n"
    "- {category_hint}\n"
    "[문장 다양성]\n"
    "매번 소재에 가장 자연스러운 접근법 하나를 골라줘: 여러 신상이 동시에 나온 점 언급 / 가격 차이 언급 / "
    "스케일·종류 차이 언급 / 특정 소재 하나를 중심으로 나머지를 함께 소개 / 가벼운 개인적 관찰로 시작 / "
    "마지막에 선택 질문. 항상 질문으로 시작하거나 끝내지 말고, 같은 표현과 문장 구조를 반복하지 마.\n"
    "[정보 공유 계정]\n"
    "- 판매자·쇼핑몰 어투가 아니라 '이런 게 나왔대', '눈에 띄어서 공유해' 같은 소식 전달 어투로 써줘. "
    "구매·예약·주문을 권하거나 재촉하지 마. 가격·예약 일정·재고는 권유가 아니라 사실 정보로만 담담하게 전해줘.\n"
    "- '구매하세요', '예약하세요', '주문', '지금 사세요', '득템', '특가', '할인', '서두르세요', '재고 얼마 없음', "
    "'판매 중입니다', '저희', '우리 샵' 같은 판매자 표현을 쓰지 마. 링크를 안내하는 문구도 쓰지 마.\n"
    "- 직접 사 봤거나 실물을 본 것처럼 쓰지 마. 소재에 없는 사용·구매 경험은 지어내지 마. "
    "감상은 '눈에 띄네', '라인이 예쁘다' 정도의 가벼운 관찰로 하고, 특정 상점이나 판매처를 홍보하지 마.\n"
    "[가격 정보]\n"
    "- 소재에 '가격'이 있으면 본문에서 그 가격을 빠뜨리지 마. 소재별로 짚어도 되고, 가격대가 비슷하면 "
    "'7만 원대'나 '7~10만 원'처럼 묶어도 돼. 가격이 눈에 띄게 다른 소재는 따로 짚어줘.\n"
    "- 가격은 소재에 적힌 금액만 써. 환산·할인 계산·추측은 하지 말고, 가격이 없는 소재의 가격은 언급하지 마.\n"
    "- 가격은 사실 정보로만 담담하게 전하고, 싸다·저렴하다·가성비 같은 판단이나 구매 권유는 쓰지 마.\n"
    "- display_name에는 가격을 넣지 마.\n"
    "[예약/일반 구분]\n"
    "- 각 소재의 '판매유형'을 그대로 따라줘. 예약 상품과 일반 판매 상품이 섞여 있으면 어느 쪽이 예약 접수 중이고 "
    "어느 쪽이 이미 재고가 있는지 소식 전하듯 짚어줘 (예: 'A는 예약 접수 중, B는 재고가 있는 상태').\n"
    "- 모두 같은 유형이면 반복하지 말고 한 번만 언급해줘.\n"
    "- 판매유형에 없는 예약 여부·마감일·입고일은 추측하지 마. '예약 마감 지남'은 예약 중이라고 쓰지 마.\n"
    "- 품절 소재는 구매를 권하는 표현을 쓰지 마.\n"
    "[문체]\n"
    "- 한국 X 사용자가 쓴 것처럼 간결하게. 보도자료·쇼핑몰 광고·SEO 문체는 피해줘.\n"
    "- '놓치지 마세요', '다양한 라인업', '추천드립니다', '비교해 보세요' 같은 광고성 표현을 쓰지 마. "
    "'~까지.', '~입니다.'를 연속으로 쓰지 마. 과장하지 마.\n"
    "- 제공된 소재에 있는 사실만 쓰고, 없는 일정·가격·발매일·크기·특전·평가는 지어내지 마.\n"
    "- AniList, 트렌딩, 순위/집계 사이트명, 출처 내부명은 쓰지 마. "
    "인지도는 '인기 있는', '화제의', '지금 주목받는'처럼 자연스러운 표현으로 써줘.\n"
    "[products: 소재별 이름]\n"
    "- 소재마다 index(소재 번호)와 display_name을 하나씩 줘. 소재를 빠뜨리지 마.\n"
    "- display_name은 상품을 알아볼 수 있는 짧은 이름으로, '[예약]' 같은 쇼핑몰 태그, 제조사명, "
    "이미 앞에 나온 작품명 반복, 가격·스케일 설명을 빼줘. URL은 쓰지 마.\n\n"
    "소재:\n{material}"
)

# Structured output for the selection call: 1-based candidate numbers, best first.
SELECTION_SCHEMA = {"type": "ARRAY", "items": {"type": "INTEGER"}}

# Structured output: the model returns the post and the per-source names, never a link.
POSTS_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "post1": {"type": "STRING"},
        "products": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "index": {"type": "INTEGER"},
                    "display_name": {"type": "STRING"},
                },
                "required": ["index", "display_name"],
            },
        },
    },
    "required": ["post1", "products"],
}

CATEGORY_HINTS = {
    "ANIME": (
        "화제·인기와 방영/공개 소식을 SNS 홍보 글로 자연스럽게 녹여줘. "
        "집계 사이트나 트렌딩 순위는 언급하지 마."
    ),
    "CHARACTER": "캐릭터의 매력 포인트(설정, 인기 이유)를 짚어줘.",
    "FIGURE": "소재에 가격·사이즈·발매(입고)일 정보가 있으면 자연스럽게 녹여줘.",
    "GOODS": "소재에 가격·한정 여부 정보가 있으면 자연스럽게 녹여줘.",
    "COLLECTION": "여러 소재를 하나의 흐름으로 묶어 큐레이션하듯 소개해줘.",
    "FESTIVAL": "소재에 행사 일정·장소 정보가 있으면 자연스럽게 녹여줘.",
}
DEFAULT_CATEGORY_HINT = "핵심 정보를 짚어줘."
# Source names that leak ranking/site jargon into the public post if passed through.
_INTERNAL_SOURCE_MARKERS = ("AniList", "트렌딩")


class AiWriterError(RuntimeError):
    pass


def api_key() -> str:
    return (os.environ.get("GEMINI_API_KEY") or "").strip()


def _is_public_source(source: str) -> bool:
    """Shop/media names are fine in the write prompt; ranking feeds are not."""
    return bool(source) and not any(marker in source for marker in _INTERNAL_SOURCE_MARKERS)


def _popularity_hint(item: dict) -> str:
    trending = item.get("trending")
    popularity = item.get("popularity")
    if (isinstance(trending, int) and trending > 0) or (
        isinstance(popularity, int) and popularity > 0
    ):
        return "인기 있는 작품"
    return ""


def _airing_hint(item: dict) -> str:
    parts = []
    episode = item.get("episode")
    if isinstance(episode, int) and episode > 0:
        parts.append(f"{episode}화")
    airing = item.get("nextAiringAt")
    if airing:
        parts.append(f"다음 방영 {airing}")
    return " · ".join(parts)


def _sale_type_hint(item: dict, today: str | None = None) -> str:
    """Preorder vs regular sale, from the stored status; empty when it is not known."""
    if item.get("entityType") != "PRODUCT":
        return ""
    status = item.get("saleStatus")
    if status == "PREORDER":
        deadline = str(item.get("preorderEndAt") or "")
        today = today or datetime.now(KST).date().isoformat()
        if deadline and deadline[:10] < today:
            # A stored PREORDER can be stale once its deadline has passed.
            return f"예약 마감 지남 (마감 {deadline})"
        parts = ["예약"]
        if deadline:
            parts.append(f"예약마감 {deadline}")
        if item.get("releaseWindowText"):
            parts.append(f"입고 {item['releaseWindowText']}")
        return " · ".join(parts)
    if status == "IN_STOCK":
        return "일반 판매(재고 있음)"
    if status == "SOLD_OUT":
        return "품절"
    return ""


def _material_block(items: list[dict]) -> str:
    lines = []
    for idx, item in enumerate(items, start=1):
        title = (item.get("titleKo") or item.get("title") or "").strip()
        summary = (item.get("summaryKo") or item.get("summary") or "").strip()
        source = item.get("source") or ""
        lines.append(f"{idx}. {title}")
        if summary:
            lines.append(f"   요약: {summary[:SUMMARY_CHARS]}")
        if _is_public_source(source):
            lines.append(f"   출처: {source}")
        vibe = _popularity_hint(item)
        if vibe:
            lines.append(f"   분위기: {vibe}")
        airing = _airing_hint(item)
        if airing:
            lines.append(f"   방영: {airing}")
        # Structured product fields (price/예약 여부/사이즈/발매일 등), not just
        # whatever the scraped summary text happens to mention, so the model
        # can state reservation urgency accurately.
        price = price_text(item)
        if price:
            lines.append(f"   가격: {price}")
        sale_type = _sale_type_hint(item)
        if sale_type:
            lines.append(f"   판매유형: {sale_type}")
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


def _error_details(response) -> list[dict]:
    try:
        details = (response.json().get("error") or {}).get("details") or []
    except (ValueError, AttributeError):
        return []
    return [detail for detail in details if isinstance(detail, dict)]


def _retry_delay(response) -> float | None:
    """Server-suggested wait: Retry-After header, else RetryInfo.retryDelay ("34s")."""
    header = (response.headers.get("Retry-After") or "").strip()
    if header.isdigit():
        return float(header)
    for detail in _error_details(response):
        match = RETRY_DELAY_RE.match(str(detail.get("retryDelay") or ""))
        if match:
            return float(match.group(1))
    return None


def _is_daily_quota(response) -> bool:
    for detail in _error_details(response):
        for violation in detail.get("violations") or []:
            if "perday" in str(violation.get("quotaId") or "").lower():
                return True
    return False


def _throttle() -> None:
    if _last_call_at is None:
        return
    wait = MIN_INTERVAL_SECONDS - (time.monotonic() - _last_call_at)
    if wait > 0:
        time.sleep(wait)


def _post_gemini(prompt: str, key: str, response_schema: dict | None = None):
    """POST with request spacing and retries; returns the final response."""
    global _last_call_at, _quota_exhausted
    if _quota_exhausted:
        raise AiWriterError("Gemini 일일 한도를 모두 사용해 호출하지 않습니다.")

    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        # Neither selection nor draft writing needs multi-step
        # reasoning; skip it to save quota.
        "generationConfig": {"thinkingConfig": {"thinkingBudget": 0}},
    }
    if response_schema is not None:
        body["generationConfig"].update(
            {"responseMimeType": "application/json", "responseSchema": response_schema}
        )
    for attempt in range(MAX_RETRIES + 1):
        _throttle()
        try:
            response = requests.post(
                GEMINI_URL, params={"key": key}, json=body, timeout=TIMEOUT_SECONDS
            )
        finally:
            _last_call_at = time.monotonic()

        if response.status_code not in RETRYABLE_STATUS or attempt == MAX_RETRIES:
            return response
        if response.status_code == 429 and _is_daily_quota(response):
            _quota_exhausted = True
            print("[Gemini] 일일 무료 한도를 모두 사용했습니다. 이후 호출은 건너뜁니다.")
            raise AiWriterError("Gemini 일일 한도를 모두 사용했습니다.")

        delay = _retry_delay(response)
        if delay is None:
            delay = BACKOFF_BASE_SECONDS * (2 ** attempt)
        if delay > MAX_RETRY_WAIT_SECONDS:
            return response
        print(
            f"[Gemini] {response.status_code} 응답, {delay:.0f}초 후 재시도 "
            f"({attempt + 1}/{MAX_RETRIES})"
        )
        time.sleep(delay)
    return response


def _call_gemini(prompt: str, key: str, response_schema: dict | None = None) -> str:
    try:
        response = _post_gemini(prompt, key, response_schema)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise AiWriterError(f"Gemini 요청 실패: {exc}") from exc

    usage = payload.get("usageMetadata") or {}
    print(
        f"[Gemini] 토큰 입력={usage.get('promptTokenCount', '?')} "
        f"출력={usage.get('candidatesTokenCount', '?')}"
    )
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
        text = _call_gemini(prompt, key, SELECTION_SCHEMA)
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


def _parse_posts(text: str, item_count: int) -> tuple[str, dict[int, str]]:
    """The content post and the display names by 0-based source position, from the model's JSON."""
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise AiWriterError(f"Gemini 응답을 JSON으로 읽지 못했습니다: {exc}") from exc
    if not isinstance(payload, dict):
        raise AiWriterError("Gemini 응답 형식이 올바르지 않습니다.")
    post1 = payload.get("post1")
    post1 = post1.strip() if isinstance(post1, str) else ""
    if not post1:
        raise AiWriterError("Gemini가 본문을 쓰지 못했습니다.")

    names: dict[int, str] = {}
    for product in payload.get("products") or []:
        if not isinstance(product, dict):
            continue
        index, name = product.get("index"), product.get("display_name")
        # The numbers are 1-based like the material block; anything else is ignored.
        valid_index = isinstance(index, int) and not isinstance(index, bool) and 1 <= index <= item_count
        if valid_index and isinstance(name, str) and name.strip():
            names.setdefault(index - 1, name.strip())
    return post1, names


def write_draft_posts(items: list[dict], angle: str) -> DraftPosts:
    """Ask Gemini Flash for the content post and per-source names, then assemble the link reply.

    The model returns JSON (`post1` and a `display_name` per numbered source) and never sees a
    URL. The reply is built here from each item's real `url`, so links are never model-generated,
    broken or dropped; a source the model named badly or skipped keeps its link under a name
    cleaned from its title.
    """
    key = api_key()
    if not key:
        raise AiWriterError("GEMINI_API_KEY가 설정되어 있지 않습니다.")
    if not items:
        raise AiWriterError("초안을 쓸 재료가 없습니다.")

    category_hint = CATEGORY_HINTS.get(_dominant_category(items), DEFAULT_CATEGORY_HINT)
    prompt = PROMPT_TEMPLATE.format(
        angle=angle, category_hint=category_hint, body_target=BODY_TARGET,
        material=_material_block(items),
    )
    text = _call_gemini(prompt, key, POSTS_SCHEMA)
    post1, names = _parse_posts(text, len(items))
    return DraftPosts(post1 + "\n", build_reply(items, names))
