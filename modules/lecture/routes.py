"""Lecture route composition.

The route handlers are split by creation/listing and detail/artifact concerns.
This module keeps the original ``router`` import stable for the application.
"""

from fastapi import APIRouter

from .routes_create import (
    lecture_list,
    new_lecture,
    submit_lecture,
)
from .routes_create import (
    router as create_router,
)
from .routes_detail import (
    approve_lecture_review,
    cancel_lecture,
    download_artifact,
    download_quiz,
    lecture_detail,
    lecture_queue_status,
    lecture_slide_preview,
    lecture_status,
    retry_lecture,
    update_lecture_review,
)
from .routes_detail import (
    router as detail_router,
)

router = APIRouter()
router.include_router(create_router, prefix="/lectures")
router.include_router(detail_router, prefix="/lectures")

__all__ = [
    "approve_lecture_review",
    "cancel_lecture",
    "download_artifact",
    "download_quiz",
    "lecture_detail",
    "lecture_list",
    "lecture_queue_status",
    "lecture_slide_preview",
    "lecture_status",
    "new_lecture",
    "retry_lecture",
    "router",
    "submit_lecture",
    "update_lecture_review",
]
