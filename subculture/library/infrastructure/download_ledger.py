"""Append-only record of image URLs already saved under the exports folder (`ledger.jsonl`)."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

LEDGER_NAME = "ledger.jsonl"


class DownloadLedger:
    """URL -> where that image was saved, so later exports can skip re-downloading it.

    One JSON object per line: `url`, `path` (relative to the exports folder, e.g.
    `<stamp>/items/FIGURE_x/00_main.jpg`), `sha256`, `bytes`, `format`, `downloadedAt`.
    A missing ledger is seeded once from the `ok` files of existing `*/index.json` exports.
    """

    def __init__(self, exports_dir: Path):
        self.exports_dir = Path(exports_dir)
        self.path = self.exports_dir / LEDGER_NAME
        self._lock = threading.Lock()
        self._by_url: dict[str, dict] | None = None

    def lookup(self, url: str) -> dict | None:
        """The recorded download for `url`, only while its file still exists."""
        record = self._records().get(url)
        if record and (self.exports_dir / record["path"]).is_file():
            return record
        return None

    def record(self, url: str, path: str, *, sha256: str, size: int, image_format: str) -> None:
        entry = {
            "url": url,
            "path": path,
            "sha256": sha256,
            "bytes": size,
            "format": image_format,
            "downloadedAt": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._records()[url] = entry
            self._append([entry])

    def _records(self) -> dict[str, dict]:
        if self._by_url is None:
            if self.path.is_file():
                self._by_url = self._read()
            else:
                self._by_url = self._seed_from_exports()
                if self._by_url:
                    self._append(self._by_url.values())
        return self._by_url

    def _read(self) -> dict[str, dict]:
        by_url = {}
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue  # a line cut off by an interrupted run
            if isinstance(entry, dict) and entry.get("url") and entry.get("path"):
                by_url[entry["url"]] = entry
        return by_url

    def _seed_from_exports(self) -> dict[str, dict]:
        by_url = {}
        for index_path in sorted(self.exports_dir.glob("*/index.json")):
            try:
                entries = json.loads(index_path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            stamp = index_path.parent.name
            for entry in entries if isinstance(entries, list) else []:
                for file in entry.get("files") or []:
                    if file.get("status") != "ok" or not file.get("url") or not file.get("path"):
                        continue
                    by_url[file["url"]] = {
                        "url": file["url"],
                        "path": f"{stamp}/{file['path']}",
                        "sha256": file.get("sha256"),
                        "bytes": file.get("bytes"),
                        "format": file.get("format"),
                        "downloadedAt": None,
                    }
        return by_url

    def _append(self, entries) -> None:
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
            handle.flush()
