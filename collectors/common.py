from content_store import ContentStore


def metadata(source: dict, **fields) -> dict:
    return {
        "summary": "", "source": source["name"], "sourceType": source["type"],
        "sourceUrl": source["url"], "region": source.get("region"),
        "category": source.get("category", "UNKNOWN"),
        "contentAngle": source.get("content_angle", "NEWS"),
        "publishedAt": None, **fields,
    }


class RobotsDenied(RuntimeError):
    pass


def save_records(records, db, source: dict, store: ContentStore | None = None) -> dict:
    store = store if store is not None else ContentStore(db)
    result = dict(processed=0, inserted=0, existing=0, updated=0, failed=0, skipped=0, reason="")
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
                print(f"[항목 오류] {source['name']} {item.get('url')}: {'; '.join(errors)}")
    except RobotsDenied as exc:
        result.update(skipped=1, reason=str(exc))
    except Exception as exc:
        result["failed"] += 1
        result["reason"] = str(exc)
        print(f"[오류] {source['name']}: {exc}")
    finally:
        close = getattr(records, "close", None)
        if close:
            close()
    return result
