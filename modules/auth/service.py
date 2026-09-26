import asyncio
from argon2 import PasswordHasher
from argon2.exceptions import (
    InvalidHashError,
    VerifyMismatchError,
)
from aiosqlite import IntegrityError

from core.database.client import get_connection


_password_hasher = PasswordHasher()


class EmailAlreadyExistsError(ValueError):
    pass


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def register_user(
    *,
    email: str,
    password: str,
    name: str | None = None,
) -> int:
    email = normalize_email(email)

    if not email:
        raise ValueError("이메일을 입력하세요.")

    if len(password) < 8:
        raise ValueError("비밀번호는 8자 이상이어야 합니다.")

    password_hash = await asyncio.to_thread(_password_hasher.hash, password)

    db = await get_connection()

    try:
        await db.execute("BEGIN")

        try:
            cursor = await db.execute(
                """
                INSERT INTO users (
                    email,
                    password_hash
                )
                VALUES (?, ?)
                """,
                (
                    email,
                    password_hash,
                ),
            )
        except IntegrityError as exc:
            raise EmailAlreadyExistsError(
                "이미 가입된 이메일입니다."
            ) from exc

        user_id = cursor.lastrowid

        await db.execute(
            """
            INSERT INTO user_profiles (
                user_id,
                name
            )
            VALUES (?, ?)
            """,
            (
                user_id,
                (name or "").strip() or None,
            ),
        )

        await db.execute(
            """
            INSERT INTO user_settings (
                user_id
            )
            VALUES (?)
            """,
            (user_id,),
        )

        await db.commit()
        return int(user_id)

    except Exception:
        await db.rollback()
        raise

    finally:
        await db.close()


async def authenticate_user(
    *,
    email: str,
    password: str,
):
    email = normalize_email(email)
    db = await get_connection()

    try:
        cursor = await db.execute(
            """
            SELECT
                id,
                email,
                password_hash,
                status
            FROM users
            WHERE email = ?
            LIMIT 1
            """,
            (email,),
        )

        row = await cursor.fetchone()

        if row is None:
            return None

        if row["status"] != "active":
            return None

        try:
            await asyncio.to_thread(
                _password_hasher.verify,
                row["password_hash"],
                password,
            )
        except (VerifyMismatchError, InvalidHashError):
            return None

        needs_rehash = await asyncio.to_thread(
            _password_hasher.check_needs_rehash,
            row["password_hash"],
        )
        if needs_rehash:
            new_hash = await asyncio.to_thread(_password_hasher.hash, password)
            await db.execute(
                """
                UPDATE users
                SET password_hash = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    new_hash,
                    row["id"],
                ),
            )

        await db.execute(
            """
            UPDATE users
            SET last_login_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (row["id"],),
        )

        await db.commit()

        return {
            "id": row["id"],
            "email": row["email"],
        }

    finally:
        await db.close()
