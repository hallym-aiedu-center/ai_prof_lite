import re

import pytest
from fastapi.testclient import TestClient

from core.database.client import get_connection


def csrf(response):
    return re.search(r'name="csrf_token"\s+value="([^"]+)"', response.text)[1]


@pytest.fixture
def client(monkeypatch):
    async def valid_openai_key(_key):
        return None
    monkeypatch.setattr("modules.credentials.routes.validate_openai_api_key", valid_openai_key)

    from app import app
    with TestClient(app) as client:
        token = csrf(client.get('/register'))
        response = client.post('/register', data={'email': 'route@example.test', 'name': 'Test',
            'password': 'test-password-123', 'password_confirm': 'test-password-123', 'csrf_token': token})
        assert response.status_code == 200
        token = csrf(client.get('/settings/credentials'))
        response = client.post('/settings/credentials/openai', data={
            'secret': 'user-owned-test-key', 'csrf_token': token
        }, follow_redirects=False)
        assert response.status_code == 303
        yield client


def fields(client):
    return {'title': 'Title', 'topic': 'Topic', 'text_model': 'test', 'image_model': 'test',
                'tts_model': 'test', 'tts_voice': 'alloy', 'csrf_token': csrf(client.get('/lectures/new'))}


async def test_submit_queues_without_executing_pipeline(client, portrait_bytes):
    response = client.post('/lectures', data=fields(client),
                           files={'portrait': ('p.png', portrait_bytes, 'image/png')}, follow_redirects=False)
    assert response.status_code == 303
    db = await get_connection()
    try:
        rows = await (await db.execute('SELECT * FROM lecture_jobs')).fetchall()
        assert len(rows) == 1 and rows[0]['status'] == 'queued' and rows[0]['attempts'] == 0
        assert (await (await db.execute('SELECT COUNT(*) FROM lecture_stages')).fetchone())[0] == 0
    finally: await db.close()


@pytest.mark.parametrize('extra', [
    {'moodle_course_id': 'abc'}, {'upload_to_moodle': 'on'},
    {'upload_to_moodle': 'on', 'moodle_course_id': '1'},
    {'moodle_deploy_mode': 'bad'}, {'title': '   '}, {'moodle_course_id': '-1'},
])
def test_invalid_inputs_are_422(client, portrait_bytes, extra):
    response = client.post('/lectures', data=fields(client) | extra,
                           files={'portrait': ('p.png', portrait_bytes, 'image/png')})
    assert response.status_code == 422


def test_csrf_required(client, portrait_bytes):
    response = client.post('/lectures', data=fields(client) | {'csrf_token': 'wrong'},
                           files={'portrait': ('p.png', portrait_bytes, 'image/png')})
    assert response.status_code == 403


def test_bad_portrait_rejected(client):
    response = client.post('/lectures', data=fields(client), files={'portrait': ('p.png', b'not-image', 'image/png')})
    assert response.status_code == 422


def test_credentials_url_rejected_before_network(client):
    response = client.post('/settings/credentials/moodle', data={
        'secret': 'test-token', 'base_url': 'https://169.254.169.254',
        'csrf_token': csrf(client.get('/settings/credentials'))})
    assert response.status_code == 422


def test_system_openai_key_is_not_a_user_fallback(portrait_bytes, monkeypatch):
    monkeypatch.setenv("OPENAI_KEY_MODE", "user")
    from app import app
    with TestClient(app) as anonymous_client:
        token = csrf(anonymous_client.get('/register'))
        response = anonymous_client.post('/register', data={
            'email': 'no-key@example.test', 'name': 'No Key',
            'password': 'test-password-123', 'password_confirm': 'test-password-123',
            'csrf_token': token,
        })
        assert response.status_code == 200
        response = anonymous_client.post(
            '/lectures', data=fields(anonymous_client),
            files={'portrait': ('p.png', portrait_bytes, 'image/png')},
        )
        assert response.status_code == 422
        assert 'OpenAI API Key' in response.text


async def test_disabled_account_session_is_invalidated(client):
    db = await get_connection()
    try:
        await db.execute("UPDATE users SET status='disabled' WHERE email='route@example.test'")
        await db.commit()
    finally:
        await db.close()
    response = client.get('/dashboard', follow_redirects=False)
    assert response.status_code == 303
    assert response.headers['location'] == '/login'


def test_security_headers_and_self_hosted_tailwind(client):
    response = client.get('/dashboard')
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['x-frame-options'] == 'DENY'
    assert "frame-ancestors 'none'" in response.headers['content-security-policy']
    assert 'cdn.tailwindcss.com' not in response.text
    css = client.get('/static/tailwind.css')
    assert css.status_code == 200
    assert '.bg-slate-50' in css.text


def test_login_rate_limit_returns_429():
    from app import app
    with TestClient(app) as anonymous_client:
        token = csrf(anonymous_client.get('/login'))
        response = None
        for _ in range(11):
            response = anonymous_client.post('/login', data={
                'email': 'rate-limit@example.test',
                'password': 'wrong-password',
                'csrf_token': token,
            })
        assert response is not None
        assert response.status_code == 429
        assert int(response.headers['retry-after']) >= 1


def test_server_openai_key_mode_uses_server_key(monkeypatch):
    import asyncio

    from modules.credentials.required import require_user_openai_api_key

    monkeypatch.setenv("OPENAI_KEY_MODE", "server")
    monkeypatch.setenv("SERVER_OPENAI_API_KEY", "server-owned-key")
    assert asyncio.run(require_user_openai_api_key(999)) == "server-owned-key"


def test_invalid_openai_key_is_not_saved(monkeypatch):
    async def invalid_key(_key):
        raise RuntimeError("invalid")
    monkeypatch.setattr("modules.credentials.routes.validate_openai_api_key", invalid_key)

    from app import app
    with TestClient(app) as anonymous_client:
        token = csrf(anonymous_client.get('/register'))
        anonymous_client.post('/register', data={
            'email': 'bad-key@example.test', 'name': 'Bad Key',
            'password': 'test-password-123', 'password_confirm': 'test-password-123',
            'csrf_token': token,
        })
        response = anonymous_client.post('/settings/credentials/openai', data={
            'secret': 'bad-secret-key',
            'csrf_token': csrf(anonymous_client.get('/settings/credentials')),
        })
        assert response.status_code == 422
        assert 'bad-secret-key' not in response.text
