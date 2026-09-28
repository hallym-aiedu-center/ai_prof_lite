from __future__ import annotations

import os


def _money_env(name: str, default: float) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError:
        value = default
    return max(0.0, value)


def estimate_lecture_cost_usd(*, target_duration_minutes: int, target_slide_count: int, generate_images: bool) -> float:
    """Return an operator-configurable planning estimate, not provider billing data.

    Prices change and models are selectable, so the application deliberately keeps
    the coefficients in environment variables.  The estimate is used as an
    admission-control budget before a job is queued.
    """
    text_base = _money_env("LECTURE_EST_TEXT_BASE_USD", 0.35)
    image_per_slide = _money_env("LECTURE_EST_IMAGE_PER_SLIDE_USD", 0.12)
    tts_per_minute = _money_env("LECTURE_EST_TTS_PER_MINUTE_USD", 0.03)
    retry_buffer = _money_env("LECTURE_EST_RETRY_BUFFER_RATIO", 0.20)

    subtotal = text_base + (max(0, int(target_duration_minutes)) * tts_per_minute)
    if generate_images:
        subtotal += max(0, int(target_slide_count)) * image_per_slide
    return round(subtotal * (1.0 + retry_buffer), 2)


def cost_estimate_config() -> dict[str, float]:
    return {
        "text_base": _money_env("LECTURE_EST_TEXT_BASE_USD", 0.35),
        "image_per_slide": _money_env("LECTURE_EST_IMAGE_PER_SLIDE_USD", 0.12),
        "tts_per_minute": _money_env("LECTURE_EST_TTS_PER_MINUTE_USD", 0.03),
        "retry_buffer_ratio": _money_env("LECTURE_EST_RETRY_BUFFER_RATIO", 0.20),
    }
