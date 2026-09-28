"""Backward-compatible facade for avatar background preparation.

Implementation lives in :mod:`modules.lecture.avatar_background` so detection,
segmentation, canvas normalization, and chroma composition can evolve
independently without changing existing imports.
"""

from .avatar_background.chroma import (
    composite_on_chroma,
)
from .avatar_background.detection import (
    detect_avatar_input,
)
from .avatar_background.preparation import prepare_avatar_source
from .avatar_background.removal import remove_portrait_background
from .avatar_background.types import AvatarPreparation

__all__ = [
    "AvatarPreparation",
    "composite_on_chroma",
    "detect_avatar_input",
    "prepare_avatar_source",
    "remove_portrait_background",
]
