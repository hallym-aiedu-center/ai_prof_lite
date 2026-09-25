from __future__ import annotations

from typing import Any

from core.moodle.client import MoodleClient


async def get_site_info(
    client: MoodleClient,
) -> dict[str, Any]:
    return await client.call(
        "core_webservice_get_site_info"
    )


async def get_my_courses(
    client: MoodleClient,
) -> list[dict[str, Any]]:
    site_info = await get_site_info(
        client
    )

    user_id = site_info.get(
        "userid"
    )

    if not user_id:
        raise RuntimeError(
            "Moodle site info에서 "
            "userid를 확인할 수 없습니다."
        )

    courses = await client.call(
        "core_enrol_get_users_courses",
        userid=int(user_id),
    )

    if not isinstance(
        courses,
        list,
    ):
        raise RuntimeError(
            "Moodle 강좌 응답 형식이 "
            "예상과 다릅니다."
        )

    return courses


async def get_course_contents(
    client: MoodleClient,
    course_id: int,
) -> list[dict[str, Any]]:
    result = await client.call(
        "core_course_get_contents",
        courseid=int(course_id),
    )

    if not isinstance(
        result,
        list,
    ):
        raise RuntimeError(
            "Moodle 강좌 contents 응답 형식이 "
            "예상과 다릅니다."
        )

    return result


async def get_course_sections(
    client: MoodleClient,
    course_id: int,
) -> list[dict[str, Any]]:
    """
    Return relative section numbers.

    The create-activity API expects sectionnum,
    not course_sections.id.
    """
    sections = await get_course_contents(
        client,
        course_id,
    )

    return [
        {
            "id": section.get("id"),
            "section": section.get("section"),
            "name": (
                section.get("name")
                or f"Section {section.get('section')}"
            ),
            "visible": section.get(
                "visible",
                1,
            ),
        }
        for section in sections
    ]


def _module_summary(
    section: dict[str, Any],
    module: dict[str, Any],
) -> dict[str, Any]:
    return {
        # module["id"] is the course module id (CMID).
        "cmid": module.get("id"),

        "instance_id": module.get(
            "instance"
        ),

        "name": module.get("name"),
        "modname": module.get(
            "modname"
        ),
        "url": module.get("url"),
        "visible": module.get(
            "visible",
            1,
        ),
        "availability": module.get(
            "availability"
        ),

        "section_id": section.get(
            "id"
        ),

        # Relative section number. This is what
        # create_activity(sectionnum=...) needs.
        "section_number": section.get(
            "section"
        ),

        "section_name": section.get(
            "name"
        ),
    }


async def get_videotrackers(
    client: MoodleClient,
    course_id: int,
) -> list[dict[str, Any]]:
    sections = await get_course_contents(
        client,
        course_id,
    )

    trackers: list[
        dict[str, Any]
    ] = []

    for section in sections:
        for module in section.get(
            "modules",
            [],
        ):
            if (
                module.get("modname")
                != "videotracker"
            ):
                continue

            trackers.append(
                _module_summary(
                    section,
                    module,
                )
            )

    return trackers


async def get_course_overview(
    client: MoodleClient,
    course_id: int,
) -> dict[str, Any]:
    sections = await get_course_contents(
        client,
        course_id,
    )

    module_counts: dict[
        str,
        int,
    ] = {}

    normalized_sections = []

    for section in sections:
        normalized_modules = []

        for module in section.get(
            "modules",
            [],
        ):
            modname = (
                module.get("modname")
                or "unknown"
            )

            module_counts[
                modname
            ] = (
                module_counts.get(
                    modname,
                    0,
                )
                + 1
            )

            normalized_modules.append(
                _module_summary(
                    section,
                    module,
                )
            )

        normalized_sections.append(
            {
                "id": section.get("id"),
                "section": section.get(
                    "section"
                ),
                "name": section.get(
                    "name"
                ),
                "summary": section.get(
                    "summary"
                ),
                "visible": section.get(
                    "visible",
                    1,
                ),
                "modules": normalized_modules,
            }
        )

    return {
        "course_id": int(course_id),
        "module_counts": module_counts,
        "sections": normalized_sections,
    }


async def find_course(
    client: MoodleClient,
    course_id: int,
) -> dict[str, Any] | None:
    courses = await get_my_courses(
        client
    )

    for course in courses:
        if int(
            course.get(
                "id",
                -1,
            )
        ) == int(course_id):
            return course

    return None
