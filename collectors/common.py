import re
from datetime import datetime, timezone

from content_store import ContentStore
from image_urls import clean_image_url


PRICE_RE = re.compile(r"(?<!\d)(\d{1,3}(?:,\d{3})+)\s*원")
PREORDER_WORDS = ("예약", "PRE-ORDER", "PREORDER", "予約")
# "마감" alone is excluded: "예약 마감일"(reservation deadline) is a normal
# preorder field label, not a sold-out signal, and the two collide often.
SOLD_OUT_WORDS = ("품절", "SOLD OUT", "판매 종료")
KOREAN_DATE_RE = re.compile(
    r"(\d{4})[.\-](\d{1,2})[.\-](\d{1,2})"       # 2026-03-15 / 2026.03.15
    r"|(\d{2})년\s*(\d{1,2})월\s*(\d{1,2})일"    # 26년 3월 15일
)


def extract_product_fields(source: dict, text: str, image_url: str | None = None) -> dict:
    """가격을 실제로 찾았을 때만 PRODUCT_FIELDS를 채운다.

    뉴스 리스트처럼 상품과 무관한 항목이 섞인 소스에 붙여도, 근거 없는
    항목까지 entityType=PRODUCT로 태깅해 content_score를 오염시키지 않도록
    한다. "예약"/"품절" 같은 키워드만으로는 판단하지 않는다 — 이벤트/티켓
    예약처럼 상품과 무관한 문맥에서도 흔히 등장해 오탐이 나기 때문에,
    가격이 실제로 붙어 있는 경우에만 상품으로 취급한다.
    """
    values = [int(value.replace(",", "")) for value in PRICE_RE.findall(text)]
    price = next((value for value in values if value >= 1000), None)
    if price is None:
        return {}

    upper = text.upper()
    if any(word.upper() in upper for word in SOLD_OUT_WORDS):
        status = "SOLD_OUT"
    elif any(word.upper() in upper for word in PREORDER_WORDS):
        status = "PREORDER"
    else:
        status = "IN_STOCK"

    deadline = None
    for keyword in ("마감", "종료", "예약"):
        idx = text.find(keyword)
        if idx == -1:
            continue
        window = text[max(0, idx - 30):idx + 30]
        match = KOREAN_DATE_RE.search(window)
        if not match:
            continue
        if match.group(1):
            year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
        else:
            year, month, day = 2000 + int(match.group(4)), int(match.group(5)), int(match.group(6))
        if 2000 <= year <= 2099 and 1 <= month <= 12 and 1 <= day <= 31:
            deadline = f"{year:04d}-{month:02d}-{day:02d}"
            break

    fields = {
        "entityType": "PRODUCT",
        "shop": source.get("shop") or source["name"],
        "saleStatus": status,
        "price": price,
        "currency": "KRW",
        "preorderEndAt": deadline,
        "productCheckedAt": datetime.now(timezone.utc),
    }
    # Left out when absent so it never overwrites a photo found elsewhere (list card).
    photo = clean_image_url(image_url, deny=source.get("image_deny_patterns", []))
    if photo:
        fields["imageUrl"] = photo
    return fields


def metadata(source: dict, **fields) -> dict:
    return {
        "summary": "", "source": source["name"], "sourceType": source["type"],
        "sourceUrl": source["url"], "region": source.get("region"),
        "category": source.get("category", "UNKNOWN"),
        "contentAngle": source.get("content_angle", "NEWS"),
        "sourceTier": source.get("source_tier", "MEDIA"),
        "note": "", "postedAt": None, "publishedAt": None, **fields,
    }


class RobotsDenied(RuntimeError):
    pass


def save_records(records, db, source: dict, store: ContentStore | None = None) -> dict:
    store = store if store is not None else ContentStore(db)
    result = dict(processed=0, inserted=0, existing=0, updated=0, failed=0, skipped=0, reason="", errors=[])
    try:
        for item in records:
            result["processed"] += 1
            errors = item.get("_errors", [])
            try:
                saved = store.save(metadata(source, **item))
                for key, count in saved.items():
                    result[key] += count
            except Exception as exc:
                errors = [*errors, f"저장 실패: {exc}"]
            if errors:
                result["failed"] += 1
                message = f"{item.get('url')}: {'; '.join(errors)}"
                result["errors"].append(message)
                print(f"[항목 오류] {source['name']} {message}")
    except RobotsDenied as exc:
        result.update(skipped=1, reason=str(exc))
        result["errors"].append(str(exc))
    except Exception as exc:
        result["failed"] += 1
        result["reason"] = str(exc)
        result["errors"].append(str(exc))
        print(f"[오류] {source['name']}: {exc}")
    finally:
        close = getattr(records, "close", None)
        if close:
            close()
    return result
