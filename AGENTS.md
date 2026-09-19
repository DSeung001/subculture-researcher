# Working rules

Setup and commands: [README.md](README.md). Sources and collection policy: [source.md](source.md).

## Product model

- The organizing unit is the **work / IP** (anime, games). Collect product, pre-order and event info per work and plan intro posts around it. Product category, information type, tag and timing are secondary facets.
- Works, aliases and each facet live in separate tables. A collab item links to several works; unclassified items are allowed.
- Keyword matches (work name + aliases against `title`/`titleKo`) can auto-add `item_works` links via `auto_assign_works` / sync / the web 「자동 연결」 buttons. Matching is additive only and never removes user unlinks of a different work. Unmatched items stay unclassified; the list UI may still show suggestion chips for unclassified rows.
- Do not decide that two listings are the same product or merge products across shops. Keep one item per source; support saved filters and hand-edited planning collections instead.

## Data and change rules

- Collection path: `sources.yaml → collectors → ContentStore → Firestore`. Automatic runs use `collect.py`; YouTube sources use `collect_manual.py`. Add sources through existing config and shared extractors; write a dedicated collector only when those are insufficient.
- Collectors and manual entry go through `ContentStore` for URL dedup. Share one URL index per collection run and preserve user-edited values on re-collection.
- Use `content_model.py` for remote categories, statuses, angles, tiers and references. An item ID is `STORAGE_CATEGORY:document_id` from the stored path; never recompute it from the editable category. Keep existing document IDs and CLI/UI behavior.
- Local curation is a one-way `Firestore → local DB` sync. It refreshes source metadata only and preserves local work links, tags, notes and collections. Sync never deletes items missing remotely; only the explicitly run `prune_library.py` removes such items, and only those with no local work links, tags, categories or collection membership (backup first). There is no shared modified-time field, so sync currently reads everything.
- Local models are SQLAlchemy ORM in `library_models.py`; schema history is Alembic. A schema change needs a new revision plus a data-preservation test. Never edit an applied revision or a frozen schema (`migrations/schema_v2.py`).
- The default local DB is PostgreSQL from `compose.yaml` (`DATABASE_URL` or `POSTGRES_*` in `.env`), with its own chain in `postgres_migrations/`. A SQLite file (`--db`, tests) is the legacy backend with the chain in `migrations/`.
- Only a brand-new SQLite file is initialized automatically. Every other database is upgraded explicitly with `migrate_library.py upgrade` (via `docker compose run --rm tools` for PostgreSQL) after stopping the app and sync; it takes a backup first (`.bak` copy for SQLite, `pg_dump` into `.local/backups` for PostgreSQL). No migrations during request handling, no `create_all`, no forced `stamp`. Document any new schema or Firestore index requirement.

## Drafts and AI

- Drafts live only in the local library (`drafts`, `draft_items`), never in Firestore. All draft creation goes through `create_draft` in `drafts_store.py`. Score-ranked AI drafts
  use `create_trending_draft` (local `collect.py` / default `draft.py` / 「AI로 글 만들기」) over the locally synced items; the cloud run (GitHub Actions) creates none. Local IP-grouped drafts use confirmed `item_works` links only
  (`draft.py --by-work` / 「작품별로 글 만들기」), including links created by keyword
  auto-assign; unmatched suggestion chips alone are never used as draft sources.
- A draft takes 1–20 distinct sources. The same source set and post format is a duplicate regardless of order or publish state. Never reuse an already-published source for `NEWS`.
- Sources are read from the local `items` copy; ones not synced yet are fetched from Firestore in one bulk read and matched by ID (never assume `get_all` returns input order). Publishing marks the draft locally first, then writes `postedAt` on the source documents in Firestore; a failed Firestore write only warns. `draft_items.item_id` has no foreign key, and sources of a draft are never pruned.
- Use the LLM only to pick candidates and write new drafts. Discuss with the user before extending it to translation, auto-classification or editing existing posts.

## Scope and operations

- Collect metadata and links only, never full copyrighted articles. HTML collection checks robots.txt and is skipped if the check fails. Do not add X scraping or community/VOC sources.
- The Flask UI is local-only on `127.0.0.1:5001`. Do not add auth, extra backends, vector DBs or new schedulers unless asked.
- Never commit credentials, `.env`, browser profiles, local DBs or backups, or test dependencies.

## Verification

- Behavior changes need offline regression tests. Do not run real collection or AI calls just to verify.
- Run `python -m unittest discover -s tests -v` before delivery. Use `.\.venv\Scripts\python.exe` on Windows when the venv is not activated.
