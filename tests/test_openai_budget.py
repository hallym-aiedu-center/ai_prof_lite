import io
import wave
from types import SimpleNamespace

import pytest

from core.database.client import get_connection
from core.openai.usage import (
    OpenAIBudgetExceeded,
    embeddings_create,
    finalize_usage,
    images_generate,
    reserve_usage,
    responses_create,
    speech_create_bytes,
    usage_summary,
)


async def _set_budget(user_id: int, amount: float | None):
    db = await get_connection()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO user_settings(user_id, language, openai_budget_usd) VALUES(?, 'ko', ?)",
            (user_id, amount),
        )
        await db.commit()
    finally:
        await db.close()


async def _events(user_id: int):
    db = await get_connection()
    try:
        return await (await db.execute(
            "SELECT * FROM openai_usage_events WHERE user_id=? ORDER BY id", (user_id,)
        )).fetchall()
    finally:
        await db.close()


async def test_user_budget_blocks_concurrent_reserved_spend(database):
    await _set_budget(1, 1.00)
    first = await reserve_usage(user_id=1, kind="responses", model="gpt-5.1", reserve_usd=0.70)
    with pytest.raises(OpenAIBudgetExceeded):
        await reserve_usage(user_id=1, kind="images", model="gpt-image-2", reserve_usd=0.31)
    await finalize_usage(first, cost_usd=0.40)
    second = await reserve_usage(user_id=1, kind="images", model="gpt-image-2", reserve_usd=0.50)
    assert second > first
    summary = await usage_summary(1)
    assert summary["spent"] == pytest.approx(0.40)
    assert summary["reserved"] == pytest.approx(0.50)
    assert summary["remaining"] == pytest.approx(0.10)


async def test_response_cost_uses_selected_model_and_actual_usage(database, monkeypatch):
    await _set_budget(1, 2.00)
    monkeypatch.setenv("OPENAI_RESPONSE_RESERVE_MIN_USD", "0.000001")
    response = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=1000,
            output_tokens=500,
            input_tokens_details=SimpleNamespace(cached_tokens=200),
        ),
        output_text="ok",
        _request_id="req_resp_123",
    )

    class InputTokens:
        async def create(self, **kwargs):
            return SimpleNamespace(input_tokens=321)

    class Responses:
        def __init__(self):
            self.input_tokens = InputTokens()
        async def create(self, **kwargs):
            return response

    client = SimpleNamespace(responses=Responses())
    await responses_create(
        client,
        user_id=1,
        model="gpt-5.1",
        input="x",
        max_output_tokens=500,
        usage_context={"operation": "unit_response", "stage": "tests", "item_key": "response_case", "item_index": 1},
    )

    summary = await usage_summary(1)
    expected = ((800 * 1.25) + (200 * 0.125) + (500 * 10.0)) / 1_000_000
    assert summary["spent"] == pytest.approx(expected)
    assert summary["reserved"] == 0
    rows = await _events(1)
    assert rows[-1]["model"] == "gpt-5.1"
    assert rows[-1]["input_tokens"] == 1000
    assert rows[-1]["cached_input_tokens"] == 200
    assert rows[-1]["output_tokens"] == 500
    assert rows[-1]["operation"] == "unit_response"
    assert rows[-1]["stage"] == "tests"
    assert rows[-1]["item_key"] == "response_case"
    assert rows[-1]["request_id"] == "req_resp_123"


async def test_embedding_usage_is_added_to_same_account_ledger(database):
    await _set_budget(1, 1.00)
    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=250, total_tokens=250),
        data=[SimpleNamespace(embedding=[1.0, 0.0])],
        _request_id="req_embed_123",
    )

    class Embeddings:
        async def create(self, **kwargs):
            return response

    client = SimpleNamespace(embeddings=Embeddings())
    result = await embeddings_create(
        client,
        user_id=1,
        model="text-embedding-3-small",
        input=["semantic reference"],
        usage_context={"operation": "unit_embedding", "stage": "tests", "item_key": "embed_1"},
    )
    assert result is response
    summary = await usage_summary(1)
    assert summary["spent"] == pytest.approx(250 * 0.02 / 1_000_000)
    row = (await _events(1))[-1]
    assert row["kind"] == "embeddings"
    assert row["model"] == "text-embedding-3-small"
    assert row["input_tokens"] == 250
    assert row["operation"] == "unit_embedding"
    assert row["request_id"] == "req_embed_123"


