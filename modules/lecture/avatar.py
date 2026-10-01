import os
import sys
from pathlib import Path

from core.config import project_path
from modules.lecture.composer import run_process


def get_ditto_paths():
    project_root = Path(__file__).resolve().parents[2]

    ditto_root = Path(
        os.getenv(
            "DITTO_ROOT",
            str(project_root / "core" / "ditto-talkinghead"),
        )
    )

    data_root = Path(
        os.getenv(
            "DITTO_DATA_ROOT",
            str(ditto_root / "checkpoints" / "ditto_trt_Ampere_Plus"),
        )
    )

    cfg_pkl = Path(
        os.getenv(
            "DITTO_CFG_PKL",
            str(ditto_root / "checkpoints" / "ditto_cfg" / "v0.4_hubert_cfg_trt.pkl"),
        )
    )

    return tuple(project_path(str(p)) for p in (ditto_root, data_root, cfg_pkl))


async def create_avatar_video(
    *,
    portrait_path: Path,
    narration_audio: Path,
    output_path: Path,
) -> Path:
    ditto_root, data_root, cfg_pkl = get_ditto_paths()

    inference = ditto_root / "inference.py"

    required = [
        inference,
        data_root,
        cfg_pkl,
        portrait_path,
        narration_audio,
    ]

    missing = [str(path) for path in required if not path.exists()]

    if missing:
        raise FileNotFoundError("Missing Ditto files:\n" + "\n".join(missing))

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    env = os.environ.copy()

    gpu = os.getenv("DITTO_GPU", "").strip()

    # worker.py pins the entire runner process tree with CUDA_VISIBLE_DEVICES.
    # Keep that assignment authoritative. DITTO_GPU remains a fallback for
    # standalone/manual calls that are not launched by the worker.
    if gpu and not os.getenv("LITE_ASSIGNED_GPU", "").strip():
        env["CUDA_VISIBLE_DEVICES"] = gpu

    await run_process(
        [
            os.getenv("DITTO_PYTHON", sys.executable),
            str(inference),
            "--data_root",
            str(data_root),
            "--cfg_pkl",
            str(cfg_pkl),
            "--audio_path",
            str(narration_audio),
            "--source_path",
            str(portrait_path),
            "--output_path",
            str(output_path),
        ],
        cwd=ditto_root,
        env=env,
    )

    return output_path
