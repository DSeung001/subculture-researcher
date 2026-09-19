BEGIN TRANSACTION;
CREATE TABLE collection_items (
                    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
                    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(collection_id, item_id)
                );
CREATE TABLE collections (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL, note TEXT NOT NULL DEFAULT ''
                );
CREATE TABLE information_types (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL,
                    normalized TEXT NOT NULL UNIQUE);
CREATE TABLE item_information_types (
                    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                    term_id INTEGER NOT NULL REFERENCES information_types(id) ON DELETE CASCADE,
                    PRIMARY KEY(item_id, term_id));
CREATE TABLE item_product_categories (
                    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                    term_id INTEGER NOT NULL REFERENCES product_categories(id) ON DELETE CASCADE,
                    PRIMARY KEY(item_id, term_id));
CREATE TABLE item_tags (
                    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                    term_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                    PRIMARY KEY(item_id, term_id));
CREATE TABLE item_works (
                    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                    term_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
                    PRIMARY KEY(item_id, term_id));
CREATE TABLE items (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, url TEXT NOT NULL,
                    source TEXT NOT NULL, payload TEXT NOT NULL,
                    deadline TEXT, synced_at TEXT NOT NULL
                );
CREATE TABLE product_categories (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL,
                    normalized TEXT NOT NULL UNIQUE);
CREATE TABLE saved_filters (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL, filters TEXT NOT NULL
                );
CREATE TABLE sync_state (
                    id INTEGER PRIMARY KEY CHECK(id=1), completed_at TEXT NOT NULL,
                    item_count INTEGER NOT NULL
                );
CREATE TABLE tags (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL,
                    normalized TEXT NOT NULL UNIQUE);
CREATE TABLE work_aliases (
                    work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, normalized TEXT NOT NULL,
                    PRIMARY KEY(work_id, normalized)
                );
CREATE TABLE works (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL,
                    normalized TEXT NOT NULL UNIQUE);
CREATE INDEX items_deadline ON items(deadline);
CREATE INDEX by_works ON item_works(term_id, item_id);
CREATE INDEX by_product_categories ON item_product_categories(term_id, item_id);
CREATE INDEX by_information_types ON item_information_types(term_id, item_id);
CREATE INDEX by_tags ON item_tags(term_id, item_id);
COMMIT;
PRAGMA user_version=1;
