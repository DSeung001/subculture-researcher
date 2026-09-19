"""Translate stored foreign-language documents that never got a Korean title."""

from subculture.collection.infrastructure.translate import enrich_translation, needs_translation


def backfill_translations(db) -> None:
    processed = updated = skipped = failed = 0
    for snapshot in db.collection_group("contents").stream():
        processed += 1
        data = snapshot.to_dict() or {}
        if (data.get("titleKo") or "").strip():
            skipped += 1
            continue
        title = data.get("title") or ""
        summary = data.get("summary") or ""
        if not needs_translation(title) and not needs_translation(summary):
            skipped += 1
            continue
        fields = enrich_translation(data)
        if not (fields.get("titleKo") or fields.get("summaryKo")):
            failed += 1
            continue
        snapshot.reference.update(fields)
        updated += 1
        print(f"[번역] {title} -> {fields.get('titleKo') or fields.get('summaryKo')}")
    print(
        f"번역 보완 종료: processed={processed} updated={updated} "
        f"skipped={skipped} failed={failed}"
    )
