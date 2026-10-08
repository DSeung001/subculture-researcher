---
name: audit-ip-matching
description: Find missing work/IP classifications in subculture-researcher and repair its YAML catalog. Use for 미분류 IP, 빠진 작품, 누락된 별칭, or IP 매칭 보강 requests.
---

# Audit IP matching

Follow repository AGENTS.md. Classification is computed from `title` and `titleKo` by `compile_works` / `match_works`; never persist links or edit documents to force a match.

## Inspect

From the repository root, use the project Python environment:

```bash
.venv/bin/python .agents/skills/audit-ip-matching/scripts/audit_ip.py --firestore > /tmp/ip-before.json
```

The helper reads non-IGNORE documents once without collection or a site build. If credentials/network access are unavailable, use deployed public `data.json` or an existing site snapshot:

```bash
.venv/bin/python .agents/skills/audit-ip-matching/scripts/audit_ip.py --site-data /tmp/public-data.json > /tmp/ip-before.json
```

Check and report `builtAt` for site data. Recompute matches with the current catalog; stored `works` may be stale. Site `view.original_title` / `view.title_text` are original/display titles. Do not match source names, summaries or URLs. Keep temporary metadata reports out of commits; they are audit artifacts, not a local store.

## Repair

Group missing titles by work/source. Search `subculture/library/work_catalog.yaml` first; add spelling, spacing and language aliases to existing canonical entries. Add new works when a title explicitly identifies a work or named character/model series. Manufacturers, shops, general event notices and generic original illustrations need not have an IP.

Verify uncertain abbreviations or character-only titles with official publishers, developers or manufacturers. Leave ambiguous names unclassified. Aliases apply globally, so prefer distinctive names over common character names, ordinary nouns or broad franchise guesses. Do not introduce LLM classification or alter matching semantics to fix a catalog gap.

Preserve YAML comments/formatting and quote aliases containing colons. Keep every work in collaborations and every listing per source.

## Verify

Reuse the same input snapshot for before/after analysis; do not read Firestore twice. The helper's `--audit-data /tmp/ip-before.json` re-matches an audit snapshot with the current catalog. Compare complete match sets for **all** items, inspecting new matches on already classified titles as well as the missing count. Add offline regression cases for real titles, titleKo-only matching, collaborations and relevant negatives. Run the helper with an offline fixture and `python -m unittest discover -s tests -v` using the project environment.

Report dataset date, before/after counts, representative repairs and unresolved reasons. The public page changes on its next build/deployment; commit/push/deploy only when authorized.
