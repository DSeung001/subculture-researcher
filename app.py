import hashlib
from datetime import datetime, timezone

import streamlit as st
from firebase_admin import firestore

from firebase_client import get_db


CATEGORIES = ["ANIME", "CHARACTER", "FIGURE", "GOODS", "COLLECTION", "UNKNOWN"]
STATUSES = ["NEW", "KEEP", "HOLD", "IGNORE"]
ANGLES = ["NEWS", "COMPARE", "SIZE", "PRICE", "QUESTION", "GUIDE", "COLLECTION"]


@st.cache_resource
def db():
    return get_db()


def doc_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def add_manual_content(url: str, title: str, category: str, angle: str):
    ref = db().collection("contents").document(doc_id(url.strip()))
    if ref.get().exists:
        return False

    ref.set(
        {
            "url": url.strip(),
            "title": title.strip() or "(untitled)",
            "summary": "",
            "source": "manual",
            "sourceType": "manual",
            "category": category,
            "contentAngle": angle,
            "status": "NEW",
            "publishedAt": None,
            "collectedAt": firestore.SERVER_TIMESTAMP,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
    )
    return True


def update_content(document_id: str, **fields):
    db().collection("contents").document(document_id).update(fields)


st.set_page_config(page_title="Subculture Researcher", layout="wide")
st.title("Subculture Researcher")
st.caption("Anime · Figure · Goods · Collection research inbox")

with st.sidebar:
    st.header("Add content")
    with st.form("manual-add", clear_on_submit=True):
        url = st.text_input("URL")
        title = st.text_input("Title")
        category = st.selectbox("Category", CATEGORIES)
        angle = st.selectbox("Angle", ANGLES)
        submitted = st.form_submit_button("Save")

    if submitted:
        if not url.strip():
            st.error("URL is required.")
        else:
            created = add_manual_content(url, title, category, angle)
            if created:
                st.success("Saved.")
                st.rerun()
            else:
                st.info("Already collected.")

    st.divider()
    st.header("Filters")
    category_filter = st.selectbox("Category filter", ["ALL"] + CATEGORIES)
    status_filter = st.selectbox("Status filter", ["ACTIVE"] + STATUSES)
    limit = st.slider("Load", min_value=20, max_value=200, value=50, step=10)

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
c1.metric("Loaded", len(docs))
c2.metric("Visible", len(items))
c3.metric("New", sum(1 for item in items if item.get("status") == "NEW"))

for item in items:
    st.subheader(item.get("title") or "(untitled)")

    meta = " · ".join(
        value
        for value in [
            item.get("source"),
            item.get("category"),
            item.get("contentAngle"),
            item.get("status"),
        ]
        if value
    )
    st.caption(meta)

    summary = item.get("summary")
    if summary:
        st.write(summary[:500])

    url = item.get("url")
    if url:
        st.link_button("Open source", url)

    a, b, c, d = st.columns(4)

    if a.button("KEEP", key=f"keep-{item['_id']}", use_container_width=True):
        update_content(item["_id"], status="KEEP")
        st.rerun()

    if b.button("HOLD", key=f"hold-{item['_id']}", use_container_width=True):
        update_content(item["_id"], status="HOLD")
        st.rerun()

    if c.button("IGNORE", key=f"ignore-{item['_id']}", use_container_width=True):
        update_content(item["_id"], status="IGNORE")
        st.rerun()

    if d.button("NEW", key=f"new-{item['_id']}", use_container_width=True):
        update_content(item["_id"], status="NEW")
        st.rerun()

    st.divider()
