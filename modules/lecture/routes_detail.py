import copy
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from core.jobs.factory import get_queue
from core.openai.usage import usage_summary
from modules.auth.session import (
    current_user_id,
    get_csrf_token,
    login_redirect,
    verify_csrf,
)
from modules.lecture.checkpoints import get_stage
from modules.lecture.repository import get_lecture, list_lecture_queue_status
from modules.lecture.review import approve_and_resume_review, update_review_plan
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


@router.get("/{lecture_id}")
async def lecture_detail(
    request: Request,
    lecture_id: int,
):
    user_id = current_user_id(request)

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
            "user": await get_user(user_id),
            "lecture": lecture,
            "active_page": "lectures",
            "csrf_token": get_csrf_token(request),
            "openai_usage": await usage_summary(user_id),
        },
    )


@router.get("/{lecture_id}/status")
async def lecture_status(
    request: Request,
    lecture_id: int,
):
    user_id = current_user_id(request)

    if user_id is None:
        return JSONResponse(
            {"error": "unauthorized"},
            status_code=401,
        )

    lecture = await get_lecture(
        lecture_id,
        user_id=user_id,
    )

    if lecture is None:
        return JSONResponse(
            {"error": "not_found"},
            status_code=404,
        )

    return {
        "id": lecture["id"],
        "status": lecture["status"],
        "progress": lecture["progress"],
        "status_message": lecture["status_message"],
        "error_message": lecture["error_message"],
        "moodle_videotracker_cmid": lecture.get("moodle_videotracker_cmid"),
        "completed": (lecture["status"] == "completed"),
        "failed": (lecture["status"] == "failed"),
        "awaiting_review": lecture["status"] == "awaiting_review",
        "cancelled": lecture["status"] == "cancelled",
    }


ARTIFACT_FIELDS = {
    "pptx": "pptx_path",
    "video": "final_video_path",
    "audio": "narration_path",
    "avatar": "avatar_path",
}


@router.get("/{lecture_id}/download/{kind}")
async def download_artifact(
    request: Request,
    lecture_id: int,
    kind: str,
):
    user_id = current_user_id(request)

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

    field = ARTIFACT_FIELDS.get(kind)

    if not field or not lecture.get(field):
        return RedirectResponse(
            url=(f"/lectures/{lecture_id}"),
            status_code=303,
        )

    path = Path(lecture[field])

    if not path.exists():
        return RedirectResponse(
            url=(f"/lectures/{lecture_id}"),
            status_code=303,
        )

    return FileResponse(
        path,
        filename=path.name,
    )


@router.get("/{lecture_id}/quiz.json")
async def download_quiz(
    request: Request,
    lecture_id: int,
):
    user_id = current_user_id(request)

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
        headers={
            "Content-Disposition": f'attachment; filename="lecture_{lecture_id}_quiz.json"'
        },
    )


@router.get("/{lecture_id}/slides/{slide_index}.png")
async def lecture_slide_preview(request: Request, lecture_id: int, slide_index: int):
    user_id = current_user_id(request)
    if user_id is None:
        return login_redirect()
    lecture = await get_lecture(lecture_id, user_id=user_id)
    if lecture is None:
        raise HTTPException(404, "강의를 찾을 수 없습니다.")
    stage = await get_stage(lecture_id, "slides")
    pngs = list((stage or {}).get("outputs", {}).get("pngs") or [])
    if slide_index < 1 or slide_index > len(pngs):
        raise HTTPException(404, "슬라이드 이미지를 찾을 수 없습니다.")
    path = Path(pngs[slide_index - 1])
    if not path.is_file():
        raise HTTPException(404, "슬라이드 이미지 파일이 없습니다.")
    return FileResponse(path, media_type="image/png", filename=path.name)


@router.post("/{lecture_id}/review/approve")
async def approve_lecture_review(
    request: Request, lecture_id: int, csrf_token: str = Form(...)
):
    user_id = current_user_id(request)
    if user_id is None:
        return login_redirect()
    verify_csrf(request, csrf_token)
    lecture = await get_lecture(lecture_id, user_id=user_id)
    if lecture is None:
        raise HTTPException(404, "강의를 찾을 수 없습니다.")
    if lecture.get("status") != "awaiting_review":
        raise HTTPException(409, "현재 PPT 검토 대기 상태가 아닙니다.")
    if not await approve_and_resume_review(lecture_id):
        raise HTTPException(
            409,
            "PPT 승인 또는 작업 재개 상태를 변경할 수 없습니다.",
        )
    return RedirectResponse(f"/lectures/{lecture_id}", status_code=303)


@router.post("/{lecture_id}/review/update")
async def update_lecture_review(request: Request, lecture_id: int):
    user_id = current_user_id(request)
    if user_id is None:
        return login_redirect()
    form = await request.form()
    verify_csrf(request, str(form.get("csrf_token") or ""))
    lecture = await get_lecture(lecture_id, user_id=user_id)
    if lecture is None:
        raise HTTPException(404, "강의를 찾을 수 없습니다.")
    if lecture.get("status") != "awaiting_review" or not lecture.get("plan_json"):
        raise HTTPException(409, "PPT 검토 대기 상태에서만 수정할 수 있습니다.")

    plan = copy.deepcopy(lecture["plan_json"])
    for index, slide in enumerate(plan.get("slides") or [], start=1):
        title = str(form.get(f"slide_{index}_title") or "").strip()
        bullets_raw = str(form.get(f"slide_{index}_bullets") or "")
        narration = str(form.get(f"slide_{index}_narration") or "").strip()
        bullets = [
            line.strip().lstrip("-• ").strip()
            for line in bullets_raw.splitlines()
            if line.strip()
        ]
        if not title or len(title) > 300:
            raise HTTPException(422, f"{index}번 슬라이드 제목은 1~300자로 입력하세요.")
        if not bullets or len(bullets) > 10 or any(len(item) > 500 for item in bullets):
            raise HTTPException(
                422, f"{index}번 슬라이드 bullet은 1~10개, 각 500자 이하로 입력하세요."
            )
        if not narration or len(narration) > 20000:
            raise HTTPException(
                422, f"{index}번 슬라이드 대본은 1~20,000자로 입력하세요."
            )
        slide["title"] = title
        slide["bullets"] = bullets
        slide["narration"] = narration

    try:
        await update_review_plan(lecture_id, plan)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/lectures/{lecture_id}", status_code=303)


@router.post("/{lecture_id}/cancel")
async def cancel_lecture(
    request: Request, lecture_id: int, csrf_token: str = Form(...)
):
    user_id = current_user_id(request)
    if user_id is None:
        return login_redirect()
    verify_csrf(request, csrf_token)
    lecture = await get_lecture(lecture_id, user_id=user_id)
    if lecture is None:
        raise HTTPException(404, "강의를 찾을 수 없습니다.")
    if not await get_queue().cancel(lecture_id):
        raise HTTPException(409, "대기 중(queued)인 작업만 취소할 수 있습니다.")
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"id": lecture_id, "status": "cancelled"})
    return RedirectResponse(f"/lectures/{lecture_id}", status_code=303)


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
