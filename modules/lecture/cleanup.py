from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Iterable

from core.config import data_dir
from core.database.client import get_connection


def _path_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _path_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _path_strings(item)


def _token_for_path(path_value: str, runs_dir: Path) -> str | None:
    try:
        path = Path(path_value).expanduser().resolve(strict=False)
        relative = path.relative_to(runs_dir.resolve(strict=False))
    except (ValueError, OSError):
        return None
    return relative.parts[0] if relative.parts else None


async def referenced_run_tokens(lecture_id: int) -> set[str]:
    """Return run tokens that still contain DB-referenced artifacts/checkpoints."""
    runs_dir = data_dir() / "lectures" / str(lecture_id) / "runs"
    db = await get_connection()
    try:
        lecture = await (await db.execute(
            """
            SELECT run_token, portrait_path, pptx_path, narration_path,
                   slides_video_path, avatar_path, final_video_path
            FROM lectures WHERE id=?
            """,
            (lecture_id,),
        )).fetchone()
        stages = await (await db.execute(
            "SELECT outputs_json FROM lecture_stages WHERE lecture_id=?",
            (lecture_id,),
        )).fetchall()
    finally:
        await db.close()

    tokens: set[str] = set()
    values: list[Any] = []
    if lecture:
        if lecture["run_token"]:
            tokens.add(str(lecture["run_token"]))
        values.extend(lecture[key] for key in (
            "portrait_path", "pptx_path", "narration_path", "slides_video_path", "avatar_path", "final_video_path"
        ))
    for row in stages:
        try:
            values.append(json.loads(row["outputs_json"] or "{}"))
        except (TypeError, json.JSONDecodeError):
            continue

    for value in values:
        for path_value in _path_strings(value):
            token = _token_for_path(path_value, runs_dir)
            if token:
                tokens.add(token)
    return tokens


def _retention_seconds() -> int:
    raw = os.getenv("LECTURE_ORPHAN_RUN_RETENTION_HOURS", "24").strip()
    try:
        hours = max(0.0, float(raw))
    except ValueError as exc:
        raise RuntimeError("LECTURE_ORPHAN_RUN_RETENTION_HOURS must be a non-negative number") from exc
    return int(hours * 3600)


async def cleanup_lecture_runs(lecture_id: int, *, preserve_tokens: Iterable[str] = ()) -> list[Path]:
    runs_dir = data_dir() / "lectures" / str(lecture_id) / "runs"
    if not runs_dir.is_dir():
        return []

    preserve = await referenced_run_tokens(lecture_id)
    preserve.update(str(token) for token in preserve_tokens if token)
    cutoff = time.time() - _retention_seconds()
    removed: list[Path] = []

    for candidate in runs_dir.iterdir():
        if candidate.name in preserve:
            continue
        try:
            stat = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.st_mtime > cutoff:
            continue
        if candidate.is_symlink() or candidate.is_file():
            candidate.unlink(missing_ok=True)
        elif candidate.is_dir():
            shutil.rmtree(candidate)
        removed.append(candidate)
    return removed


async def cleanup_all_orphan_runs() -> int:
    db = await get_connection()
    try:
        rows = await (await db.execute("SELECT id FROM lectures")).fetchall()
    finally:
        await db.close()

    removed = 0
    for row in rows:
        removed += len(await cleanup_lecture_runs(int(row["id"])))
    return removed
