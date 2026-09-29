"""Shared web/worker configuration. Relative paths are project-relative."""
import math
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def project_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def data_dir() -> Path:
    return project_path(os.getenv("DATA_DIR", "data"))


def positive_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


def job_gpu_ids(*, concurrency: int | None = None) -> list[str]:
    """Return the physical GPU ids reserved for lecture jobs.

    JOB_GPU_IDS accepts ordinary CUDA indices (``0,1,2,3``), GPU UUIDs, or
    MIG UUIDs.  When it is omitted, a single legacy DITTO_GPU is respected for
    one-slot deployments; otherwise ids default to ``0..JOB_CONCURRENCY-1``.
    """
    slots = concurrency or positive_int("JOB_CONCURRENCY", 4)
    raw = os.getenv("JOB_GPU_IDS", "").strip()
    legacy = os.getenv("DITTO_GPU", "").strip()

    if raw:
        values = [item.strip() for item in raw.split(",") if item.strip()]
    elif legacy and slots == 1:
        values = [legacy]
    else:
        values = [str(index) for index in range(slots)]

    if not values:
        raise ValueError("JOB_GPU_IDS must contain at least one GPU id")
    if len(set(values)) != len(values):
        raise ValueError("JOB_GPU_IDS must not contain duplicate GPU ids")
    if len(values) < slots:
        raise ValueError(
            "JOB_GPU_IDS must contain at least JOB_CONCURRENCY entries "
            f"(got {len(values)} GPU ids for {slots} slots)"
        )
    return values[:slots]


def registration_code() -> str:
    """Optional shared code required for new account registration."""
    return os.getenv("REGISTRATION_CODE", "").strip()


def openai_key_mode() -> str:
    """Return the configured OpenAI credential policy: ``user`` or ``server``."""
    mode = os.getenv("OPENAI_KEY_MODE", "user").strip().lower() or "user"
    if mode not in {"user", "server"}:
        raise ValueError("OPENAI_KEY_MODE must be either 'user' or 'server'")
    return mode


def server_openai_account_budget_usd() -> float | None:
    """Return the per-account budget enforced in server-key mode.

    Every account receives the same configured ceiling, but usage is still
    accounted independently per user. An empty value disables the ceiling.
    """
    raw = os.getenv("SERVER_OPENAI_ACCOUNT_BUDGET_USD", "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError("SERVER_OPENAI_ACCOUNT_BUDGET_USD must be a number") from exc
    if not math.isfinite(value) or value <= 0 or value > 100000:
        raise ValueError(
            "SERVER_OPENAI_ACCOUNT_BUDGET_USD must be greater than 0 and at most 100000"
        )
    return round(value, 2)


def session_secret() -> str:
    secret = os.getenv("SESSION_SECRET", "").strip()
    if (
        len(secret) < 32
        or secret in {"dev-only-change-me", "change-me"}
        or secret.startswith("replace-with")
    ):
        raise RuntimeError(
            "SESSION_SECRET must be a random secret of at least 32 characters."
        )
    return secret