async def test_image_generation_uses_model_quality_size_price_when_usage_missing(database):
    await _set_budget(1, 1.00)
    response = SimpleNamespace(data=[SimpleNamespace(b64_json="unused")], _request_id="req_img_123")

    class Images:
        async def generate(self, **kwargs):
            return response

    client = SimpleNamespace(images=Images())
    await images_generate(
        client,
        user_id=1,
        model="gpt-image-2",
        prompt="diagram",
        quality="low",
        size="1024x1024",
        usage_context={"operation": "unit_image", "stage": "tests", "item_key": "image_1"},
    )
    summary = await usage_summary(1)
    # Fixed image output price + a very small prompt-token input component.
    assert summary["spent"] >= 0.006
    assert summary["spent"] < 0.0061
    row = (await _events(1))[-1]
    assert row["kind"] == "images"
    assert row["model"] == "gpt-image-2"
    assert row["operation"] == "unit_image"
    assert row["request_id"] == "req_img_123"


def _wav_bytes(seconds: float = 1.0, sample_rate: int = 8000) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00\x00" * int(sample_rate * seconds))
    return output.getvalue()


async def test_tts_usage_is_added_to_same_account_ledger(database):
    await _set_budget(1, 1.00)
    audio = _wav_bytes(1.0)

    class Speech:
        async def create(self, **kwargs):
            return SimpleNamespace(
                content=audio,
                usage=SimpleNamespace(input_tokens=40, output_tokens=20, input_tokens_details=SimpleNamespace(cached_tokens=0)),
                _request_id="req_tts_123",
            )

    client = SimpleNamespace(audio=SimpleNamespace(speech=Speech()))
    result = await speech_create_bytes(
        client,
        user_id=1,
        model="gpt-4o-mini-tts",
        voice="alloy",
        input="테스트 음성",
        response_format="wav",
        usage_context={"operation": "unit_tts", "stage": "tests", "item_key": "tts_1"},
    )
    assert result == audio
    summary = await usage_summary(1)
    assert summary["spent"] > 0
    row = (await _events(1))[-1]
    assert row["kind"] == "tts"
    assert row["model"] == "gpt-4o-mini-tts"
    assert row["status"] == "finalized"
    assert row["input_tokens"] == 40
    assert row["output_tokens"] == 20
    assert row["operation"] == "unit_tts"
    assert row["request_id"] == "req_tts_123"


async def test_budget_gate_stops_provider_call_before_spend(database):
    await _set_budget(1, 0.001)

    class Responses:
        def __init__(self):
            self.called = False
        async def create(self, **kwargs):
            self.called = True
            raise AssertionError("provider must not be called after budget rejection")

    responses = Responses()
    client = SimpleNamespace(responses=responses)
    with pytest.raises(OpenAIBudgetExceeded):
        await responses_create(
            client,
            user_id=1,
            model="gpt-5.1",
            input="large operation",
            max_output_tokens=1000,
        )
    assert responses.called is False


async def test_text_model_selection_changes_accounted_cost(database, monkeypatch):
    await _set_budget(1, 5.00)
    monkeypatch.setenv("OPENAI_RESPONSE_RESERVE_MIN_USD", "0.000001")

    class Responses:
        async def create(self, **kwargs):
            return SimpleNamespace(
                output_text="ok",
                usage=SimpleNamespace(
                    input_tokens=1000,
                    output_tokens=1000,
                    input_tokens_details=SimpleNamespace(cached_tokens=0),
                ),
            )

    client = SimpleNamespace(responses=Responses())
    await responses_create(client, user_id=1, model="gpt-5.1", input="x", max_output_tokens=1000)
    await responses_create(client, user_id=1, model="gpt-4.1", input="x", max_output_tokens=1000)

    rows = await _events(1)
    by_model = {row["model"]: row["cost_usd"] for row in rows if row["kind"] == "responses"}
    assert by_model["gpt-5.1"] == pytest.approx((1.25 + 10.0) / 1000)
    assert by_model["gpt-4.1"] == pytest.approx((2.0 + 8.0) / 1000)
    assert by_model["gpt-5.1"] != by_model["gpt-4.1"]


