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

## Firestore collection

`contents/{sha256(url)}`

Expected fields:

- `url`
- `title`
- `summary`
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

## Allowed categories

- `ANIME`
- `CHARACTER`
- `FIGURE`
- `GOODS`
- `COLLECTION`
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

`note` is a short editorial memo for the combined X account. `postedAt` is set when the item has been published manually.

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
