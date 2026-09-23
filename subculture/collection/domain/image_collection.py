"""Whether a sources.yaml entry can fill imageUrl / detailImageUrls (config only, no I/O)."""

# Collectors that always set a main photo without a yaml image selector.
_BUILTIN_MAIN_TYPES = frozenset({"figurefarm"})


def image_collection_flags(source: dict) -> dict[str, bool]:
    """Return `main` (imageUrl) and `detail` (detailImageUrls) collection capability."""
    source = source or {}
    main = bool(
        source.get("list_image_selector")
        or source.get("fetch_detail_image")
        or source.get("image_selector")
        or source.get("image_field")
        or source.get("image_html_field")
        or source.get("product_mode")
        or source.get("type") in _BUILTIN_MAIN_TYPES
    )
    detail = bool(source.get("detail_images_selector"))
    return {"main": main, "detail": detail}
