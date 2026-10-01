import re

import pytest
from fastapi.testclient import TestClient

from core.database.client import get_connection
from modules.lecture.repository import create_lecture, update_lecture


def csrf(response):
    return re.search(r'name="csrf_token"\s+value="([^"]+)"', response.text)[1]


@pytest.fixture
def client(monkeypatch):
    async def valid_openai_key(_key):
        return None

    monkeypatch.setattr(
        "modules.credentials.routes.validate_openai_api_key", valid_openai_key
    )

    from app import app

    with TestClient(app) as client:
        token = csrf(client.get("/register"))
        response = client.post(
            "/register",
            data={
                "email": "route@example.test",
                "name": "Test",
                "password": "test-password-123",
                "password_confirm": "test-password-123",
                "csrf_token": token,
            },
        )
        assert response.status_code == 200
        token = csrf(client.get("/settings/credentials"))
        response = client.post(
            "/settings/credentials/openai",
            data={"secret": "user-owned-test-key", "csrf_token": token},
            follow_redirects=False,
        )
        assert response.status_code == 303
        yield client


def fields(client):
    return {
        "title": "Title",
        "topic": "Topic",
        "text_model": "test",
        "image_model": "test",
        "tts_model": "test",
        "tts_voice": "alloy",
        "csrf_token": csrf(client.get("/lectures/new")),
    }


