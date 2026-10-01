from __future__ import annotations

from typing import Any

from fastapi.templating import Jinja2Templates
from jinja2 import pass_context

from core.config import PROJECT_ROOT
from core.lang import (
    AUTO_LANGUAGE,
    SUPPORTED_LANGUAGES,
    language_preference,
    resolve_language,
    translate,
)

templates = Jinja2Templates(directory=str(PROJECT_ROOT / "templates"))


def _context_request(context: Any):
    try:
        return context.get("request")
    except AttributeError:
        return None


def _context_user(context: Any):
    try:
        return context.get("user")
    except AttributeError:
        return None


@pass_context
def t(context: Any, key: str, **values: object) -> str:
    language = resolve_language(_context_request(context), _context_user(context))
    return translate(key, language, **values)


@pass_context
def current_language(context: Any) -> str:
    return resolve_language(_context_request(context), _context_user(context))


@pass_context
def current_language_preference(context: Any) -> str:
    return language_preference(_context_user(context))


def language_options() -> tuple[tuple[str, str], ...]:
    return ((AUTO_LANGUAGE, "Auto"), *SUPPORTED_LANGUAGES.items())


templates.env.globals.update(
    t=t,
    current_language=current_language,
    current_language_preference=current_language_preference,
    language_options=language_options,
)
