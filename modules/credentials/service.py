import json
from typing import Any

from core.database.client import get_connection
from core.database.secrets import (
    decrypt_secret,
    encrypt_secret,
)


async def save_credential(
    *,
    provider: str,
    credential_type: str,
    secret: str,
    name: str = "default",
    user_id: int | None = None,
    organization_id: int | None = None,
    metadata: dict[str, Any] | None = None,
):
    if (user_id is None) == (organization_id is None):
        raise ValueError("Exactly one of user_id or organization_id is required.")

    encrypted = encrypt_secret(secret)
    metadata_json = (
        json.dumps(
            metadata,
            ensure_ascii=False,
        )
        if metadata
        else None
    )

    db = await get_connection()

    try:
        if user_id is not None:
            await db.execute(
                """
                INSERT INTO credentials (
                    user_id,
                    provider,
                    credential_type,
                    name,
                    encrypted_secret,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(
                    user_id,
                    provider,
                    credential_type,
                    name
                )
                WHERE user_id IS NOT NULL
                DO UPDATE SET
                    encrypted_secret = excluded.encrypted_secret,
                    metadata_json = excluded.metadata_json,
                    revoked_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    user_id,
                    provider,
                    credential_type,
                    name,
                    encrypted,
                    metadata_json,
                ),
            )
        else:
            await db.execute(
                """
                INSERT INTO credentials (
                    organization_id,
                    provider,
                    credential_type,
                    name,
                    encrypted_secret,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(
                    organization_id,
                    provider,
                    credential_type,
                    name
                )
                WHERE organization_id IS NOT NULL
                DO UPDATE SET
                    encrypted_secret = excluded.encrypted_secret,
                    metadata_json = excluded.metadata_json,
                    revoked_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    organization_id,
                    provider,
                    credential_type,
                    name,
                    encrypted,
                    metadata_json,
                ),
            )

        await db.commit()

    finally:
        await db.close()


async def get_credential(
    *,
    provider: str,
    credential_type: str,
    name: str = "default",
    user_id: int | None = None,
    organization_id: int | None = None,
):
    if (user_id is None) == (organization_id is None):
        raise ValueError("Exactly one of user_id or organization_id is required.")

    db = await get_connection()

    try:
        if user_id is not None:
            cursor = await db.execute(
                """
                SELECT *
                FROM credentials
                WHERE user_id = ?
                  AND provider = ?
                  AND credential_type = ?
                  AND name = ?
                  AND revoked_at IS NULL
                LIMIT 1
                """,
                (
                    user_id,
                    provider,
                    credential_type,
                    name,
                ),
            )
        else:
            cursor = await db.execute(
                """
                SELECT *
                FROM credentials
                WHERE organization_id = ?
                  AND provider = ?
                  AND credential_type = ?
                  AND name = ?
                  AND revoked_at IS NULL
                LIMIT 1
                """,
                (
                    organization_id,
                    provider,
                    credential_type,
                    name,
                ),
            )

        row = await cursor.fetchone()

        if row is None:
            return None

        return {
            "id": row["id"],
            "provider": row["provider"],
            "credential_type": row["credential_type"],
            "name": row["name"],
            "secret": decrypt_secret(row["encrypted_secret"]),
            "metadata": (
                json.loads(row["metadata_json"]) if row["metadata_json"] else {}
            ),
        }

    finally:
        await db.close()


async def list_user_credentials(
    user_id: int,
) -> list[dict]:
    db = await get_connection()

    try:
        cursor = await db.execute(
            """
            SELECT
                id,
                provider,
                credential_type,
                name,
                metadata_json,
                created_at,
                updated_at
            FROM credentials
            WHERE user_id = ?
              AND revoked_at IS NULL
            ORDER BY provider, name
            """,
            (user_id,),
        )

        rows = await cursor.fetchall()

        return [
            {
                "id": row["id"],
                "provider": row["provider"],
                "credential_type": row["credential_type"],
                "name": row["name"],
                "metadata": (
                    json.loads(row["metadata_json"]) if row["metadata_json"] else {}
                ),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    finally:
        await db.close()


async def revoke_user_credential(
    *,
    user_id: int,
    provider: str,
):
    db = await get_connection()

    try:
        await db.execute(
            """
            UPDATE credentials
            SET revoked_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
              AND provider = ?
              AND revoked_at IS NULL
            """,
            (
                user_id,
                provider,
            ),
        )

        await db.commit()

    finally:
        await db.close()
