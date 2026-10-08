"""Read-only IP audit; emit metadata and recomputed matches as JSON."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from subculture.library.application.catalog import load_catalog
from subculture.library.domain.keywords import compile_works, match_works


def site_records(payload):
    for item in payload['items']:
        view = item['view']
        yield {'id': item['id'], 'title': view.get('original_title') or '',
               'titleKo': view.get('title_text') or '', 'source': item.get('source') or '',
               'url': view.get('url') or ''}


def firestore_records():
    from subculture.shared.content_model import content_id
    from subculture.shared.firebase_client import get_db
    for snapshot in get_db().collection_group('contents').stream(timeout=30, retry=None):
        data = snapshot.to_dict()
        if data.get('status') != 'IGNORE':
            yield {'id': content_id(snapshot), **{
                key: data.get(key) or '' for key in ('title', 'titleKo', 'source', 'url')}}


def audit(records, catalog):
    compiled = compile_works(catalog)
    items = [{**record, 'works': match_works(record, compiled)} for record in records]
    missing = [item for item in items if not item['works']]
    return {'total': len(items), 'unclassified': len(missing), 'missing': missing, 'items': items}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--firestore', action='store_true')
    mode.add_argument('--site-data', type=Path)
    mode.add_argument('--audit-data', type=Path)
    args = parser.parse_args()
    built_at = None
    if args.site_data or args.audit_data:
        payload = json.loads((args.site_data or args.audit_data).read_text(encoding='utf-8'))
        built_at = payload.get('builtAt')
        records = site_records(payload) if args.site_data else payload['items']
    else:
        records = firestore_records()
    result = audit(records, load_catalog())
    result['dataset'] = (payload.get('dataset', 'site') if args.audit_data
                         else 'site' if args.site_data else 'firestore')
    result['builtAt'] = built_at
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
