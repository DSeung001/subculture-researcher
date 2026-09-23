"""Content-addressed local originals, independent of export lifetime."""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from subculture.library.infrastructure.download_ledger import DownloadLedger

EXTENSIONS = {"jpeg": ".jpg", "png": ".png", "gif": ".gif", "webp": ".webp", "bmp": ".bmp"}


def contained_path(root: Path, value: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError("Image path must be relative")
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Image path escapes storage root")
    return path


class ImageStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.ledger = DownloadLedger(self.root)

    def lookup(self, url: str) -> dict | None:
        return self.ledger.lookup(url)

    def save(self, url: str, body: bytes, image_format: str) -> dict:
        digest = hashlib.sha256(body).hexdigest()
        relative = f"{digest[:2]}/{digest}{EXTENSIONS[image_format]}"
        destination = contained_path(self.root, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            if not destination.is_file() or hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".image-", delete=False) as handle:
                    temporary = Path(handle.name)
                    handle.write(body)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, destination)
            self.ledger.record(url, relative, sha256=digest, size=len(body), image_format=image_format)
        except BaseException:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            try:
                destination.parent.rmdir()  # only when this failed write left it empty
            except OSError:
                pass
            raise
        return {"path": relative, "sha256": digest, "bytes": len(body), "format": image_format}
