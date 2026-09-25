import asyncio
import io
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from fastapi import FastAPI, Request, UploadFile
from PIL import Image
from starlette.datastructures import Headers

from core.body_limit import BodyLimitMiddleware
from core.config import session_secret
from core.moodle.client import MoodleClient
from core.moodle.url_policy import resolve_target
from modules.lecture.uploads import save_portrait


@pytest.mark.parametrize('value', ['', 'dev-only-change-me', 'short'])
def test_unsafe_session_key_fails_startup(monkeypatch, value):
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.setenv('SESSION_SECRET', value)
    with pytest.raises(RuntimeError): session_secret()


@pytest.mark.parametrize('url', [
    'http://example.com', 'https://127.0.0.1', 'https://[::1]',
    'https://169.254.169.254', 'https://10.0.0.1', 'https://[::ffff:127.0.0.1]',
    'file:///etc/passwd', 'https://user:password@example.com', 'https://example.com?q=1',
    'https://example.com/#fragment', 'https://example.com/%2e%2e',
])
async def test_unsafe_moodle_urls_rejected(url):
    with pytest.raises(ValueError): await resolve_target(url)


async def test_dns_private_and_mixed_answers_rejected(monkeypatch):
    loop = asyncio.get_running_loop()
    resolver = AsyncMock(return_value=[(2, 1, 6, '', ('93.184.216.34', 443)),
                                      (2, 1, 6, '', ('127.0.0.1', 443))])
    monkeypatch.setattr(loop, 'getaddrinfo', resolver)
    with pytest.raises(ValueError): await resolve_target('https://public.example')


async def test_private_origin_requires_admin_exact_allowlist(monkeypatch):
    monkeypatch.setenv('MOODLE_PRIVATE_ORIGINS', 'http://10.0.0.5:8080')
    target, _, _ = await resolve_target('http://10.0.0.5:8080/moodle')
    assert target.host == '10.0.0.5'
    with pytest.raises(ValueError): await resolve_target('http://10.0.0.5:8081')
    monkeypatch.setenv('MOODLE_PRIVATE_ORIGINS', 'http://169.254.169.254')
    with pytest.raises(ValueError): await resolve_target('http://169.254.169.254')


async def test_dns_pinned_host_and_tls_sni(monkeypatch):
    resolver = AsyncMock(return_value=[(2, 1, 6, '', ('93.184.216.34', 443))])
    monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', resolver)
    with respx.mock as mock:
        route = mock.post('https://93.184.216.34/moodle/webservice/rest/server.php').respond(200, json={'userid': 1})
        result = await MoodleClient(base_url='https://moodle.example/moodle', token='test').call('site_info')
        assert result['userid'] == 1
        request = route.calls[0].request
        assert request.headers['host'] == 'moodle.example'
        assert request.extensions['sni_hostname'] == 'moodle.example'
        assert resolver.await_count == 1
        assert b'wstoken=test' in request.content


async def test_redirect_not_followed():
    with respx.mock as mock:
        route = mock.post('https://93.184.216.34/webservice/rest/server.php').respond(
            302, headers={'Location': 'http://169.254.169.254/latest/meta-data'})
        with pytest.raises(ValueError, match='리다이렉트'):
            await MoodleClient(base_url='https://93.184.216.34', token='test').call('site_info')
        assert route.call_count == 1 and len(mock.calls) == 1


def upload(content, mime='image/png', filename='portrait.png'):
    return UploadFile(io.BytesIO(content), filename=filename, headers=Headers({'content-type': mime}))


async def test_portrait_decode_and_reencode(portrait_bytes):
    path = await save_portrait(upload(portrait_bytes + b'UNTRUSTED-TRAILER', filename='../../bad.exe'))
    with Image.open(path) as image:
        assert image.format == 'PNG'
    assert b'UNTRUSTED-TRAILER' not in path.read_bytes()
    assert path.name.endswith('.png')


@pytest.mark.parametrize('content,mime', [(b'not an image', 'image/png'), (b'bad', 'application/octet-stream')])
async def test_non_images_rejected(content, mime):
    with pytest.raises(Exception) as caught: await save_portrait(upload(content, mime))
    assert caught.value.status_code == 422


async def test_spoofed_mime_and_pixel_limit(monkeypatch, portrait_bytes):
    with pytest.raises(Exception) as caught: await save_portrait(upload(portrait_bytes, 'image/jpeg'))
    assert caught.value.status_code == 422
    monkeypatch.setenv('MAX_PORTRAIT_PIXELS', '100')
    with pytest.raises(Exception) as caught: await save_portrait(upload(portrait_bytes))
    assert caught.value.status_code == 422


async def test_file_size_limit(monkeypatch, portrait_bytes):
    monkeypatch.setenv('MAX_PORTRAIT_BYTES', '30')
    with pytest.raises(Exception) as caught: await save_portrait(upload(portrait_bytes))
    assert caught.value.status_code == 413


async def test_streaming_body_limit_without_content_length():
    app = FastAPI()
    app.add_middleware(BodyLimitMiddleware, max_bytes=10)
    @app.post('/')
    async def endpoint(request: Request):
        return {'size': len(await request.body())}
    async def chunks():
        yield b'123456'
        yield b'789012'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/', content=chunks())
        assert response.status_code == 413
        response = await client.post('/', content=b'12345678901')
        assert response.status_code == 413
