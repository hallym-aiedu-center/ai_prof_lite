"""Backward-compatible facade for avatar background preparation.

Implementation lives in :mod:`modules.lecture.avatar_background` so detection,
segmentation, canvas normalization, and chroma composition can evolve
independently without changing existing imports.
"""

from .avatar_background.canvas import (
    _feather_bottom_alpha,
    _presenter_canvas,
    _save_normalized_transparent,
    _trim_alpha,
)
from .avatar_background.chroma import (
    _auto_chroma_rgb,
    _foreground_bbox_from_chroma,
    _normalize_existing_chroma,
    _resolve_output_chroma_rgb,
    composite_on_chroma,
)
from .avatar_background.config import _env_bool, _env_float, _env_int
from .avatar_background.detection import (
    _blue_like,
    _border_pixels,
    _green_like,
    _hex_color,
    _parse_forced_chroma_color,
    _representative_color,
    _resolve_input_decision,
    _thumbnail_rgba,
    detect_avatar_input,
)
from .avatar_background.preparation import prepare_avatar_source
from .avatar_background.removal import _rembg_session, remove_portrait_background
from .avatar_background.types import AvatarPreparation

__all__ = [
    "AvatarPreparation",
    "composite_on_chroma",
    "detect_avatar_input",
    "prepare_avatar_source",
    "remove_portrait_background",
]