async def test_response_reservation_uses_input_token_counter_when_available(database, monkeypatch):
    await _set_budget(1, 1.00)
    monkeypatch.setenv("OPENAI_RESPONSE_RESERVE_MIN_USD", "0.000001")

    class InputTokens:
        def __init__(self):
            self.calls = []
        async def create(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(input_tokens=777)

    class Responses:
        def __init__(self):
            self.input_tokens = InputTokens()
        async def create(self, **kwargs):
            return SimpleNamespace(
                output_text="ok",
                usage=SimpleNamespace(
                    input_tokens=777,
                    output_tokens=50,
                    input_tokens_details=SimpleNamespace(cached_tokens=0),
                ),
            )

    responses = Responses()
    client = SimpleNamespace(responses=responses)
    await responses_create(client, user_id=1, model="gpt-5.1", input="hello", max_output_tokens=50)
    assert len(responses.input_tokens.calls) == 1
    assert responses.input_tokens.calls[0]["model"] == "gpt-5.1"
    assert responses.input_tokens.calls[0]["input"] == "hello"



def test_paid_openai_calls_are_centralized_in_usage_layer():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    direct_patterns = (
        ".responses.create(",
        ".embeddings.create(",
        ".images.generate(",
        ".audio.speech.create(",
        ".chat.completions.create(",
        ".completions.create(",
    )
    offenders = []
    for package in (root / "modules",):
        for path in package.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if any(pattern in text for pattern in direct_patterns):
                offenders.append(str(path.relative_to(root)))
    assert offenders == []


async def test_server_mode_applies_same_budget_independently_per_account(database, monkeypatch):
    db = await get_connection()
    try:
        await db.execute("INSERT INTO users(id,email,password_hash) VALUES(2,'second@example.test','unused')")
        await db.commit()
    finally:
        await db.close()

    monkeypatch.setenv("OPENAI_KEY_MODE", "server")
    monkeypatch.setenv("SERVER_OPENAI_ACCOUNT_BUDGET_USD", "1.00")

    first = await reserve_usage(user_id=1, kind="responses", model="gpt-5.1", reserve_usd=0.80)
    second = await reserve_usage(user_id=2, kind="responses", model="gpt-5.1", reserve_usd=0.80)
    assert first != second

    with pytest.raises(OpenAIBudgetExceeded):
        await reserve_usage(user_id=1, kind="images", model="gpt-image-2", reserve_usd=0.21)
    with pytest.raises(OpenAIBudgetExceeded):
        await reserve_usage(user_id=2, kind="images", model="gpt-image-2", reserve_usd=0.21)

    summary1 = await usage_summary(1)
    summary2 = await usage_summary(2)
    assert summary1["budget"] == pytest.approx(1.0)
    assert summary2["budget"] == pytest.approx(1.0)
    assert summary1["reserved"] == pytest.approx(0.8)
    assert summary2["reserved"] == pytest.approx(0.8)


async def test_ambiguous_openai_failure_preserves_reservation_and_is_not_retryable(database):
    import httpx

    from core.jobs.errors import retryable
    from core.openai.usage import OpenAIAmbiguousRequestError

    await _set_budget(1, 1.00)

    class Responses:
        async def create(self, **kwargs):
            request = httpx.Request("POST", "https://api.openai.com/v1/responses")
            raise httpx.ReadTimeout("response timed out", request=request)

    client = SimpleNamespace(responses=Responses())
    with pytest.raises(OpenAIAmbiguousRequestError) as caught:
        await responses_create(
            client,
            user_id=1,
            model="gpt-5.1",
            input="ambiguous",
            max_output_tokens=100,
        )

    assert retryable(caught.value) is False
    rows = await _events(1)
    assert rows[-1]["status"] == "ambiguous"
    assert rows[-1]["reserved_cost_usd"] > 0
    summary = await usage_summary(1)
    assert summary["reserved"] == pytest.approx(rows[-1]["reserved_cost_usd"])
