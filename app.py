import streamlit as st
from datetime import datetime, timezone
from firebase_admin import firestore

from firebase_client import get_db
from content_store import add_manual_content
from sources_config import community_source_names
from presentation import (
    effective_date,
    format_date_kst,
    is_new_today,
    metric_caption,
    sort_items,
    summary_preview,
)


CATEGORIES = ["ANIME", "CHARACTER", "FIGURE", "GOODS", "COLLECTION", "UNKNOWN"]
STATUSES = ["NEW", "KEEP", "HOLD", "IGNORE"]
ANGLES = ["NEWS", "COMPARE", "SIZE", "PRICE", "QUESTION", "GUIDE", "COLLECTION"]
# COMMUNITY(사용자 커뮤니티)는 배제 정책에 따라 선택/필터 대상에서 제외한다.
SOURCE_TIERS = ["OFFICIAL", "MEDIA"]

CATEGORY_LABELS = {
    "ANIME": "애니",
    "CHARACTER": "캐릭터",
    "FIGURE": "피규어",
    "GOODS": "굿즈",
    "COLLECTION": "컬렉션",
    "UNKNOWN": "미분류",
}
STATUS_LABELS = {
    "NEW": "새 항목",
    "KEEP": "채택",
    "HOLD": "보류",
    "IGNORE": "무시",
}
ANGLE_LABELS = {
    "NEWS": "뉴스",
    "COMPARE": "비교",
    "SIZE": "크기",
    "PRICE": "가격",
    "QUESTION": "질문/고민",
    "GUIDE": "가이드",
    "COLLECTION": "컬렉션",
}
TIER_LABELS = {
    "OFFICIAL": "공식",
    "MEDIA": "미디어",
    "COMMUNITY": "커뮤니티",
}


@st.cache_resource
def db():
    return get_db()


def update_content(document_id: str, **fields):
    db().collection("contents").document(document_id).update(fields)


CHUNK_SIZE = 20


def reset_visible_count():
    st.session_state["visible_count"] = CHUNK_SIZE


st.set_page_config(page_title="서브컬처 리서처", layout="wide")
st.title("서브컬처 리서처")
st.caption("애니 · 피규어 · 굿즈 · 컬렉션 콘텐츠 후보를 모아보는 개인용 리서치 인박스")

