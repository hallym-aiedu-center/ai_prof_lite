from pathlib import Path

from PIL import Image

from .canvas import _save_normalized_transparent
from .chroma import _normalize_existing_chroma, composite_on_chroma
from .config import _env_bool
from .detection import _resolve_input_decision
from .removal import remove_portrait_background
from .types import AvatarPreparation


def prepare_avatar_source(
    *,
    source_path: Path,
    output_dir: Path,
) -> AvatarPreparation:
    """Prepare avatar input with automatic background strategy.

    Modes:
    - chroma: green/blue background detected -> skip rembg completely.
    - transparent: existing alpha -> skip rembg, normalize canvas, add chroma.
    - portrait: ordinary photo -> rembg, normalize canvas, add chroma.

    Set AVATAR_INPUT_MODE to force one of these paths when automatic
    classification is not appropriate for a particular deployment.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    decision = _resolve_input_decision(source_path)
    mode = decision["mode"]
    score = float(decision.get("score", 0.0))

    transparent_path = output_dir / "portrait_foreground.png"
    chroma_path = output_dir / "portrait_chroma.png"

    if mode == "chroma":
        chroma_color = str(
            decision.get("chroma_color")
            or "#00FF00"
        )
        _normalize_existing_chroma(
            source_path=source_path,
            output_path=chroma_path,
            chroma_color=chroma_color,
        )
        return AvatarPreparation(
            input_mode="chroma",
            ditto_source=chroma_path,
            transparent_foreground=None,
            chroma_color=chroma_color,
            detection_score=score,
        )

    if mode == "transparent":
        _save_normalized_transparent(
            source_path=source_path,
            transparent_path=transparent_path,
        )
        chroma_path, chroma_color = composite_on_chroma(
            transparent_path=transparent_path,
            chroma_path=chroma_path,
        )
        return AvatarPreparation(
            input_mode="transparent",
            ditto_source=chroma_path,
            transparent_foreground=transparent_path,
            chroma_color=chroma_color,
            detection_score=score,
        )

    required = _env_bool(
        "BACKGROUND_REMOVAL_REQUIRED",
        True,
    )
    raw_removed = output_dir / "portrait_removed_raw.png"

    try:
        remove_portrait_background(
            source_path=source_path,
            transparent_path=raw_removed,
        )
    except Exception:
        if required:
            raise
        with Image.open(source_path) as image:
            image.convert("RGBA").save(
                raw_removed,
                format="PNG",
            )

    _save_normalized_transparent(
        source_path=raw_removed,
        transparent_path=transparent_path,
    )
    chroma_path, chroma_color = composite_on_chroma(
        transparent_path=transparent_path,
        chroma_path=chroma_path,
    )
    return AvatarPreparation(
        input_mode="portrait",
        ditto_source=chroma_path,
        transparent_foreground=transparent_path,
        chroma_color=chroma_color,
        detection_score=score,
    )
