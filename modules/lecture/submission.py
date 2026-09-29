from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, UploadFile

from modules.lecture.references import cleanup_reference_files, save_reference_files
from modules.lecture.repository import create_lecture
from modules.lecture.uploads import save_portrait


@dataclass(frozen=True)
class LectureSubmission:
    title: str
    topic: str
    text_model: str
    image_model: str
    tts_model: str
    tts_voice: str
    generate_images: bool
    target_duration_minutes: int
    target_slide_count: int
    review_before_video: bool
    reference_mode: str
    upload_to_moodle: bool
    moodle_course_id: int | None
    moodle_section_num: int | None
    moodle_deploy_mode: str
    moodle_videotracker_cmid: int | None


def _optional_int(value: str, label: str, minimum: int = 1) -> int | None:
    if not value.strip():
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise HTTPException(422, f"{label} 값이 올바르지 않습니다.") from exc
    if parsed < minimum:
        raise HTTPException(422, f"{label} 값이 올바르지 않습니다.")
    return parsed


def validate_lecture_submission(
    *,
    title: str,
    topic: str,
    text_model: str,
    image_model: str,
    tts_model: str,
    tts_voice: str,
    generate_images: str | None,
    target_duration_minutes: int,
    target_slide_count: int,
    review_before_video: str | None,
    reference_mode: str,
    upload_to_moodle: str | None,
    moodle_course_id: str,
    moodle_section_num: str,
    moodle_deploy_mode: str,
    moodle_videotracker_cmid: str,
) -> LectureSubmission:
    title, topic = title.strip(), topic.strip()
    if not title or len(title) > 200 or not topic or len(topic) > 20_000:
        raise HTTPException(422, "제목은 1~200자, 강의 요청은 1~20,000자로 입력하세요.")

    models = [text_model.strip(), image_model.strip(), tts_model.strip(), tts_voice.strip()]
    if any(not value or len(value) > 128 for value in models):
        raise HTTPException(422, "모델과 음성 이름은 1~128자로 입력하세요.")

    duration = int(target_duration_minutes)
    slide_count = int(target_slide_count)
    if duration not in {30, 40, 50, 60}:
        raise HTTPException(422, "목표 강의시간은 30/40/50/60분 중에서 선택하세요.")
    if slide_count not in {8, 9, 10, 11, 12}:
        raise HTTPException(422, "슬라이드 수는 8~12장 중에서 선택하세요.")

    mode = reference_mode.strip().lower()
    if mode not in {"rag", "full"}:
        raise HTTPException(422, "참고자료 처리 방식은 RAG 또는 전체 파일 전달 중에서 선택하세요.")
    if moodle_deploy_mode not in {"create", "existing"}:
        raise HTTPException(422, "올바른 Moodle 배포 방식을 선택하세요.")

    course_id = _optional_int(moodle_course_id, "강좌")
    section_num = _optional_int(moodle_section_num, "섹션", 0)
    cmid = _optional_int(moodle_videotracker_cmid, "VideoTracker")
    should_upload = upload_to_moodle is not None
    if should_upload:
        if course_id is None:
            raise HTTPException(422, "Moodle 강좌를 선택하세요.")
        if moodle_deploy_mode == "create":
            if section_num is None:
                raise HTTPException(422, "새 활동을 생성할 섹션을 선택하세요.")
            cmid = None
        elif cmid is None:
            raise HTTPException(422, "기존 VideoTracker를 선택하세요.")

    return LectureSubmission(
        title=title,
        topic=topic,
        text_model=models[0],
        image_model=models[1],
        tts_model=models[2],
        tts_voice=models[3],
        generate_images=generate_images is not None,
        target_duration_minutes=duration,
        target_slide_count=slide_count,
        review_before_video=review_before_video is not None,
        reference_mode=mode,
        upload_to_moodle=should_upload,
        moodle_course_id=course_id,
        moodle_section_num=section_num,
        moodle_deploy_mode=moodle_deploy_mode,
        moodle_videotracker_cmid=cmid,
    )


async def persist_lecture_submission(
    *,
    user_id: int,
    submission: LectureSubmission,
    portrait: UploadFile,
    reference_files: list[UploadFile] | None,
) -> int:
    portrait_path = None
    source_files: list[dict] = []
    try:
        portrait_path = await save_portrait(portrait)
        source_files = await save_reference_files(reference_files)
        return await create_lecture(
            user_id=user_id,
            title=submission.title,
            topic=submission.topic,
            text_model=submission.text_model,
            image_model=submission.image_model,
            tts_model=submission.tts_model,
            tts_voice=submission.tts_voice,
            generate_images=submission.generate_images,
            target_duration_minutes=submission.target_duration_minutes,
            target_slide_count=submission.target_slide_count,
            review_before_video=submission.review_before_video,
            source_files=source_files,
            reference_mode=submission.reference_mode,
            moodle_course_id=submission.moodle_course_id,
            moodle_section_num=submission.moodle_section_num,
            moodle_deploy_mode=submission.moodle_deploy_mode,
            moodle_videotracker_cmid=submission.moodle_videotracker_cmid,
            upload_to_moodle=submission.upload_to_moodle,
            portrait_path=str(portrait_path),
        )
    except BaseException:
        if portrait_path is not None:
            portrait_path.unlink(missing_ok=True)
        cleanup_reference_files(source_files)
        raise
