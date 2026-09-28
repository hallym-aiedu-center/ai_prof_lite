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




def install_usage_passthrough(monkeypatch):
    async def passthrough(client, **kwargs):
        kwargs.pop("user_id", None)
        kwargs.pop("lecture_id", None)
        kwargs.pop("budget_input_bytes", None)
        return await client.responses.create(**kwargs)
    monkeypatch.setattr(planner, "responses_create", passthrough)

def error(cls, status, body):
    request = httpx.Request('POST', 'https://api.openai.com/v1/responses')
    return cls(str(body), response=httpx.Response(status, request=request), body=body)


async def invoke(monkeypatch, responses):
    client = Client(responses)
    monkeypatch.setattr(planner, 'get_client', lambda **_: client)
    install_usage_passthrough(monkeypatch)
    return client, planner.create_lecture_plan(
        api_key='test', title='title', topic='topic', model='test', target_slide_count=4, user_id=1
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

async def test_expand_narrations_preserves_structure_and_never_shortens(monkeypatch, plan):
    revised = {
        "narrations": [
            "짧음",
            "test narration " + "상세 설명 " * 8,
            "test narration " + "사례 설명 " * 8,
            "test narration " + "정리 설명 " * 8,
        ]
    }
    client = Client([SimpleNamespace(output_text=json.dumps(revised, ensure_ascii=False))])
    monkeypatch.setattr(planner, 'get_client', lambda **_: client)
    install_usage_passthrough(monkeypatch)

    result = await planner.expand_lecture_narrations(
        api_key='test',
        plan=plan,
        model='test',
        actual_duration_seconds=1800,
        minimum_duration_seconds=2400,
        attempt=1,
        user_id=1,
    )

    assert result is not plan
    assert result['slides'][0]['narration'] == plan['slides'][0]['narration']
    assert len(result['slides'][1]['narration']) > len(plan['slides'][1]['narration'])
    assert [s['title'] for s in result['slides']] == [s['title'] for s in plan['slides']]
    assert result['quiz'] == plan['quiz']
    assert client.responses.create.await_count == 1
    prompt = client.responses.create.call_args.kwargs['input']
    assert '최소 재생시간: 40.00분' in prompt
    assert '안전 목표: 약 42.00분' in prompt


async def test_reference_context_is_used_without_a_second_review_call(monkeypatch, plan):
    client = Client([SimpleNamespace(output_text=json.dumps(plan, ensure_ascii=False))])
    monkeypatch.setattr(planner, 'get_client', lambda **_: client)
    install_usage_passthrough(monkeypatch)
    result = await planner.create_lecture_plan(
        api_key='test',
        title='title',
        topic='topic',
        model='test',
        target_slide_count=4,
        reference_context='REFERENCE FACT: alpha is beta',
        user_id=1,
    )
    assert result == plan
    assert client.responses.create.await_count == 1
    prompt = client.responses.create.call_args.kwargs['input']
    assert 'REFERENCE FACT: alpha is beta' in prompt
