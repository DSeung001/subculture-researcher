# Working rules

Setup and commands: [README.md](README.md). Sources and collection policy: [source.md](source.md).

## Product model

- The organizing unit is the **work / IP** (anime, games). Collect product, pre-order and event info per work and plan intro posts around it. Product category, information type, tag and timing are secondary facets.
- Works, aliases and each facet live in separate tables. A collab item links to several works; unclassified items are allowed.
- Keyword matches (work name + aliases against `title`/`titleKo`) can auto-add `item_works` links via `auto_assign_works` / sync / the web 「자동 연결」 buttons. Matching is additive only and never removes user unlinks of a different work. Unmatched items stay unclassified. The 작품·기획 screens expose works and product categories only; information types, tags, saved filters and per-item collection order/notes were removed from the UI (their tables and rows are kept).
- Do not decide that two listings are the same product or merge products across shops. Keep one item per source; support saved filters and hand-edited planning collections instead.

## Code layout

- Code lives in `subculture/`, grouped by bounded context: `collection` (수집), `library` (작품·기획, local DB), `drafts` (글), plus `shared` (kernel: content vocabulary, image/URL rules, presentation, Firestore client, paths) and `web` (Flask app, templates, static). Each context has `domain` (pure rules, no I/O), `application` (use cases), `infrastructure` (Firestore, SQLAlchemy, HTTP, Gemini) and `interface` (CLI entry code, blueprints).
- Dependencies point inward: `domain` imports no I/O library or outer layer; `infrastructure` never imports `application`/`interface`; `library` imports no other context; `collection` may only call `library.application` (post-collection sync); `drafts` may only use `library`; `shared` imports no context; only `web` imports `web`. `interface` modules (CLIs, screens) may compose contexts. `tests/test_architecture.py` enforces this.
- Root scripts (`app.py`, `collect.py`, `collect_manual.py`, `draft.py`, `sync_library.py`, `prune_library.py`, `migrate_library.py`, `seed_works.py`, `export_images.py`, `delete_firestore_drafts.py`, `delete_untitled_x.py`) are thin wrappers that only call the `main()` in `subculture/*/interface` (or `application/seed_works.py`); keep commands and options unchanged. `migrations/`, `postgres_migrations/` and `alembic.ini` stay at the root because applied revisions import `migrations.schema_v2`.

## Data and change rules

- Collection path: `subculture/collection/sources.yaml → collectors → ContentStore → Firestore` (collectors in `subculture/collection/infrastructure/collectors/`). Automatic runs use `collect.py`; YouTube sources use `collect_manual.py`. Add sources through existing config and shared extractors; write a dedicated collector only when those are insufficient.
- Collectors and manual entry go through `ContentStore` for URL dedup. Share one URL index per collection run and preserve user-edited values on re-collection.
- Use `subculture/shared/content_model.py` for remote categories, statuses, angles, tiers and references. An item ID is `STORAGE_CATEGORY:document_id` from the stored path; never recompute it from the editable category. Keep existing document IDs and CLI/UI behavior.
- Local curation is a one-way `Firestore → local DB` sync. It refreshes source metadata only and preserves local work links, product categories and collections. Sync never deletes items missing remotely; only the explicitly run `prune_library.py` removes such items, and only those with no local work links, collection membership or draft use (backup first; the automatic 피규어 category does not count as local work). There is no shared modified-time field, so sync currently reads everything.
- Local models are SQLAlchemy ORM in `subculture/library/infrastructure/models.py`; schema history is Alembic. A schema change needs a new revision plus a data-preservation test. Never edit an applied revision or a frozen schema (`migrations/schema_v2.py`).
- The default local DB is PostgreSQL from `compose.yaml` (`DATABASE_URL` or `POSTGRES_*` in `.env`), with its own chain in `postgres_migrations/`. A SQLite file (`--db`, tests) is the legacy backend with the chain in `migrations/`.
- Only a brand-new SQLite file is initialized automatically. Every other database is upgraded explicitly with `migrate_library.py upgrade` (via `docker compose run --rm tools` for PostgreSQL) after stopping the app and sync; it takes a backup first (`.bak` copy for SQLite, `pg_dump` into `.local/backups` for PostgreSQL). No migrations during request handling, no `create_all`, no forced `stamp`. Document any new schema or Firestore index requirement.

## Drafts and AI

- Drafts live only in the local library (`drafts`, `draft_items`), never in Firestore. All draft creation goes through `create_draft` in `subculture/drafts/application/drafts.py`. Score-ranked AI drafts
  use `create_trending_draft` (local `collect.py` / default `draft.py` / 「AI로 글 만들기」) over the locally synced items; the cloud run (GitHub Actions) creates none. Local IP-grouped drafts use confirmed `item_works` links only
  (`draft.py --by-work` / 「작품별로 글 만들기」), including links created by keyword
  auto-assign; unlinked items are never used as sources for IP drafts. Selecting items on 작품·기획 makes a draft directly (`POST /library/drafts`, quick body or AI body).
- A draft is two posts: the body (product facts, no URLs; `drafts.body`) and the reply (`상품 페이지 참고 ↓` plus a short name and URL per source; `drafts.reply_body`). Both creation paths fill both. The LLM returns JSON (`post1`, and a `display_name` per numbered source) and never sees or writes a URL; the reply is assembled in code from each source's own `url` (`drafts/domain/posts.py`), and a source the model skipped keeps its link under a name cleaned from its title. Preorder vs regular sale reaches the model as a code-derived `판매유형` line, not as a guess from text.
- A draft takes 1–20 distinct sources. The same source set and post format is a duplicate regardless of order or publish state. Never reuse an already-published source for `NEWS`.
- Sources are read from the local `items` copy; ones not synced yet are fetched from Firestore in one bulk read and matched by ID (never assume `get_all` returns input order). Publishing marks the draft locally first, then writes `postedAt` on the source documents in Firestore; a failed Firestore write only warns. `draft_items.item_id` has no foreign key, and sources of a draft are never pruned.
- Use the LLM only to pick candidates and write new drafts. Discuss with the user before extending it to translation, auto-classification or editing existing posts.

## Scope and operations

- Collect metadata and links only, never full copyrighted articles. HTML collection checks robots.txt and is skipped if the check fails. The only exception is `local_only` `local_browser` sources (Naver stores) run by hand through `collect_manual.py`: headed, private Playwright context, list pages only, no bypass of challenges; `collect.py` never runs them. Do not add X scraping or community/VOC sources, or YouTube channels that upload the anime episodes themselves (KADOKAWA Anime, Aniplex and TOHO animation were removed).
- The Flask UI is local-only on `127.0.0.1:5001`. Do not add auth, extra backends, vector DBs or new schedulers unless asked.
- Never commit credentials, `.env`, browser profiles, local DBs or backups, or test dependencies.

## Verification

- Behavior changes need offline regression tests. Do not run real collection or AI calls just to verify.
- Run `python -m unittest discover -s tests -v` before delivery. Use `.\.venv\Scripts\python.exe` on Windows when the venv is not activated.