with st.sidebar:
    st.header("수동 콘텐츠 추가")
    with st.form("manual-add", clear_on_submit=True):
        url = st.text_input("URL")
        title = st.text_input("제목")
        category = st.selectbox(
            "카테고리",
            CATEGORIES,
            format_func=lambda value: CATEGORY_LABELS[value],
        )
        angle = st.selectbox(
            "콘텐츠 포맷",
            ANGLES,
            format_func=lambda value: ANGLE_LABELS[value],
        )
        source_tier = st.selectbox(
            "소스 티어",
            SOURCE_TIERS,
            index=SOURCE_TIERS.index("MEDIA"),
            format_func=lambda value: TIER_LABELS[value],
        )
        submitted = st.form_submit_button("저장")

    if submitted:
        if not url.strip():
            st.error("URL을 입력해주세요.")
        else:
            try:
                created = add_manual_content(
                    db(), url, title, category, angle, source_tier,
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                if created:
                    st.success("저장했습니다.")
                    st.rerun()
                else:
                    st.info("이미 저장된 URL입니다.")

    st.divider()
    st.header("필터 & 정렬")
    category_filter = st.selectbox(
        "카테고리",
        ["ALL"] + CATEGORIES,
        format_func=lambda value: "전체" if value == "ALL" else CATEGORY_LABELS[value],
        key="category_filter",
        on_change=reset_visible_count,
    )
    status_filter = st.selectbox(
        "상태",
        ["ACTIVE"] + STATUSES,
        format_func=lambda value: (
            "무시 제외 전체" if value == "ACTIVE" else STATUS_LABELS[value]
        ),
        key="status_filter",
        on_change=reset_visible_count,
    )
    tier_filter = st.selectbox(
        "소스 티어",
        ["ALL"] + SOURCE_TIERS,
        format_func=lambda value: "전체" if value == "ALL" else TIER_LABELS[value],
        key="tier_filter",
        on_change=reset_visible_count,
    )
    unposted_only = st.checkbox(
        "미발행만",
        value=False,
        key="unposted_only",
        on_change=reset_visible_count,
    )
    sort_order = st.radio(
        "정렬",
        ["NEWEST", "OLDEST"],
        format_func=lambda value: "최신순" if value == "NEWEST" else "오래된순",
        horizontal=True,
        key="sort_order",
        on_change=reset_visible_count,
    )
    limit = st.slider(
        "불러올 개수",
        min_value=20, max_value=200, value=50, step=10,
        key="limit",
        on_change=reset_visible_count,
    )

query = (
    db()
    .collection("contents")
    .order_by("collectedAt", direction=firestore.Query.DESCENDING)
    .limit(limit)
)

docs = list(query.stream())
community_names = community_source_names()

items = []
for snapshot in docs:
    item = snapshot.to_dict()
    item["_id"] = snapshot.id

    if category_filter != "ALL" and item.get("category") != category_filter:
        continue

    if status_filter == "ACTIVE" and item.get("status") == "IGNORE":
        continue

    if status_filter != "ACTIVE" and item.get("status") != status_filter:
        continue

    # sourceTier catches new writes; source name also catches legacy docs
    # collected before the sourceTier field existed.
    if item.get("sourceTier") == "COMMUNITY" or item.get("source") in community_names:
        continue

    if tier_filter != "ALL" and item.get("sourceTier") != tier_filter:
        continue

    if unposted_only and item.get("postedAt"):
        continue

    items.append(item)

items = sort_items(items, newest_first=(sort_order == "NEWEST"))

st.session_state.setdefault("visible_count", CHUNK_SIZE)
visible_count = min(st.session_state["visible_count"], len(items))
page_items = items[:visible_count]


def load_more():
    st.session_state["visible_count"] += CHUNK_SIZE


c1, c2, c3, c4 = st.columns(4)
c1.metric("불러온 항목", len(docs))
c2.metric("필터 결과", len(items))
c3.metric("새 항목", sum(1 for item in items if item.get("status") == "NEW"))
c4.metric("오늘 추가", sum(1 for item in items if is_new_today(item)))

st.divider()

for item in page_items:
    category_value = item.get("category", "UNKNOWN")
    angle_value = item.get("contentAngle", "NEWS")
    status_value = item.get("status", "NEW")
    tier_value = item.get("sourceTier") or "MEDIA"
    posted_at = item.get("postedAt")

    title = item.get("title") or "(제목 없음)"
    badge = "🆕 " if is_new_today(item) else ""
    posted_label = (
        f"발행 {format_date_kst(posted_at)}"
        if isinstance(posted_at, datetime)
        else ("발행됨" if posted_at else "미발행")
    )

    meta = " · ".join(
        value
        for value in [
            item.get("source"),
            CATEGORY_LABELS.get(category_value, category_value),
            ANGLE_LABELS.get(angle_value, angle_value),
            TIER_LABELS.get(tier_value, tier_value),
            STATUS_LABELS.get(status_value, status_value),
            posted_label,
            format_date_kst(effective_date(item)),
        ]
        if value
    )

    url = item.get("url")

    with st.container(border=True):
        line1, menu = st.columns([9, 1])
        line1.markdown(f"**{badge}{title}** — {meta}")
        line1.caption(summary_preview(item))

        with menu.popover("⋯ 관리", use_container_width=True):
            a, b = st.columns(2)
            if a.button(
                "✅ 채택", key=f"keep-{item['_id']}",
                type="primary", use_container_width=True,
            ):
                update_content(item["_id"], status="KEEP")
                st.rerun()
            if b.button(
                "⏸️ 보류", key=f"hold-{item['_id']}", use_container_width=True,
            ):
                update_content(item["_id"], status="HOLD")
                st.rerun()
            c, d = st.columns(2)
            if c.button(
                "🚫 무시", key=f"ignore-{item['_id']}", use_container_width=True,
            ):
                update_content(item["_id"], status="IGNORE")
                st.rerun()
            if d.button(
                "🔄 새 항목", key=f"new-{item['_id']}", use_container_width=True,
            ):
                update_content(item["_id"], status="NEW")
                st.rerun()
            if st.button(
                "📤 발행함", key=f"posted-{item['_id']}", use_container_width=True,
            ):
                update_content(item["_id"], postedAt=datetime.now(timezone.utc))
                st.rerun()

            note_key = f"note-{item['_id']}"
            note_value = st.text_input(
                "발행 메모",
                value=item.get("note") or "",
                key=note_key,
                placeholder="트윗에 쓸 한 줄 / 채택 이유",
            )
            if st.button("메모 저장", key=f"save-note-{item['_id']}"):
                update_content(item["_id"], note=note_value.strip())
                st.rerun()

            st.divider()
            st.caption(metric_caption(item))
            if item.get("summary"):
                st.write(item["summary"][:500])
            if url:
                st.link_button("원문 열기", url, use_container_width=True)

st.divider()
if visible_count < len(items):
    st.button(
        f"더 보기 (+{min(CHUNK_SIZE, len(items) - visible_count)}개)",
        key="load-more", on_click=load_more, use_container_width=True,
    )
else:
    st.caption(f"전체 {len(items)}건 모두 표시했습니다.")
