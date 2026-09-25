from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from core.jobs.factory import get_queue
from modules.auth.session import current_user_id, get_csrf_token, login_redirect, verify_csrf
from modules.lecture.repository import get_lecture, list_lecture_queue_status
from modules.lecture.route_support import _queue_runtime_config, templates
from modules.users.service import get_user


router = APIRouter()


@router.get("/api/queue-status")
async def lecture_queue_status(request: Request):
    user_id = current_user_id(request)
    if user_id is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    lectures = await list_lecture_queue_status(user_id=user_id, limit=30)
    return {
        **_queue_runtime_config(),
        "lectures": [
            {
                **lecture,
                "detail_url": f"/lectures/{lecture['id']}",
            }
            for lecture in lectures
        ],
    }


@router.get(
    "/{lecture_id}"
)
async def lecture_detail(
    request: Request,
    lecture_id: int,
):
    user_id = current_user_id(
        request
    )

    if user_id is None:
        return login_redirect()

    lecture = await get_lecture(
        lecture_id,
        user_id=user_id,
    )

    if lecture is None:
        return RedirectResponse(
            url="/lectures",
            status_code=303,
        )

    return templates.TemplateResponse(
        request=request,
        name="lectures/detail.html",
        context={
            "user": await get_user(
                user_id
            ),
            "lecture": lecture,
            "active_page": "lectures",
            "csrf_token": get_csrf_token(
                request
            ),
        },
    )


@router.get(
    "/{lecture_id}/status"
)
async def lecture_status(
    request: Request,
    lecture_id: int,
):
    user_id = current_user_id(
        request
    )

    if user_id is None:
        return JSONResponse(
            {
                "error": "unauthorized"
            },
            status_code=401,
        )

    lecture = await get_lecture(
        lecture_id,
        user_id=user_id,
    )

    if lecture is None:
        return JSONResponse(
            {
                "error": "not_found"
            },
            status_code=404,
        )

    return {
        "id": lecture["id"],
        "status": lecture["status"],
        "progress": lecture[
            "progress"
        ],
        "status_message": lecture[
            "status_message"
        ],
        "error_message": lecture[
            "error_message"
        ],
        "moodle_videotracker_cmid": lecture.get(
            "moodle_videotracker_cmid"
        ),
        "completed": (
            lecture["status"]
            == "completed"
        ),
        "failed": (
            lecture["status"]
            == "failed"
        ),
    }


ARTIFACT_FIELDS = {
    "pptx": "pptx_path",
    "video": "final_video_path",
    "audio": "narration_path",
    "avatar": "avatar_path",
}


@router.get(
    "/{lecture_id}/download/{kind}"
)
async def download_artifact(
    request: Request,
    lecture_id: int,
    kind: str,
):
    user_id = current_user_id(
        request
    )

    if user_id is None:
        return login_redirect()

    lecture = await get_lecture(
        lecture_id,
        user_id=user_id,
    )

    if lecture is None:
        return RedirectResponse(
            url="/lectures",
            status_code=303,
        )

    field = ARTIFACT_FIELDS.get(
        kind
    )

    if (
        not field
        or not lecture.get(field)
    ):
        return RedirectResponse(
            url=(
                f"/lectures/{lecture_id}"
            ),
            status_code=303,
        )

    path = Path(
        lecture[field]
    )

    if not path.exists():
        return RedirectResponse(
            url=(
                f"/lectures/{lecture_id}"
            ),
            status_code=303,
        )

    return FileResponse(
        path,
        filename=path.name,
    )


@router.get(
    "/{lecture_id}/quiz.json"
)
async def download_quiz(
    request: Request,
    lecture_id: int,
):
    user_id = current_user_id(
        request
    )

    if user_id is None:
        return login_redirect()

    lecture = await get_lecture(
        lecture_id,
        user_id=user_id,
    )

    if lecture is None:
        return RedirectResponse(
            url="/lectures",
            status_code=303,
        )

    if lecture.get("quiz_json") is None:
        raise HTTPException(404, "생성된 퀴즈가 없습니다.")
    return JSONResponse(
        content=lecture["quiz_json"],
        headers={"Content-Disposition": f'attachment; filename="lecture_{lecture_id}_quiz.json"'},
    )


@router.post("/{lecture_id}/retry")
async def retry_lecture(request: Request, lecture_id: int, csrf_token: str = Form(...)):
    user_id = current_user_id(request)
    if user_id is None:
        return login_redirect()
    verify_csrf(request, csrf_token)
    lecture = await get_lecture(lecture_id, user_id=user_id)
    if lecture is None:
        raise HTTPException(404, "강의를 찾을 수 없습니다.")
    if not await get_queue().retry(lecture_id):
        raise HTTPException(409, "실패한 작업만 재시도할 수 있습니다.")
    return RedirectResponse(f"/lectures/{lecture_id}", status_code=303)
