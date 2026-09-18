import streamlit as st
from firebase_admin import firestore

from firebase_client import get_db
from content_store import add_manual_content
from presentation import metric_caption


CATEGORIES = ["ANIME", "CHARACTER", "FIGURE", "GOODS", "COLLECTION", "UNKNOWN"]
STATUSES = ["NEW", "KEEP", "HOLD", "IGNORE"]
ANGLES = ["NEWS", "COMPARE", "SIZE", "PRICE", "QUESTION", "GUIDE", "COLLECTION"]

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


@st.cache_resource
def db():
    return get_db()


def update_content(document_id: str, **fields):
    db().collection("contents").document(document_id).update(fields)


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
        submitted = st.form_submit_button("저장")

    if submitted:
        if not url.strip():
            st.error("URL을 입력해주세요.")
        else:
            try:
                created = add_manual_content(db(), url, title, category, angle)
            except ValueError as exc:
                st.error(str(exc))
            else:
                if created:
                    st.success("저장했습니다.")
                    st.rerun()
                else:
                    st.info("이미 저장된 URL입니다.")

    st.divider()
    st.header("필터")
    category_filter = st.selectbox(
        "카테고리",
        ["ALL"] + CATEGORIES,
        format_func=lambda value: "전체" if value == "ALL" else CATEGORY_LABELS[value],
    )
    status_filter = st.selectbox(
        "상태",
        ["ACTIVE"] + STATUSES,
        format_func=lambda value: (
            "무시 제외 전체" if value == "ACTIVE" else STATUS_LABELS[value]
        ),
    )
    limit = st.slider("불러올 개수", min_value=20, max_value=200, value=50, step=10)

query = (
    db()
    .collection("contents")
    .order_by("collectedAt", direction=firestore.Query.DESCENDING)
    .limit(limit)
)

docs = list(query.stream())

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

    items.append(item)

c1, c2, c3 = st.columns(3)
c1.metric("불러온 항목", len(docs))
c2.metric("현재 표시", len(items))
c3.metric("새 항목", sum(1 for item in items if item.get("status") == "NEW"))

for item in items:
    st.subheader(item.get("title") or "(제목 없음)")

    category_value = item.get("category", "UNKNOWN")
    angle_value = item.get("contentAngle", "NEWS")
    status_value = item.get("status", "NEW")

    meta = " · ".join(
        value
        for value in [
            item.get("source"),
            CATEGORY_LABELS.get(category_value, category_value),
            ANGLE_LABELS.get(angle_value, angle_value),
            STATUS_LABELS.get(status_value, status_value),
        ]
        if value
    )
    st.caption(meta)
    st.caption(metric_caption(item))

    summary = item.get("summary")
    if summary:
        st.write(summary[:500])

    url = item.get("url")
    if url:
        st.link_button("원문 열기", url)

    a, b, c, d = st.columns(4)

    if a.button("채택", key=f"keep-{item['_id']}", use_container_width=True):
        update_content(item["_id"], status="KEEP")
        st.rerun()

    if b.button("보류", key=f"hold-{item['_id']}", use_container_width=True):
        update_content(item["_id"], status="HOLD")
        st.rerun()

    if c.button("무시", key=f"ignore-{item['_id']}", use_container_width=True):
        update_content(item["_id"], status="IGNORE")
        st.rerun()

    if d.button("새 항목으로", key=f"new-{item['_id']}", use_container_width=True):
        update_content(item["_id"], status="NEW")
        st.rerun()

    st.divider()
