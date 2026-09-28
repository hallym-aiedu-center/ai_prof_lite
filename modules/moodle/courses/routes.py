from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from core.config import PROJECT_ROOT as TEMPLATE_ROOT
from modules.auth.session import (
    current_user_id,
    get_csrf_token,
    login_redirect,
)
from modules.moodle.courses.service import (
    find_course,
    get_course_overview,
    get_course_sections,
    get_my_courses,
    get_videotrackers,
)
from modules.moodle.service import (
    get_user_moodle_client,
)
from modules.users.service import (
    get_user,
)

router = APIRouter(
    prefix="/moodle",
    tags=["moodle-ui"],
)

api_router = APIRouter(
    prefix="/api/moodle",
    tags=["moodle-api"],
)

templates = Jinja2Templates(
    directory=str(TEMPLATE_ROOT / "templates")
)


def _clean_course(
    course: dict,
) -> dict:
    return {
        "id": course.get("id"),
        "fullname": course.get(
            "fullname"
        ),
        "shortname": course.get(
            "shortname"
        ),
        "displayname": (
            course.get("displayname")
            or course.get("fullname")
        ),
        "summary": course.get(
            "summary"
        ),
        "visible": course.get(
            "visible",
            1,
        ),
        "startdate": course.get(
            "startdate"
        ),
        "enddate": course.get(
            "enddate"
        ),
        "progress": course.get(
            "progress"
        ),
    }


@router.get("/courses")
async def course_list_page(
    request: Request,
):
    user_id = current_user_id(
        request
    )

    if user_id is None:
        return login_redirect()

    user = await get_user(
        user_id
    )

    try:
        client = (
            await get_user_moodle_client(
                user_id
            )
        )

        courses = await get_my_courses(
            client
        )

        error = None

    except Exception as exc:  # noqa: BLE001
        courses = []
        error = str(exc)

    return templates.TemplateResponse(
        request=request,
        name="moodle/courses.html",
        context={
            "user": user,
            "active_page": "moodle_courses",
            "csrf_token": get_csrf_token(
                request
            ),
            "courses": [
                _clean_course(course)
                for course in courses
            ],
            "error": error,
        },
    )


@router.get(
    "/courses/{course_id}"
)
async def course_detail_page(
    request: Request,
    course_id: int,
):
    user_id = current_user_id(
        request
    )

    if user_id is None:
        return login_redirect()

    user = await get_user(
        user_id
    )

    try:
        client = (
            await get_user_moodle_client(
                user_id
            )
        )

        course = await find_course(
            client,
            course_id,
        )

        if course is None:
            return templates.TemplateResponse(
                request=request,
                name="moodle/course_detail.html",
                context={
                    "user": user,
                    "active_page": "moodle_courses",
                    "csrf_token": get_csrf_token(
                        request
                    ),
                    "course": None,
                    "overview": None,
                    "error": (
                        "해당 강좌를 "
                        "찾을 수 없습니다."
                    ),
                },
                status_code=404,
            )

        overview = (
            await get_course_overview(
                client,
                course_id,
            )
        )

        error = None

    except Exception as exc:  # noqa: BLE001
        course = None
        overview = None
        error = str(exc)

    return templates.TemplateResponse(
        request=request,
        name="moodle/course_detail.html",
        context={
            "user": user,
            "active_page": "moodle_courses",
            "csrf_token": get_csrf_token(
                request
            ),
            "course": (
                _clean_course(course)
                if course
                else None
            ),
            "overview": overview,
            "error": error,
        },
    )


@api_router.get("/courses")
async def api_courses(
    request: Request,
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

    try:
        client = (
            await get_user_moodle_client(
                user_id
            )
        )

        courses = await get_my_courses(
            client
        )

        return {
            "courses": [
                _clean_course(course)
                for course in courses
            ]
        }

    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            {
                "error": "moodle_error",
                "message": str(exc),
            },
            status_code=400,
        )


@api_router.get(
    "/courses/{course_id}/sections"
)
async def api_course_sections(
    request: Request,
    course_id: int,
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

    try:
        client = (
            await get_user_moodle_client(
                user_id
            )
        )

        sections = (
            await get_course_sections(
                client,
                course_id,
            )
        )

        return {
            "course_id": course_id,
            "sections": sections,
        }

    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            {
                "error": "moodle_error",
                "message": str(exc),
            },
            status_code=400,
        )


@api_router.get(
    "/courses/{course_id}/videotrackers"
)
async def api_videotrackers(
    request: Request,
    course_id: int,
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

    try:
        client = (
            await get_user_moodle_client(
                user_id
            )
        )

        trackers = (
            await get_videotrackers(
                client,
                course_id,
            )
        )

        return {
            "course_id": course_id,
            "count": len(trackers),
            "auto_selected_cmid": (
                trackers[0]["cmid"]
                if len(trackers) == 1
                else None
            ),
            "videotrackers": trackers,
        }

    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            {
                "error": "moodle_error",
                "message": str(exc),
            },
            status_code=400,
        )


@api_router.get(
    "/courses/{course_id}/contents"
)
async def api_course_contents(
    request: Request,
    course_id: int,
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

    try:
        client = (
            await get_user_moodle_client(
                user_id
            )
        )

        return (
            await get_course_overview(
                client,
                course_id,
            )
        )

    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            {
                "error": "moodle_error",
                "message": str(exc),
            },
            status_code=400,
        )
