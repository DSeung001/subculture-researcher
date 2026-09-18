# Repository working rules

This is a small, local-only research inbox for choosing 2–4 X post ideas a day.
Read [agent.md](agent.md) for architecture, [README.md](README.md) for commands,
and [source.md](source.md) for source policy.

## Change discipline

- Preserve behavior and URL deduplication; prefer measurable reductions in
  network calls and repeated logic over new infrastructure.
- Use `content_model.py` for categories, statuses, angles, tiers, and references.
  Derive identity from the stored path, never the editable category field.
- Route collector/manual writes through `ContentStore` and all draft creation
  through `create_draft`. Keep source-specific collectors only when configuration
  and existing helpers are insufficient.
- Validate drafts before expensive AI body generation. Reuse bulk source reads;
  Firestore `get_all` result order is not guaranteed.
- Keep CLI/UI behavior and legacy document IDs compatible. Document new schema
  or index requirements; avoid silently migrating existing data.
- Add focused offline regression tests for behavioral changes. Run
  `python -m unittest discover -s tests -v` before delivery. Do not use real
  collection or AI calls merely to test a refactor.

## Product boundaries

- Collect metadata and links, never full copyrighted articles. Respect robots.txt
  for HTML collection. Do not add X scraping or community/forum (VOC) sources.
- Keep the Flask review UI local. Do not add authentication, another backend,
  vector databases, or schedulers without a demonstrated need.
- LLM use is limited to selecting candidates and writing new drafts. Discuss
  expansion into translation, classification, or editing existing content first.
- Never commit credentials, `.env`, browser profiles, or local test dependencies.
