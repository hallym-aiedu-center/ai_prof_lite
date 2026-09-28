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
from modules.lecture.references import cleanup_reference_files, save_reference_files
from modules.lecture.repository import create_lecture, list_lectures
from modules.lecture.route_support import _queue_runtime_config, _wants_json, templates
from modules.lecture.uploads import save_portrait
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

    return templates.TemplateResponse(
        request=request,
        name="lectures/list.html",
        context={
            "user": await get_user(
                user_id
            ),
            "lectures": await list_lectures(
                user_id=user_id,
                limit=100,
            ),
            "active_page": "lectures",
            "csrf_token": get_csrf_token(
                request
            ),
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
            "queue_config": _queue_runtime_config(),
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

    def integer(value, label, minimum=1):
        if not value.strip():
            return None
        try:
            parsed = int(value)
            if parsed < minimum:
                raise ValueError()
            return parsed
        except ValueError as exc:
            raise HTTPException(422, f"{label} 값이 올바르지 않습니다.") from exc

    title, topic = title.strip(), topic.strip()
    if not title or len(title) > 200 or not topic or len(topic) > 20000:
        raise HTTPException(422, "제목은 1~200자, 강의 요청은 1~20,000자로 입력하세요.")
    for value in (text_model, image_model, tts_model, tts_voice):
        if not value.strip() or len(value) > 128:
            raise HTTPException(422, "모델과 음성 이름은 1~128자로 입력하세요.")
    if int(target_duration_minutes) not in {30, 40, 50, 60}:
        raise HTTPException(422, "목표 강의시간은 30/40/50/60분 중에서 선택하세요.")
    if int(target_slide_count) not in {8, 9, 10, 11, 12}:
        raise HTTPException(422, "슬라이드 수는 8~12장 중에서 선택하세요.")

    reference_mode = reference_mode.strip().lower()
    if reference_mode not in {"rag", "full"}:
        raise HTTPException(422, "참고자료 처리 방식은 RAG 또는 전체 파일 전달 중에서 선택하세요.")

    if moodle_deploy_mode not in {"create", "existing"}:
        raise HTTPException(422, "올바른 Moodle 배포 방식을 선택하세요.")
    course_id = integer(moodle_course_id, "강좌")
    section_num = integer(moodle_section_num, "섹션", 0)
    cmid = integer(moodle_videotracker_cmid, "VideoTracker")
    should_upload = upload_to_moodle is not None
    if should_upload:
        try:
            await require_user_moodle_credential(user_id)
        except MissingCredentialError as exc:
            raise HTTPException(422, str(exc)) from exc
        if course_id is None:
            raise HTTPException(422, "Moodle 강좌를 선택하세요.")
        if moodle_deploy_mode == "create":
            if section_num is None:
                raise HTTPException(422, "새 활동을 생성할 섹션을 선택하세요.")
            cmid = None
        elif cmid is None:
            raise HTTPException(422, "기존 VideoTracker를 선택하세요.")

    should_generate_images = generate_images is not None

    portrait_path = None
    source_files: list[dict] = []
    try:
        portrait_path = await save_portrait(portrait)
        source_files = await save_reference_files(reference_files)
        lecture_id = await create_lecture(
            user_id=user_id, title=title, topic=topic,
            text_model=text_model, image_model=image_model,
            tts_model=tts_model, tts_voice=tts_voice,
            generate_images=should_generate_images,
            target_duration_minutes=int(target_duration_minutes),
            target_slide_count=int(target_slide_count),
            review_before_video=review_before_video is not None,
            source_files=source_files,
            reference_mode=reference_mode,
            moodle_course_id=course_id, moodle_section_num=section_num,
            moodle_deploy_mode=moodle_deploy_mode, moodle_videotracker_cmid=cmid,
            upload_to_moodle=should_upload, portrait_path=str(portrait_path),
        )
    except BaseException:
        if portrait_path is not None:
            portrait_path.unlink(missing_ok=True)
        cleanup_reference_files(source_files)
        raise
    try:
        await get_queue().enqueue(lecture_id)
    except Exception:
        # The queued lecture is durable. Worker reconciliation repairs this gap.
        logging.getLogger(__name__).exception("Queue enqueue deferred for lecture %s", lecture_id)

    if _wants_json(request):
        return JSONResponse(
            {
                "id": lecture_id,
                "title": title,
                "status": "queued",
                "progress": 0,
                "status_message": "작업 대기 중",
                "reference_mode": reference_mode,
                "review_before_video": review_before_video is not None,
                "detail_url": f"/lectures/{lecture_id}",
            },
            status_code=202,
        )

    return RedirectResponse(
        url=f"/lectures/{lecture_id}",
        status_code=303,
    )

