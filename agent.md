# Agent Context

## Project purpose

Subculture Researcher is a small personal research inbox for discovering content ideas before publishing them on X and later connecting successful topics to FiguRoom.

The system should remain intentionally simple.

## Architecture

```
Sources
  -> Python collectors
  -> Firestore
  -> Flask review UI (server-rendered Jinja2 templates)
```

The review UI (`app.py`) is a local-only Flask app run with `python app.py`, using
the Firebase Admin SDK on the server side (same service-account credentials as
`collect.py`). It is not authenticated or deployed publicly — run it on your
own machine only. There is no separate backend API beyond this review app.

## Core workflow

1. Collect metadata from configured sources.
2. Store one Firestore document per canonical URL.
3. Review items in the Flask app.
4. Mark each item as `NEW`, `KEEP`, `HOLD`, or `IGNORE`.
5. Manually save X URLs when useful.
6. Bundle one or more inbox items into a draft and review it on the drafts tab.

## Firestore collections

Content is split into one Firestore collection per category, each nested under a
`categories` shard document:

`categories/{CATEGORY}/contents/{sha256(url)}`

A document keeps living in the category collection it was first saved under, even if
its `category` field is edited later — moving it would change its document path.
The review UI reads a single category with `categories/{CATEGORY}/contents`, and reads
across every category at once with a Firestore `collection_group("contents")` query
(same `collectedAt` ordering and pagination either way). The `collection_group` query
needs a one-time Firestore composite index for `collectedAt`; the first time it runs,
the Firestore client error includes a direct link to create it.

Expected fields:

- `url`
- `title`
- `titleKo`
- `summary`
- `summaryKo`
- `sourceLanguage`
- `translatedAt`
- `source`
- `sourceType`
- `sourceUrl`
- `region`
- `category`
- `contentAngle`
- `sourceTier`
- `note`
- `status`
- `publishedAt`
- `postedAt`
- `collectedAt`
- `createdAt`

`titleKo` and `summaryKo` are Korean translations of foreign titles/summaries from the free MyMemory API. Hangul-majority text is stored as-is. Article bodies are never stored.

## Allowed categories

- `ANIME`
- `CHARACTER`
- `FIGURE`
- `GOODS`
- `COLLECTION`
- `FESTIVAL` — anime/figure/goods conventions and fan festivals (AGF, Comiket, Wonder Festival, etc.)
- `UNKNOWN`

## Allowed content angles

- `NEWS`
- `COMPARE`
- `SIZE`
- `PRICE`
- `QUESTION`
- `GUIDE`
- `COLLECTION`

## Allowed source tiers

- `OFFICIAL` — manufacturer / official announcements
- `MEDIA` — news hubs and retailer media

User-community/forum sources (VOC) are out of scope by policy — only new
product, anime, and figure info resources are collected.

`note` is a short editorial memo for the combined X account. `postedAt` is set when the item has been published manually, or when a draft that uses it is marked posted (only if `postedAt` was empty).

## Firestore drafts

`drafts/{autoId}`

- `sourceIds` — one or more `"CATEGORY:sha256(url)"` strings, each identifying a document
  in `categories/{CATEGORY}/contents`
- `angle` — same allowed values as `contentAngle`
- `body` — assembled title/summary/URL/note text (no article body, no LLM)
- `status` — `DRAFT` or `POSTED`
- `postedAt`
- `createdAt`
- `updatedAt`

Duplicate rules:

- Reject a new draft when another draft already has the same `sourceIds` set and the same `angle`.
- `NEWS` drafts also reject any selected source that already has `postedAt`.
- Other angles may reuse posted sources. The drafts UI labels those sources as already used.
- Publishing a draft sets `contents.postedAt` only when that field is empty.

## Important constraints

- Do not add X scraping.
- Do not commit Firebase service account credentials.
- Keep collectors source-specific only when configuration is insufficient.
- Respect robots.txt for HTML collection.
- Store metadata and links, not full copyrighted articles.
- Prefer small incremental changes over infrastructure expansion.
- Do not add LLMs, vector databases, schedulers, authentication, or a backend server unless there is a demonstrated need.
- Preserve URL-based deduplication.

## Near-term product goal

The tool should make it possible to choose 2-4 strong X post candidates within a few minutes each day and later analyze which topic/content-angle combinations produce useful audience growth for FiguRoom.
