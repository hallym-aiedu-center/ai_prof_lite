from modules.auth import service
from modules.auth.rate_limit import SlidingWindowRateLimiter


def test_sliding_window_rate_limiter_blocks_burst_and_recovers():
    limiter = SlidingWindowRateLimiter(limit=2, window_seconds=10)
    assert limiter.consume("client", now=0) == (True, 0)
    assert limiter.consume("client", now=1) == (True, 0)
    allowed, retry_after = limiter.consume("client", now=2)
    assert not allowed
    assert retry_after == 8
    assert limiter.consume("client", now=11) == (True, 0)


async def test_password_hashing_and_verification_are_offloaded(database, monkeypatch):
    calls = []

    class FakeHasher:
        def hash(self, password):
            return "hashed:" + password

        def verify(self, password_hash, password):
            if password_hash != "hashed:" + password:
                raise AssertionError("unexpected password")
            return True

        def check_needs_rehash(self, password_hash):
            return False

    async def fake_to_thread(func, *args):
        calls.append(func.__name__)
        return func(*args)

    monkeypatch.setattr(service, "_password_hasher", FakeHasher())
    monkeypatch.setattr(service.asyncio, "to_thread", fake_to_thread)

    await service.register_user(
        email="thread@example.test",
        password="password-123",
        name="Thread Test",
    )
    user = await service.authenticate_user(
        email="thread@example.test",
        password="password-123",
    )

    assert user is not None
    assert calls == ["hash", "verify", "check_needs_rehash"]


def test_registration_code_blocks_wrong_code(monkeypatch):
    import re
    from fastapi.testclient import TestClient
    from app import app

    monkeypatch.setenv("REGISTRATION_CODE", "lab-code-123")
    with TestClient(app) as client:
        page = client.get('/register')
        assert '가입 코드' in page.text
        token = re.search(r'name="csrf_token"\s+value="([^"]+)"', page.text)[1]
        denied = client.post('/register', data={
            'email': 'blocked@example.test',
            'password': 'password-123',
            'password_confirm': 'password-123',
            'registration_code_input': 'wrong',
            'csrf_token': token,
        })
        assert denied.status_code == 403
        assert '가입 코드가 올바르지 않습니다.' in denied.text

        token = re.search(r'name="csrf_token"\s+value="([^"]+)"', denied.text)[1]
        allowed = client.post('/register', data={
            'email': 'allowed@example.test',
            'password': 'password-123',
            'password_confirm': 'password-123',
            'registration_code_input': 'lab-code-123',
            'csrf_token': token,
        })
        assert allowed.status_code == 200
