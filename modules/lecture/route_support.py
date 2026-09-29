from fastapi import Request
from fastapi.templating import Jinja2Templates

from core.config import PROJECT_ROOT as TEMPLATE_ROOT
from core.config import job_gpu_ids, positive_int

templates = Jinja2Templates(directory=str(TEMPLATE_ROOT / "templates"))


def _wants_json(request: Request) -> bool:
    return (
        "application/json" in request.headers.get("accept", "").lower()
        or request.query_params.get("ajax") == "1"
    )


def _queue_runtime_config() -> dict:
    slots = positive_int("JOB_CONCURRENCY", 4)
    try:
        gpu_ids = job_gpu_ids(concurrency=slots)
        error = None
    except ValueError as exc:
        gpu_ids = []
        error = str(exc)
    return {
        "capacity": slots,
        "gpu_ids": gpu_ids,
        "config_error": error,
    }
