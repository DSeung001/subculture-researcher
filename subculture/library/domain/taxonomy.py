"""Which classifications the screens offer."""


# What the screens offer. information_types and tags stay in the database (their tables and any
# rows are kept) but nothing links to them any more, so they are not shown or accepted.
TAXONOMIES = {
    "works": "작품·IP",
    "product_categories": "제품 카테고리",
}
FILTER_KEYS = (*TAXONOMIES, "q", "unclassified", "deadline_from", "deadline_to")
