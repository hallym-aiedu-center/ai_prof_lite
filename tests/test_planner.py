import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from jsonschema import ValidationError
from openai import APITimeoutError, AuthenticationError, BadRequestError, RateLimitError

from modules.lecture import planner


class Client:
    def __init__(self, responses):
        self.responses = SimpleNamespace(create=AsyncMock(side_effect=responses))
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass


def error(cls, status, body):
    request = httpx.Request('POST', 'https://api.openai.com/v1/responses')
    return cls(str(body), response=httpx.Response(status, request=request), body=body)


async def invoke(monkeypatch, responses):
    client = Client(responses)
    monkeypatch.setattr(planner, 'get_client', lambda **_: client)
    return client, planner.create_lecture_plan(
        api_key='test', title='title', topic='topic', model='test', target_slide_count=4
    )


async def test_structured_output_success(monkeypatch, plan):
    client, operation = await invoke(monkeypatch, [SimpleNamespace(output_text=json.dumps(plan))])
    assert await operation == plan
    assert client.responses.create.await_count == 1


async def test_unsupported_format_only_falls_back(monkeypatch, plan):
    failure = error(BadRequestError, 400, {'code': 'unsupported_value', 'param': 'text.format.type', 'message': 'json_schema not supported'})
    client, operation = await invoke(monkeypatch, [failure, SimpleNamespace(output_text=json.dumps(plan))])
    assert await operation == plan
    assert client.responses.create.await_count == 2
    assert 'text' not in client.responses.create.call_args.kwargs


@pytest.mark.parametrize('failure', [
    error(AuthenticationError, 401, {'message': 'bad key'}),
    error(RateLimitError, 429, {'message': 'slow down'}),
    error(BadRequestError, 400, {'code': 'invalid_json_schema', 'param': 'text.format', 'message': 'unsupported schema keyword'}),
    APITimeoutError(request=httpx.Request('POST', 'https://api.openai.com/v1/responses')),
])
async def test_errors_do_not_trigger_second_call(monkeypatch, failure):
    client, operation = await invoke(monkeypatch, [failure])
    with pytest.raises(type(failure)):
        await operation
    assert client.responses.create.await_count == 1


async def test_invalid_fallback_json_rejected_locally(monkeypatch):
    failure = error(BadRequestError, 400, {'param': 'text.format', 'message': 'json_schema is not supported'})
    client, operation = await invoke(monkeypatch, [failure, SimpleNamespace(output_text='{"slides": []}')])
    with pytest.raises(ValidationError):
        await operation
    assert client.responses.create.await_count == 2


async def test_malformed_success_does_not_make_extra_call(monkeypatch):
    client, operation = await invoke(monkeypatch, [SimpleNamespace(output_text='not json')])
    with pytest.raises(json.JSONDecodeError):
        await operation
    assert client.responses.create.await_count == 1
