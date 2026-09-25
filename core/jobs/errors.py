import asyncio
import httpx
from openai import APIConnectionError, APIStatusError


class AmbiguousDeploymentError(RuntimeError):
    """A remote creation might have succeeded; never blindly repeat it."""


def retryable(error: Exception) -> bool:
    if isinstance(error, AmbiguousDeploymentError):
        return False
    if isinstance(error, (asyncio.TimeoutError, TimeoutError, APIConnectionError, httpx.TransportError)):
        return True
    if isinstance(error, APIStatusError):
        return error.status_code in {408, 409, 429} or error.status_code >= 500
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in {408, 429} or error.response.status_code >= 500
    return False
