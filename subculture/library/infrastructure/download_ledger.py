"""Append-only URL ledger relative to its storage root (shared images)."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

LEDGER_NAME = "ledger.jsonl"


class DownloadLedger:
    """URL -> where that image was saved, so later exports can skip re-downloading it.

    One JSON object per line: `url`, `path` (relative to this ledger's root), `sha256`, `bytes`, `format`, `downloadedAt`.
    A missing ledger starts empty.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self.path = self.root / LEDGER_NAME
        self._lock = threading.Lock()
        self._by_url: dict[str, dict] | None = None

    def lookup(self, url: str) -> dict | None:
        """The recorded download for `url`, only while its file still exists."""
        record = self._records().get(url)
        if record and self._valid_file(record["path"]):
            return record
        return None

    def _valid_file(self, value: str) -> bool:
        if not isinstance(value, str) or Path(value).is_absolute():
            return False
        path = (self.root / value).resolve()
        return path.is_relative_to(self.root.resolve()) and path.is_file()

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
            self._append(entry)
            self._records()[url] = entry

    def _records(self) -> dict[str, dict]:
        if self._by_url is None:
            self._by_url = self._read() if self.path.is_file() else {}
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

    def _append(self, entry: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
            handle.flush()
