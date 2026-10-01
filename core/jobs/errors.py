import asyncio

import httpx
from openai import APIConnectionError, APIStatusError

from core.openai.usage import OpenAIAmbiguousRequestError


class AmbiguousDeploymentError(RuntimeError):
    """A remote creation might have succeeded; never blindly repeat it."""


class PublishNotReadyError(RuntimeError):
    """The scheduled publish time arrived before the final lecture media was ready."""


class PublishSourceFailedError(RuntimeError):
    """The lecture failed before scheduled publication could become ready."""


def retryable(error: Exception) -> bool:
    if isinstance(error, OpenAIAmbiguousRequestError):
        return False
    if isinstance(error, AmbiguousDeploymentError):
        return False
    if isinstance(error, PublishSourceFailedError):
        return False
    if isinstance(error, PublishNotReadyError):
        return True
    if isinstance(
        error,
        (asyncio.TimeoutError, TimeoutError, APIConnectionError, httpx.TransportError),
    ):
        return True
    if isinstance(error, APIStatusError):
        return error.status_code in {408, 409, 429} or error.status_code >= 500
    if isinstance(error, httpx.HTTPStatusError):
        return (
            error.response.status_code in {408, 429}
            or error.response.status_code >= 500
        )
    return False
