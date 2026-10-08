# Working rules

Setup and commands: [README.md](README.md). Sources and collection policy: [source.md](source.md).

## Product model

- The organizing unit is the **work / IP** (anime, games). Collect product, pre-order and event info and show it grouped per work.
- Works and their aliases live in `subculture/library/work_catalog.yaml`. An item belongs to every work whose name or alias appears in its `title`/`titleKo` (`compile_works` / `match_works` in `subculture/library/domain/keywords.py`); a collab item matches several works and an unmatched item stays unclassified.
- Work links are computed when the static site is built and are never stored. There are no hand-made links or unlinks: fix a classification by editing the catalog.
- Do not decide that two listings are the same product or merge products across shops. Keep one item per source.

## Code layout

- Code lives in `subculture/`: `collection` (수집; layers `domain`, `application`, `infrastructure`, `interface`), `library` (작품·IP catalog; `domain` matching rules and `application` YAML loader only), `shared` (kernel: content vocabulary, image/URL rules, presentation, Firestore client, paths) and `web` (local Flask app, static site builder, templates, static).
- Dependencies point inward: `domain` imports no I/O library or outer layer; `infrastructure` never imports `application`/`interface`; `collection` and `library` do not import each other below the interface layer; `shared` imports no context; only `web` imports `web`. `web` and `interface` modules compose contexts. `tests/test_architecture.py` enforces this.
- Follow SOLID when adding or changing classes/modules: single responsibility per class, extend behavior without editing stable code (open/closed), keep subtypes substitutable for their base, split interfaces so callers depend only on what they use, and depend on abstractions (the layer boundaries above) rather than concrete infrastructure.
- Root scripts (`app.py`, `build_site.py`, `collect.py`, `collect_manual.py`, `delete_untitled_x.py`) are thin wrappers that only call a `main()` in `subculture/collection/interface` or `subculture/web`; keep commands and options unchanged.

## Data and change rules

- Collection path: `subculture/collection/sources.yaml → collectors → ContentStore → Firestore` (collectors in `subculture/collection/infrastructure/collectors/`). Automatic runs use `collect.py`; `local_only` browser sources use `collect_manual.py`. Add sources through existing config and shared extractors; write a dedicated collector only when those are insufficient.
- Collectors and manual entry go through `ContentStore` for URL dedup. Share one URL index per collection run and preserve user-edited values on re-collection.
- Use `subculture/shared/content_model.py` for remote categories, statuses, angles, tiers and references. An item ID is `STORAGE_CATEGORY:document_id` from the stored path; never recompute it from the editable category. Keep existing document IDs and CLI/UI behavior.
- Firestore is the only store. There is no local database: do not add one (or a sync, migrations, drafts) unless asked. Document any new Firestore index requirement.

## Static site

- Publishing path: `Firestore → build_site.py (subculture/web/site_builder.py) → site/ → GitHub Pages` (`.github/workflows/pages.yml`, after every `Collect sources` run and on manual dispatch).
- The page is read-only and never talks to Firestore. No credential, Firebase web config or write path may reach the built files; the service account key exists only as the `FIREBASE_KEY` Actions secret and the local `firebase-key.json`.
- Card fields are computed in Python by `shared/presentation.card_view` (shared with the inbox) and shipped in `data.json`; `web/site/site.js` only filters, sorts and renders. Do not re-implement scoring or labels in JavaScript, and keep its card markup in step with `templates/_item_card.html`.
- Items with status `IGNORE` are left out of the build. Asset paths stay relative (the site is served under `/<repo>/`).
- A build reads every document once; there is no shared modified-time field for an incremental read.

## Scope and operations

- Collect metadata and links only, never full copyrighted articles. HTML collection checks robots.txt and is skipped if the check fails. The only exception is `local_only` `local_browser` sources (Naver stores) run by hand through `collect_manual.py`: headed, private Playwright context, list pages only, no bypass of challenges; `collect.py` never runs them. Do not add X scraping or community/VOC sources, or YouTube channels that upload the anime episodes themselves. Anime sources AniList and PR TIMES 만화·애니, the `anilist`/`youtube_feed` collectors and AniList-metric scoring were removed; existing `ANIME` documents stay. 애니플러스 뉴스 is collected again as the only `ANIME` source (list links, dates and photos, no metrics).
- The Flask UI (inbox: status, publish mark, note, manual add; source list) is local-only on `127.0.0.1:5001` and is never deployed. Do not add auth, extra backends, vector DBs or new schedulers unless asked.
- No LLM is used. Discuss with the user before adding one (drafts, LLM translation, auto-classification).
- Never commit credentials, `.env`, `firebase-key.json`, browser profiles, the built `site/` or test dependencies. The repository and the deployed site are public.

## Verification

- Behavior changes need offline regression tests. Do not run real collection or a real site build just to verify.
- Run `python -m unittest discover -s tests -v` before delivery. Use `.\.venv\Scripts\python.exe` on Windows when the venv is not activated.
