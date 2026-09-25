import os

from openai import AsyncOpenAI


def get_client(*, api_key: str) -> AsyncOpenAI:
    """Build an OpenAI client from an explicitly supplied credential only."""
    key = str(api_key or "").strip()
    if not key:
        raise RuntimeError("An explicit OpenAI API key is required.")
    return AsyncOpenAI(
        api_key=key,
        max_retries=0,
        timeout=float(os.getenv("OPENAI_TIMEOUT_SECONDS", "120")),
    )


def get_realtime_connection(*, model: str, api_key: str):
    client = get_client(api_key=api_key)
    return client.realtime.connect(model=model)
