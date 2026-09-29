import logging
import os

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse

from core.jobs.factory import get_queue
from modules.auth.session import (
    current_user_id,
    get_csrf_token,
    login_redirect,
    verify_csrf,
)
from modules.credentials.required import (
    MissingCredentialError,
    require_user_moodle_credential,
    require_user_openai_api_key,
)
from modules.lecture.repository import list_lectures
from modules.lecture.route_support import _wants_json, templates
from modules.lecture.submission import persist_lecture_submission, validate_lecture_submission
from core.openai.usage import usage_summary
from modules.users.service import get_user

router = APIRouter()


@router.get("")
async def lecture_list(
    request: Request,
):
    user_id = current_user_id(
        request
    )

    if user_id is None:
        return login_redirect()

    try:
        page = max(1, int(request.query_params.get("page", "1")))
    except ValueError:
        page = 1
    page_size = 20
    rows = await list_lectures(
        user_id=user_id,
        limit=page_size + 1,
        offset=(page - 1) * page_size,
    )
    has_next = len(rows) > page_size

    return templates.TemplateResponse(
        request=request,
        name="lectures/list.html",
        context={
            "user": await get_user(
                user_id
            ),
            "lectures": rows[:page_size],
            "active_page": "lectures",
            "csrf_token": get_csrf_token(
                request
            ),
            "page": page,
            "has_previous": page > 1,
            "has_next": has_next,
        },
    )


@router.get("/new")
async def new_lecture(
    request: Request,
):
    user_id = current_user_id(
        request
    )

    if user_id is None:
        return login_redirect()

    return templates.TemplateResponse(
        request=request,
        name="lectures/new.html",
        context={
            "user": await get_user(
                user_id
            ),
            "active_page": "lectures",
            "csrf_token": get_csrf_token(
                request
            ),
            "openai_usage": await usage_summary(user_id),
            "requested_course_id": (
                request.query_params.get(
                    "course_id",
                    "",
                )
            ),
            "defaults": {
                "text_model": os.getenv(
                    "LECTURE_TEXT_MODEL",
                    "gpt-5.1",
                ),
                "image_model": os.getenv(
                    "LECTURE_IMAGE_MODEL",
                    "gpt-image-2",
                ),
                "tts_model": os.getenv(
                    "LECTURE_TTS_MODEL",
                    "gpt-4o-mini-tts",
                ),
                "tts_voice": os.getenv(
                    "LECTURE_TTS_VOICE",
                    "alloy",
                ),
                "target_duration_minutes": int(os.getenv(
                    "LECTURE_TARGET_DURATION_MINUTES",
                    "40",
                )),
                "target_slide_count": int(os.getenv(
                    "LECTURE_TARGET_SLIDE_COUNT",
                    "10",
                )),
            },
        },
    )


@router.post("")
async def submit_lecture(
    request: Request,

    title: str = Form(...),
    topic: str = Form(...),

    text_model: str = Form(...),
    image_model: str = Form(...),
    tts_model: str = Form(...),
    tts_voice: str = Form(
        "alloy"
    ),

    generate_images: str | None = Form(
        None
    ),

    target_duration_minutes: int = Form(40),
    target_slide_count: int = Form(10),
    review_before_video: str | None = Form(None),
    reference_mode: str = Form("rag"),

    upload_to_moodle: str | None = Form(
        None
    ),

    moodle_course_id: str = Form(
        ""
    ),

    moodle_section_num: str = Form(
        ""
    ),

    moodle_deploy_mode: str = Form(
        "create"
    ),

    moodle_videotracker_cmid: str = Form(
        ""
    ),

    csrf_token: str = Form(...),

    portrait: UploadFile = File(...),
    reference_files: list[UploadFile] | None = File(None),
):
    user_id = current_user_id(
        request
    )

    if user_id is None:
        if _wants_json(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return login_redirect()

    verify_csrf(
        request,
        csrf_token,
    )

    # OpenAI credential policy is installation-configurable (user BYOK or server key).
    # Moodle credentials always remain user-owned.
    try:
        await require_user_openai_api_key(user_id)
    except MissingCredentialError as exc:
        raise HTTPException(422, str(exc)) from exc

    submission = validate_lecture_submission(
        title=title,
        topic=topic,
        text_model=text_model,
        image_model=image_model,
        tts_model=tts_model,
        tts_voice=tts_voice,
        generate_images=generate_images,
        target_duration_minutes=target_duration_minutes,
        target_slide_count=target_slide_count,
        review_before_video=review_before_video,
        reference_mode=reference_mode,
        upload_to_moodle=upload_to_moodle,
        moodle_course_id=moodle_course_id,
        moodle_section_num=moodle_section_num,
        moodle_deploy_mode=moodle_deploy_mode,
        moodle_videotracker_cmid=moodle_videotracker_cmid,
    )
    if submission.upload_to_moodle:
        try:
            await require_user_moodle_credential(user_id)
        except MissingCredentialError as exc:
            raise HTTPException(422, str(exc)) from exc

    lecture_id = await persist_lecture_submission(
        user_id=user_id,
        submission=submission,
        portrait=portrait,
        reference_files=reference_files,
    )

    try:
        await get_queue().enqueue(lecture_id)
    except Exception:
        # The queued lecture is durable. Worker reconciliation repairs this gap.
        logging.getLogger(__name__).exception("Queue enqueue deferred for lecture %s", lecture_id)

    if _wants_json(request):
        return JSONResponse(
            {
                "id": lecture_id,
                "title": submission.title,
                "status": "queued",
                "progress": 0,
                "status_message": "작업 대기 중",
                "reference_mode": submission.reference_mode,
                "review_before_video": submission.review_before_video,
                "detail_url": f"/lectures/{lecture_id}",
            },
            status_code=202,
        )

    return RedirectResponse(
        url=f"/lectures/{lecture_id}",
        status_code=303,
    )

