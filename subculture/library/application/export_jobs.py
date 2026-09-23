"""Run one image export at a time in the background and report its progress."""

from __future__ import annotations

import threading
import uuid
from dataclasses import asdict
from pathlib import Path

from subculture.library.application.export_images import (
    ExportError, ExportOptions, ExportProgress, export_images,
)


def _thread_runner(target) -> None:
    threading.Thread(target=target, name="image-export", daemon=True).start()


class ExportJobs:
    """In-memory job registry. `runner(target)` starts the work (a daemon thread by default)."""

    def __init__(self, runner=_thread_runner, export=export_images):
        self._runner = runner
        self._export = export
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}

    def start(
        self, library_factory, item_ids: list[str], options: ExportOptions, *,
        directory: Path | None = None, fetch=None,
    ) -> str:
        if not item_ids:
            raise ExportError("내보낼 항목이 없습니다.")
        with self._lock:
            if any(job["state"] == "running" for job in self._jobs.values()):
                raise ExportError("이미 진행 중인 내보내기가 있습니다.")
            job_id = uuid.uuid4().hex
            total = len(item_ids) if options.max_items is None else min(len(item_ids), options.max_items)
            job = {
                "id": job_id,
                "state": "running",
                "progress": asdict(ExportProgress(items_total=total)),
                "directory": None,
                "error": None,
                "stop": threading.Event(),
            }
            self._jobs[job_id] = job

        def report(progress: ExportProgress) -> None:
            with self._lock:
                job["progress"] = asdict(progress)

        def work() -> None:
            try:
                root = self._export(
                    library_factory(), item_ids, directory=directory, options=options,
                    fetch=fetch, progress=report, should_stop=job["stop"].is_set,
                )
            except Exception as exc:
                with self._lock:
                    job["state"], job["error"] = "failed", str(exc)
                return
            with self._lock:
                job["directory"] = str(root)
                job["state"] = "cancelled" if job["progress"]["stop_reason"] == "cancelled" else "done"

        self._runner(work)
        return job_id

    def status(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return {key: value for key, value in job.items() if key != "stop"}

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job["state"] != "running":
                return False
            job["stop"].set()
            return True
