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
- `body` — either the mechanically assembled title/summary/URL/note text, or an
  AI-written draft (see below); never the article body itself
- `status` — `DRAFT` or `POSTED`
- `postedAt`
- `createdAt`
- `updatedAt`

Duplicate rules:

- Reject a new draft when another draft already has the same `sourceIds` set and the same `angle`.
- `NEWS` drafts also reject any selected source that already has `postedAt`.
- Other angles may reuse posted sources. The drafts UI labels those sources as already used.
- Publishing a draft sets `contents.postedAt` only when that field is empty.

## AI draft writing

`ai_drafts.py` takes the top-scoring (`presentation.content_score`, which now
also boosts `region == "KR"` items, and for any `entityType == "PRODUCT"` item
(figures today; any future product-type source too) boosts
`saleStatus == "PREORDER"` and titles matching `LIMITED_KEYWORDS`
(한정판/한정수량/限定, etc.) — preorders and limited runs are time-sensitive and
sell out, so they're worth surfacing over an always-available in-stock item)
unposted, non-`IGNORE` items across every category, and runs two Gemini Flash
(via the plain REST API — no SDK dependency) calls in `ai_writer.py`:

1. **Selection** (`select_top_items`) — from a pool of the
   `SELECTION_POOL_SIZE` highest-scoring candidates, the model picks the
   `DRAFT_SIZE` most likely to perform well on X, preferring `[국내]`
   (Korean-site) items, preordering/limited products, and, for anime, items
   with higher AniList trending/popularity/favourites/averageScore. Candidate
   titles are shown in their original (non-translated) form here. If there's
   no API key or the call fails/is unparseable, it silently falls back to the
   score-sorted order, so selection issues never block draft creation.
2. **Writing** (`write_draft_body`) — writes the Korean body for the selected
   items, formatted for X: a hooking first line, short line-broken sentences,
   at most one emoji, and 2-4 relevant hashtags on the last line. The prompt's
   emphasis line (`CATEGORY_HINTS`) varies by the draft's dominant category
   (ANIME/CHARACTER/FIGURE/GOODS/COLLECTION/FESTIVAL) — e.g. a FIGURE draft is
   nudged toward price/size/release info, a FESTIVAL draft toward date/venue.

Both prompts' material blocks include `presentation.product_caption(item)` for
any product item (shop/saleStatus/price/preorderEndAt/sizeText/etc.) so a
higher content_score from a preorder or limited run is backed by real
structured data in the prompt, not just whatever happens to be in the scraped
summary text — the score doesn't just rank candidates, it's the same signal
the model sees when picking and writing.

The model is told not to invent links or facts, and to cover every numbered
material in the body. After writing, `write_draft_body` appends a `출처`
block assembled locally from each item's real `url` / `titleKo` (never
model-generated). The same sources also appear as REF entries alongside the
draft in `templates/drafts.html`, so the post text stays copy-paste-ready for
X with grounded links and without hallucinated URLs.

This runs automatically at the end of every real (non-`--dry-run`,
non-`--no-ai-draft`) `collect.py` run, on demand via `python draft.py`
(optionally `--category`), and from the drafts page ("AI로 글 만들기" →
`POST /drafts/ai`). The two CLI entry points share `run_trending_draft`
(same one-line status messages); the Flask button calls
`create_trending_draft` directly for flash messages. All three paths use
the same selection/writing logic and `create_draft` duplicate checks, so a
repeat run over unchanged top items is a no-op rather than a duplicate draft.

`GEMINI_API_KEY` is read from the environment: a local `.env` file (loaded via
`python-dotenv`, gitignored) in development, the `GEMINI_API_KEY` repository
secret in the `collect.yml` GitHub Actions workflow. Missing or invalid keys
raise `AiWriterError`, which CLI callers catch via `run_trending_draft` and
the Flask handler catches for flash messages — neither fails the surrounding
collection run or request.

## Important constraints

- Do not add X scraping.
- Do not commit Firebase service account credentials.
- Keep collectors source-specific only when configuration is insufficient.
- Respect robots.txt for HTML collection.
- Store metadata and links, not full copyrighted articles.
- Prefer small incremental changes over infrastructure expansion.
- Do not add vector databases, additional schedulers, authentication, or a
  backend server beyond the existing Flask review app unless there is a
  demonstrated need. LLM usage is intentionally scoped to candidate selection
  and draft body writing within the AI draft flow (see "AI draft writing"
  above) — don't expand it into other features (auto-translation,
  auto-classification, editing existing content) without discussing it first.
- Preserve URL-based deduplication.

## Near-term product goal

The tool should make it possible to choose 2-4 strong X post candidates within a few minutes each day and later analyze which topic/content-angle combinations produce useful audience growth for FiguRoom.
