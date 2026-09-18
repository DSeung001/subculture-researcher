# Architecture and data contracts

Working rules: [AGENTS.md](AGENTS.md). Setup: [README.md](README.md).
Source policy: [source.md](source.md).

## Flow and ownership

`sources.yaml → collectors → ContentStore → Firestore → Flask/Jinja review UI`

The Firebase Admin SDK runs server-side. `python app.py` serves the
unauthenticated review UI locally on `127.0.0.1:5001`.

| Module | Responsibility |
|---|---|
| `sources_config.py` | Shared source configuration loading |
| `content_model.py` | Allowed categories/statuses/angles/tiers and stable references |
| `collectors/common.py` | Metadata defaults, product extraction, save/error accounting |
| `content_store.py` | Canonical URLs, legacy deduplication, create/update rules |
| `translate.py` | Optional MyMemory title/summary translation with quota guards |
| `presentation.py` | Display helpers, dates, ranking and product captions |
| `drafts_store.py` | Draft validation, bulk source reads, persistence and publishing |
| `ai_drafts.py` | Shared candidate selection and draft orchestration |
| `ai_writer.py` | Gemini selection/writing prompts, throttling and retries |
| `app.py`, `collect.py`, `draft.py` | UI and CLI entry points |

## Content storage

Path: `categories/{STORAGE_CATEGORY}/contents/{sha256(canonical_url)}`.
Legacy documents keep their IDs. A category field edit does not move the document.
Use `content_id(snapshot)` for source IDs/cursors and `content_ref(db, source_id)`
for lookups; the ID format is `STORAGE_CATEGORY:document_id`.

Core fields: `url`, `title`, `summary`, `source`, `sourceType`, `sourceUrl`,
`region`, `category`, `contentAngle`, `sourceTier`, `note`, `status`,
`publishedAt`, `postedAt`, `collectedAt`, `createdAt`.

Optional fields:

- Translation: `titleKo`, `summaryKo`, `sourceLanguage`, `translatedAt`.
  Korean-majority text needs no translation; display falls back to originals.
- Engagement: `viewCount`, `likeCount`, each with its `CheckedAt` timestamp.
- AniList signals: `SIGNAL_FIELDS` in `content_store.py`.
- Products: `PRODUCT_FIELDS` in `content_store.py` (shop, sale status, price,
  currency, preorder deadline, release window, manufacturer, size, image).

`ContentStore` loads an index of existing URLs once per run, shares it across
collectors, and preserves editorial fields on recollection. Only metrics/signals/
product metadata are refreshed on existing documents. Manual submissions refresh
the index. Dry runs never connect to Firestore or translate content.

The inbox reads a category's storage shard or the `contents` collection group,
ordered by `collectedAt`, then filters/sorts each page locally. A collection-group
ordering index may be needed; Firestore supplies a creation link on failure.

## Drafts

Path: `drafts/{autoId}`. Fields: `sourceIds`, `angle`, `body`, `status`,
`postedAt`, `createdAt`, `updatedAt`. Status is `DRAFT` or `POSTED`.

- Accept 1–20 distinct source IDs and preserve selection order.
- Reject the same source-ID set and angle, regardless of order or draft status.
  Duplicate lookup projects only source IDs from drafts matching the angle.
- `NEWS` cannot use already-posted sources; other angles can reuse them.
- `create_draft` loads sources in one bulk read and validates before invoking an
  optional `body_factory(items, angle)`. Manual bodies and generated bodies share
  this path. Missing sources or generation failures do not save a draft.
- Draft lists share the same bulk loader and display placeholders for missing
  sources. Publishing fills source `postedAt` only when empty.

## AI draft flow

`collect.py` (unless `--dry-run`/`--no-ai-draft`), `draft.py`, and `POST /drafts/ai`
all use `create_trending_draft`. CLI messages are shared by `run_trending_draft`.

1. Read a bounded candidate set (`CANDIDATE_LIMIT`), exclude ignored/posted items,
   optionally filter category, then rank by `presentation.content_score`.
   Ranking boosts domestic items, official sources, AniList/engagement signals,
   and product preorders/limited runs.
2. Gemini selects from the score-ranked pool using original titles and structured
   product captions. Missing keys or failed/unparseable selection fall back to
   score order.
3. Validate chosen sources and duplicate rules, then generate the Korean body
   from freshly loaded sources. Duplicate drafts skip the body-writing call.
4. Append real source titles/URLs locally. The model must not invent facts/links;
   category hints and product captions guide its writing.

`GEMINI_API_KEY` comes from local `.env` or an Actions secret. Missing/invalid keys
raise `AiWriterError`; callers report the failure without failing collection.
Request spacing, bounded retries and quota guards live in `ai_writer.py`.

## Current limits

- Candidate ranking covers the bounded query result, not the whole database.
- Inbox category filters read storage shards; editing category does not migrate
  a document between shards.
- Duplicate draft detection and draft/source publishing are not transactions.
  Parallel writes can race; no cross-process uniqueness guarantee is claimed.

Offline regression tests: `python -m unittest discover -s tests -v`.