async def test_submit_queues_without_executing_pipeline(client, portrait_bytes):
    response = client.post(
        "/lectures",
        data=fields(client),
        files={"portrait": ("p.png", portrait_bytes, "image/png")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    db = await get_connection()
    try:
        rows = await (await db.execute("SELECT * FROM lecture_jobs")).fetchall()
        assert (
            len(rows) == 1
            and rows[0]["status"] == "queued"
            and rows[0]["attempts"] == 0
        )
        assert (
            await (await db.execute("SELECT COUNT(*) FROM lecture_stages")).fetchone()
        )[0] == 0
    finally:
        await db.close()


@pytest.mark.parametrize(
    "extra",
    [
        {"moodle_course_id": "abc"},
        {"upload_to_moodle": "on"},
        {"upload_to_moodle": "on", "moodle_course_id": "1"},
        {"moodle_deploy_mode": "bad"},
        {"title": "   "},
        {"moodle_course_id": "-1"},
    ],
)
def test_invalid_inputs_are_422(client, portrait_bytes, extra):
    response = client.post(
        "/lectures",
        data=fields(client) | extra,
        files={"portrait": ("p.png", portrait_bytes, "image/png")},
    )
    assert response.status_code == 422


def test_csrf_required(client, portrait_bytes):
    response = client.post(
        "/lectures",
        data=fields(client) | {"csrf_token": "wrong"},
        files={"portrait": ("p.png", portrait_bytes, "image/png")},
    )
    assert response.status_code == 403


def test_bad_portrait_rejected(client):
    response = client.post(
        "/lectures",
        data=fields(client),
        files={"portrait": ("p.png", b"not-image", "image/png")},
    )
    assert response.status_code == 422


def test_credentials_url_rejected_before_network(client):
    response = client.post(
        "/settings/credentials/moodle",
        data={
            "secret": "test-token",
            "base_url": "https://169.254.169.254",
            "csrf_token": csrf(client.get("/settings/credentials")),
        },
    )
    assert response.status_code == 422


def test_system_openai_key_is_not_a_user_fallback(portrait_bytes, monkeypatch):
    monkeypatch.setenv("OPENAI_KEY_MODE", "user")
    from app import app

    with TestClient(app) as anonymous_client:
        token = csrf(anonymous_client.get("/register"))
        response = anonymous_client.post(
            "/register",
            data={
                "email": "no-key@example.test",
                "name": "No Key",
                "password": "test-password-123",
                "password_confirm": "test-password-123",
                "csrf_token": token,
            },
        )
        assert response.status_code == 200
        response = anonymous_client.post(
            "/lectures",
            data=fields(anonymous_client),
            files={"portrait": ("p.png", portrait_bytes, "image/png")},
        )
        assert response.status_code == 422
        assert "OpenAI API Key" in response.text


async def test_disabled_account_session_is_invalidated(client):
    db = await get_connection()
    try:
        await db.execute(
            "UPDATE users SET status='disabled' WHERE email='route@example.test'"
        )
        await db.commit()
    finally:
        await db.close()
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_security_headers_and_self_hosted_tailwind(client):
    response = client.get("/dashboard")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "cdn.tailwindcss.com" not in response.text
    css = client.get("/static/tailwind.css")
    assert css.status_code == 200
    assert ".bg-slate-50" in css.text


def test_login_rate_limit_returns_429():
    from app import app

    with TestClient(app) as anonymous_client:
        token = csrf(anonymous_client.get("/login"))
        response = None
        for _ in range(11):
            response = anonymous_client.post(
                "/login",
                data={
                    "email": "rate-limit@example.test",
                    "password": "wrong-password",
                    "csrf_token": token,
                },
            )
        assert response is not None
        assert response.status_code == 429
        assert int(response.headers["retry-after"]) >= 1


def test_server_openai_key_mode_uses_server_key(monkeypatch):
    import asyncio

    from modules.credentials.required import require_user_openai_api_key

    monkeypatch.setenv("OPENAI_KEY_MODE", "server")
    monkeypatch.setenv("SERVER_OPENAI_API_KEY", "server-owned-key")
    assert asyncio.run(require_user_openai_api_key(999)) == "server-owned-key"


def test_invalid_openai_key_is_not_saved(monkeypatch):
    async def invalid_key(_key):
        raise RuntimeError("invalid")

    monkeypatch.setattr(
        "modules.credentials.routes.validate_openai_api_key", invalid_key
    )

    from app import app

    with TestClient(app) as anonymous_client:
        token = csrf(anonymous_client.get("/register"))
        anonymous_client.post(
            "/register",
            data={
                "email": "bad-key@example.test",
                "name": "Bad Key",
                "password": "test-password-123",
                "password_confirm": "test-password-123",
                "csrf_token": token,
            },
        )
        response = anonymous_client.post(
            "/settings/credentials/openai",
            data={
                "secret": "bad-secret-key",
                "csrf_token": csrf(anonymous_client.get("/settings/credentials")),
            },
        )
        assert response.status_code == 422
        assert "bad-secret-key" not in response.text


def test_new_lecture_exposes_review_reference_and_account_budget_link(client):
    response = client.get("/lectures/new")
    assert response.status_code == 200
    assert 'name="review_before_video"' in response.text
    assert 'name="reference_files"' in response.text
    assert 'name="max_cost_usd"' not in response.text
    assert "/settings/profile" in response.text


async def test_submit_persists_reference_and_review(client, portrait_bytes):
    data = fields(client) | {"review_before_video": "on"}
    response = client.post(
        "/lectures",
        data=data,
        files=[
            ("portrait", ("p.png", portrait_bytes, "image/png")),
            (
                "reference_files",
                ("notes.txt", b"Grounded course material", "text/plain"),
            ),
        ],
        follow_redirects=False,
    )
    assert response.status_code == 303
    db = await get_connection()
    try:
        row = await (
            await db.execute("SELECT * FROM lectures ORDER BY id DESC LIMIT 1")
        ).fetchone()
        assert row["review_before_video"] == 1
        assert row["review_status"] == "pending"
        assert "notes.txt" in row["source_files_json"]
    finally:
        await db.close()


def test_profile_exposes_openai_budget_control(client):
    response = client.get("/settings/profile")
    assert response.status_code == 200
    assert 'name="openai_budget_usd"' in response.text


async def test_profile_saves_account_openai_budget(client):
    response = client.get("/settings/profile")
    token = csrf(response)
    saved = client.post(
        "/settings/profile",
        data={
            "name": "Test",
            "nickname": "Budget Owner",
            "phone": "",
            "language": "ko",
            "openai_budget_usd": "12.34",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert saved.status_code == 303

    db = await get_connection()
    try:
        row = await (
            await db.execute(
                """SELECT s.openai_budget_usd
               FROM user_settings s
               JOIN users u ON u.id=s.user_id
               WHERE u.email='route@example.test'"""
            )
        ).fetchone()
    finally:
        await db.close()
    assert row is not None
    assert row["openai_budget_usd"] == pytest.approx(12.34)


async def test_instructor_avatar_upload_saves_immediately(client, portrait_bytes):
    page = client.get("/instructor")
    assert page.status_code == 200
    token = csrf(page)
    response = client.post(
        "/instructor/avatar",
        data={"csrf_token": token},
        files={"avatar": ("professor.png", portrait_bytes, "image/png")},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True

    db = await get_connection()
    try:
        row = await (
            await db.execute(
                """SELECT p.avatar_path
               FROM ai_instructor_profiles p
               JOIN users u ON u.id=p.user_id
               WHERE u.email='route@example.test'"""
            )
        ).fetchone()
    finally:
        await db.close()
    assert row is not None
    assert row["avatar_path"]

    image = client.get("/instructor/avatar")
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/png")


def test_server_mode_profile_uses_environment_budget_and_hides_user_budget_input(
    client, monkeypatch
):
    monkeypatch.setenv("OPENAI_KEY_MODE", "server")
    monkeypatch.setenv("SERVER_OPENAI_ACCOUNT_BUDGET_USD", "25.00")
    response = client.get("/settings/profile")
    assert response.status_code == 200
    assert 'name="openai_budget_usd"' not in response.text
    assert "$25.00" in response.text
    assert "각 계정의 사용액은 서로 독립적으로 계산됩니다." in response.text


async def test_other_user_cannot_download_lecture_artifacts(client, tmp_path):
    db = await get_connection()
    try:
        owner = await (
            await db.execute("SELECT id FROM users WHERE email='route@example.test'")
        ).fetchone()
    finally:
        await db.close()

    assert owner is not None
    lecture_id = await create_lecture(
        user_id=int(owner["id"]),
        title="Owner lecture",
        topic="Private material",
        text_model="test",
        image_model="test",
        tts_model="test",
        tts_voice="alloy",
        generate_images=False,
        moodle_course_id=None,
        moodle_section_num=None,
        moodle_deploy_mode="create",
        moodle_videotracker_cmid=None,
        upload_to_moodle=False,
    )
    video_path = tmp_path / "owner-video.mp4"
    video_path.write_bytes(b"owner-only-video")
    await update_lecture(
        lecture_id,
        final_video_path=str(video_path),
        quiz_json={"questions": [{"question": "owner-only-quiz"}]},
    )

    client.cookies.clear()
    token = csrf(client.get("/register"))
    response = client.post(
        "/register",
        data={
            "email": "other-user@example.test",
            "name": "Other User",
            "password": "test-password-123",
            "password_confirm": "test-password-123",
            "csrf_token": token,
        },
    )
    assert response.status_code == 200

    for path in (
        f"/lectures/{lecture_id}/download/video",
        f"/lectures/{lecture_id}/quiz.json",
    ):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/lectures"
        assert "content-disposition" not in response.headers
        assert b"owner-only-video" not in response.content
        assert b"owner-only-quiz" not in response.content
