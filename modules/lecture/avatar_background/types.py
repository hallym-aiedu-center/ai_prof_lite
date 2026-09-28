from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AvatarPreparation:
    """Normalized source information used by Ditto and final composition."""

    input_mode: str
    ditto_source: Path
    transparent_foreground: Path | None
    chroma_color: str
    detection_score: float
