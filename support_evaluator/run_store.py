"""Immutable per-run storage with root-level latest-run compatibility files."""

from __future__ import annotations

import json
import os
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .config import GENERATED_ARTIFACTS, RUNS_DIRECTORY

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    import msvcrt


def create_run_directory(project_root: Path, run_id: str) -> Path:
    run_dir = project_root / RUNS_DIRECTORY / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _load_index(project_root: Path) -> dict[str, Any]:
    path = project_root / RUNS_DIRECTORY / "index.json"
    if not path.exists():
        return {"schema_version": 1, "latest_attempt": None, "latest_successful": None, "runs": []}
    try:
        index = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "latest_attempt": None, "latest_successful": None, "runs": []}
    if not isinstance(index, dict) or not isinstance(index.get("runs"), list):
        return {"schema_version": 1, "latest_attempt": None, "latest_successful": None, "runs": []}
    return index


def _write_index(project_root: Path, index: dict[str, Any]) -> None:
    path = project_root / RUNS_DIRECTORY / "index.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _lock(lock_file: Any, acquire: bool) -> None:
    if "fcntl" in globals():
        operation = fcntl.LOCK_EX if acquire else fcntl.LOCK_UN
        fcntl.flock(lock_file.fileno(), operation)
        return

    lock_file.seek(0, os.SEEK_END)
    if lock_file.tell() == 0:
        lock_file.write(b"\0")
        lock_file.flush()
    lock_file.seek(0)
    operation = msvcrt.LK_LOCK if acquire else msvcrt.LK_UNLCK
    msvcrt.locking(lock_file.fileno(), operation, 1)


@contextmanager
def _index_lock(project_root: Path):
    lock_path = project_root / RUNS_DIRECTORY / "index.lock"
    with lock_path.open("a+b") as lock_file:
        _lock(lock_file, acquire=True)
        try:
            yield
        finally:
            _lock(lock_file, acquire=False)


def begin_run(project_root: Path, run_id: str, timestamp: str) -> Path:
    run_dir = create_run_directory(project_root, run_id)
    with _index_lock(project_root):
        index = _load_index(project_root)
        index["latest_attempt"] = run_id
        index.setdefault("runs", []).append({"run_id": run_id, "state": "IN_PROGRESS", "started_at": timestamp})
        _write_index(project_root, index)
    return run_dir


def finish_run(project_root: Path, run_id: str, state: str, timestamp: str) -> None:
    with _index_lock(project_root):
        index = _load_index(project_root)
        for record in reversed(index.setdefault("runs", [])):
            if record.get("run_id") == run_id:
                record.update({"state": state, "finished_at": timestamp})
                break
        else:
            index["runs"].append({"run_id": run_id, "state": state, "finished_at": timestamp})
        if state == "RESULTS_FINALISED":
            index["latest_successful"] = run_id
        _write_index(project_root, index)
        if index.get("latest_attempt") == run_id:
            _publish_latest(project_root, project_root / RUNS_DIRECTORY / run_id)


def _publish_latest(project_root: Path, run_dir: Path) -> None:
    """Materialize the latest attempt at legacy paths, replacing each file atomically."""
    names = [name for name in GENERATED_ARTIFACTS if name != "run_manifest.json"]
    names.append("run_manifest.json")
    for name in names:
        source = run_dir / name
        destination = project_root / name
        if not source.is_file():
            destination.unlink(missing_ok=True)
            continue
        temporary = destination.with_name(destination.name + ".tmp")
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
