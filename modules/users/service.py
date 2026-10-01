import asyncio
import json
import shutil
from pathlib import Path

from core.config import data_dir
from core.database.client import get_connection


async def get_user_status(user_id: int) -> str | None:
    db = await get_connection()
    try:
        row = await (
            await db.execute(
                "SELECT status FROM users WHERE id = ? LIMIT 1",
                (user_id,),
            )
        ).fetchone()
        return str(row["status"]) if row else None
    finally:
        await db.close()


async def get_user(user_id: int):
    db = await get_connection()

    try:
        cursor = await db.execute(
            """
            SELECT
                u.id,
                u.email,
                u.status,
                u.email_verified,
                u.created_at,
                u.last_login_at,
                p.name,
                p.nickname,
                p.phone,
                p.avatar_path,
                s.language,
                s.default_openai_model,
                s.default_image_model,
                s.default_realtime_model,
                s.default_course_id,
                s.openai_budget_usd
            FROM users AS u
            LEFT JOIN user_profiles AS p
                ON p.user_id = u.id
            LEFT JOIN user_settings AS s
                ON s.user_id = u.id
            WHERE u.id = ?
            LIMIT 1
            """,
            (user_id,),
        )

        row = await cursor.fetchone()

        return dict(row) if row else None

    finally:
        await db.close()


async def update_language(*, user_id: int, language: str) -> None:
    db = await get_connection()
    try:
        await db.execute(
            """
            UPDATE user_settings
            SET language = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
            """,
            (language, user_id),
        )
        await db.commit()
    finally:
        await db.close()


async def update_profile(
    *,
    user_id: int,
    name: str | None,
    nickname: str | None,
    phone: str | None,
    language: str = "auto",
    openai_budget_usd: float | None = None,
):
    db = await get_connection()

    try:
        await db.execute(
            """
            UPDATE user_profiles
            SET name = ?,
                nickname = ?,
                phone = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
            """,
            (
                (name or "").strip() or None,
                (nickname or "").strip() or None,
                (phone or "").strip() or None,
                user_id,
            ),
        )

        await db.execute(
            """
            UPDATE user_settings
            SET language = ?,
                openai_budget_usd = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
            """,
            (
                language,
                openai_budget_usd,
                user_id,
            ),
        )

        await db.commit()

    finally:
        await db.close()


def _safe_user_file(path_value: str | None, root: Path) -> Path | None:
    if not path_value:
        return None
    try:
        candidate = Path(path_value).expanduser().resolve(strict=False)
        candidate.relative_to(root.resolve(strict=False))
    except (OSError, ValueError):
        return None
    return candidate


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


async def _quiesce_user_work(db, user_id: int) -> None:
    """Revoke local work before account rows/files disappear."""
    await db.execute("BEGIN IMMEDIATE")
    cursor = await db.execute(
        """
        UPDATE users
        SET status='deleting', updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (user_id,),
    )
    if cursor.rowcount != 1:
        await db.rollback()
        raise ValueError("삭제할 계정을 찾을 수 없습니다.")
    # Do not delete durable jobs here.  ``users.status != 'active'`` is already
    # part of the queue ownership/claim predicates, so changing the account to
    # ``deleting`` fences workers immediately.  Keeping the rows until the final
    # user DELETE means a cancelled/failed account deletion can restore the user
    # without silently losing queued work.
    await db.execute(
        """
        UPDATE lecture_publish_schedules
        SET lease_until=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
        WHERE user_id=? AND status='publishing'
        """,
        (user_id,),
    )
    instructor_table = await (
        await db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ai_instructor_runs'"
        )
    ).fetchone()
    if instructor_table is not None:
        await db.execute(
            """
            UPDATE ai_instructor_runs
            SET planning_lease_until=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
            WHERE user_id=? AND status='planning'
            """,
            (user_id,),
        )
    await db.commit()


async def delete_account(user_id: int) -> None:
    """Delete an account and its user-owned files.

    Database rows are removed transactionally through the users row and FK cascades.
    Files are collected before that transaction and are deleted only when they live
    under DATA_DIR, so a corrupted DB path cannot delete arbitrary host files.
    """
    root = data_dir().resolve(strict=False)
    db = await get_connection()
    paths: set[Path] = set()
    lecture_ids: list[int] = []
    original_status: str | None = None
    quiesced = False
    try:
        user_row = await (
            await db.execute("SELECT status FROM users WHERE id = ? LIMIT 1", (user_id,))
        ).fetchone()
        if user_row is None:
            raise ValueError("삭제할 계정을 찾을 수 없습니다.")
        original_status = str(user_row["status"] or "active")

        lectures = await (
            await db.execute(
                """
            SELECT id, portrait_path, pptx_path, narration_path, slides_video_path,
                   avatar_path, final_video_path, source_files_json
            FROM lectures WHERE user_id = ?
            """,
                (user_id,),
            )
        ).fetchall()
        profile = await (
            await db.execute(
                "SELECT avatar_path FROM user_profiles WHERE user_id = ?",
                (user_id,),
            )
        ).fetchone()

        for row in lectures:
            lecture_ids.append(int(row["id"]))
            for key in (
                "portrait_path",
                "pptx_path",
                "narration_path",
                "slides_video_path",
                "avatar_path",
                "final_video_path",
            ):
                candidate = _safe_user_file(row[key], root)
                if candidate:
                    paths.add(candidate)
            try:
                references = json.loads(row["source_files_json"] or "[]")
            except (TypeError, ValueError, json.JSONDecodeError):
                references = []
            for item in references if isinstance(references, list) else []:
                if isinstance(item, dict):
                    candidate = _safe_user_file(str(item.get("path") or ""), root)
                    if candidate:
                        paths.add(candidate)

        if profile:
            candidate = _safe_user_file(profile["avatar_path"], root)
            if candidate:
                paths.add(candidate)

        await _quiesce_user_work(db, user_id)
        quiesced = True
        # runner.py checks ownership at least every two seconds.  The ``deleting``
        # account status makes those ownership checks fail; give the process a
        # brief cancellation window before removing filesystem roots so a stale
        # process cannot recreate them.
        await asyncio.sleep(2.25)

        await db.execute("BEGIN IMMEDIATE")
        cursor = await db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        if cursor.rowcount != 1:
            await db.rollback()
            raise ValueError("삭제할 계정을 찾을 수 없습니다.")
        await db.commit()
    except BaseException:
        await db.rollback()
        if quiesced and original_status is not None:
            await db.execute(
                "UPDATE users SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (original_status, user_id),
            )
            await db.commit()
        raise
    finally:
        await db.close()

    # Known per-account roots cover generated run artifacts even if a path was not
    # persisted in the lecture row.
    paths.add(root / "instructor" / str(user_id))
    for lecture_id in lecture_ids:
        paths.add(root / "lectures" / str(lecture_id))

    for path in sorted(paths, key=lambda value: len(value.parts), reverse=True):
        _remove_path(path)
        parent = path.parent
        while parent != root and root in parent.parents:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
