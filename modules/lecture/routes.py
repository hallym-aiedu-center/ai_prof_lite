"""Lecture route composition.

The route handlers are split by creation/listing and detail/artifact concerns.
This module keeps the original ``router`` import stable for the application.
"""

from fastapi import APIRouter

from .route_support import _queue_runtime_config, _wants_json, templates
from .routes_create import (
    lecture_list,
    new_lecture,
    router as create_router,
    submit_lecture,
)
from .routes_detail import (
    ARTIFACT_FIELDS,
    download_artifact,
    download_quiz,
    lecture_detail,
    lecture_queue_status,
    lecture_status,
    retry_lecture,
    router as detail_router,
)


router = APIRouter()
router.include_router(create_router, prefix="/lectures")
router.include_router(detail_router, prefix="/lectures")

__all__ = [
    "download_artifact",
    "download_quiz",
    "lecture_detail",
    "lecture_list",
    "lecture_queue_status",
    "lecture_status",
    "new_lecture",
    "retry_lecture",
    "router",
    "submit_lecture",
]
