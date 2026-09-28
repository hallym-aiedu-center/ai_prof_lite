import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from core.jobs.errors import (
    AmbiguousDeploymentError,
    PublishNotReadyError,
    PublishSourceFailedError,
)
from modules.lecture import publishing


def test_weekday_and_datetime_helpers():
    assert publishing.weekday_name_ko(None) == "-"
    assert publishing.weekday_name_ko(-1) == "-"
    assert publishing.weekday_name_ko(0) == "월"
    assert publishing.weekday_name_ko(6) == "일"

    now = datetime(2026, 9, 28, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))  # Monday
    same_day = publishing.next_weekday_datetime(
        weekday=0, hour=11, minute=0, timezone_name="Asia/Seoul", now=now
    )
    assert same_day == datetime(2026, 9, 28, 11, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    rolled = publishing.next_weekday_datetime(
        weekday=0, hour=10, minute=10, timezone_name="Asia/Seoul", now=now
    )
    assert rolled.date().isoformat() == "2026-10-05"

    sql = publishing.to_utc_sql(now)
    restored = publishing.from_utc_sql(sql, "Asia/Seoul")
    assert restored == now.replace(second=0, microsecond=0)




def _install_usage_passthrough(monkeypatch):
    async def passthrough(client, **kwargs):
        kwargs.pop("user_id", None)
        kwargs.pop("lecture_id", None)
        return await client.responses.create(**kwargs)
    monkeypatch.setattr(publishing, "responses_create", passthrough)

class _Responses:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(output_text=json.dumps(self.result, ensure_ascii=False))


@pytest.mark.asyncio
async def test_choose_ai_publish_plan_success(monkeypatch):
    _install_usage_passthrough(monkeypatch)
    responses = _Responses({"weekday": 2, "hour": 18, "minute": 30, "rationale": "분산 게시"})
    monkeypatch.setattr(
        publishing,
        "get_client",
        lambda **_: SimpleNamespace(responses=responses),
    )
    result = await publishing.choose_ai_publish_plan(
        api_key="k",
        title="title",
        topic="topic",
        model="model",
        timezone_name="Asia/Seoul",
        weekday_load={2: 3},
        user_id=1,
    )
    assert result["weekday"] == 2
    assert result["hour"] == 18 and result["minute"] == 30
    assert result["timezone"] == "Asia/Seoul"
    assert result["scheduled_local"].tzinfo is not None
    assert responses.calls[0]["model"] == "model"


@pytest.mark.asyncio
async def test_choose_ai_publish_plan_fallback_and_validation(monkeypatch):
    _install_usage_passthrough(monkeypatch)
    monkeypatch.setattr(
        publishing,
        "get_client",
        lambda **_: SimpleNamespace(responses=_Responses(error=RuntimeError("offline"))),
    )
    result = await publishing.choose_ai_publish_plan(
        api_key="k", title="t", topic="x", model="m", timezone_name="Asia/Seoul", user_id=1
    )
    assert result["hour"] == 18 and result["minute"] == 0
    assert "자동 스케줄" in result["rationale"]

    bad = _Responses({"weekday": 7, "hour": 18, "minute": 0, "rationale": "bad"})
    monkeypatch.setattr(publishing, "get_client", lambda **_: SimpleNamespace(responses=bad))
    with pytest.raises(ValueError, match="weekday"):
        await publishing.choose_ai_publish_plan(
            api_key="k", title="t", topic="x", model="m", timezone_name="UTC", user_id=1
        )


@pytest.mark.asyncio
async def test_ensure_lecture_ready_for_publish_branches(monkeypatch):
    cases = [
        (None, RuntimeError, "찾을 수"),
        ({"upload_to_moodle": False}, RuntimeError, "업로드 대상"),
        ({"upload_to_moodle": True, "status": "failed"}, PublishSourceFailedError, "실패"),
        ({"upload_to_moodle": True, "status": "running"}, PublishNotReadyError, "아직 완료"),
    ]
    for lecture, exc_type, match in cases:
        monkeypatch.setattr(publishing, "get_lecture", AsyncMock(return_value=lecture))
        with pytest.raises(exc_type, match=match):
            await publishing.ensure_lecture_ready_for_publish(1)

    lecture = {"upload_to_moodle": True, "status": "completed", "final_video_path": "x.mp4"}
    monkeypatch.setattr(publishing, "get_lecture", AsyncMock(return_value=lecture))
    assert await publishing.ensure_lecture_ready_for_publish(1) is lecture


def _lecture(video: Path, **overrides):
    value = {
        "final_video_path": str(video),
        "user_id": 3,
        "moodle_deploy_mode": "create",
        "moodle_videotracker_cmid": None,
        "moodle_course_id": 7,
        "moodle_section_num": 2,
        "title": "Lecture",
    }
    value.update(overrides)
    return value


async def _patch_deploy_common(monkeypatch, lecture):
    monkeypatch.setattr(publishing, "ensure_lecture_ready_for_publish", AsyncMock(return_value=lecture))
    monkeypatch.setattr(publishing, "get_user_moodle_client", AsyncMock(return_value=object()))
    monkeypatch.setattr(publishing, "media_duration", AsyncMock(return_value=12.5))
    monkeypatch.setattr(publishing, "set_video_from_file", AsyncMock(return_value={"success": True}))
    monkeypatch.setattr(publishing, "update_lecture", AsyncMock())


@pytest.mark.asyncio
async def test_deploy_create_scheduled_marks_and_uploads(tmp_path, monkeypatch):
    video = tmp_path / "final.mp4"
    video.write_bytes(b"video")
    lecture = _lecture(video)
    await _patch_deploy_common(monkeypatch, lecture)
    monkeypatch.setattr(publishing, "get_publish_schedule", AsyncMock(return_value={"create_state": "idle"}))
    update_schedule = AsyncMock()
    monkeypatch.setattr(publishing, "update_publish_schedule", update_schedule)
    create = AsyncMock(return_value={"cmid": 42, "success": True})
    monkeypatch.setattr(publishing, "create_activity", create)

    result = await publishing.deploy_lecture_to_moodle(10, publish_lease_token="lease")
    assert result["cmid"] == 42 and result["mode"] == "create"
    assert update_schedule.await_count == 2
    assert update_schedule.await_args_list[0].kwargs["create_state"] == "running"
    assert update_schedule.await_args_list[1].kwargs["create_state"] == "completed"
    publishing.set_video_from_file.assert_awaited_once()
    assert publishing.update_lecture.await_count == 2


@pytest.mark.asyncio
async def test_deploy_reuses_completed_schedule_without_recreate(tmp_path, monkeypatch):
    video = tmp_path / "final.mp4"
    video.write_bytes(b"video")
    lecture = _lecture(video)
    await _patch_deploy_common(monkeypatch, lecture)
    monkeypatch.setattr(
        publishing,
        "get_publish_schedule",
        AsyncMock(return_value={"create_state": "completed", "create_result_json": '{"cmid": 77}'}),
    )
    create = AsyncMock()
    monkeypatch.setattr(publishing, "create_activity", create)
    monkeypatch.setattr(publishing, "update_publish_schedule", AsyncMock())

    result = await publishing.deploy_lecture_to_moodle(10, publish_lease_token="lease")
    assert result["cmid"] == 77
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_deploy_ambiguous_schedule_states(tmp_path, monkeypatch):
    video = tmp_path / "final.mp4"
    video.write_bytes(b"video")
    lecture = _lecture(video)
    await _patch_deploy_common(monkeypatch, lecture)
    monkeypatch.setattr(publishing, "update_publish_schedule", AsyncMock())

    for schedule in [
        {"create_state": "running"},
        {"create_state": "completed", "create_result_json": "{}"},
    ]:
        monkeypatch.setattr(publishing, "get_publish_schedule", AsyncMock(return_value=schedule))
        monkeypatch.setattr(publishing, "create_activity", AsyncMock())
        with pytest.raises(AmbiguousDeploymentError):
            await publishing.deploy_lecture_to_moodle(10, publish_lease_token="lease")

    monkeypatch.setattr(publishing, "get_publish_schedule", AsyncMock(return_value={"create_state": "idle"}))
    monkeypatch.setattr(publishing, "create_activity", AsyncMock(side_effect=TimeoutError("lost")))
    with pytest.raises(AmbiguousDeploymentError, match="응답"):
        await publishing.deploy_lecture_to_moodle(10, publish_lease_token="lease")


@pytest.mark.asyncio
async def test_deploy_create_requires_lease_and_course_metadata(tmp_path, monkeypatch):
    video = tmp_path / "final.mp4"
    video.write_bytes(b"video")

    lecture = _lecture(video)
    await _patch_deploy_common(monkeypatch, lecture)
    monkeypatch.setattr(publishing, "get_publish_schedule", AsyncMock(return_value={"create_state": "idle"}))
    with pytest.raises(RuntimeError, match="lease token"):
        await publishing.deploy_lecture_to_moodle(1)

    lecture = _lecture(video, moodle_course_id=None)
    await _patch_deploy_common(monkeypatch, lecture)
    with pytest.raises(RuntimeError, match="강좌/섹션"):
        await publishing.deploy_lecture_to_moodle(1)


@pytest.mark.asyncio
async def test_deploy_direct_create_existing_and_error_modes(tmp_path, monkeypatch):
    video = tmp_path / "final.mp4"
    video.write_bytes(b"video")

    lecture = _lecture(video)
    await _patch_deploy_common(monkeypatch, lecture)
    monkeypatch.setattr(publishing, "get_publish_schedule", AsyncMock(return_value=None))
    monkeypatch.setattr(publishing, "create_activity", AsyncMock(return_value={"cmid": 9}))
    result = await publishing.deploy_lecture_to_moodle(1)
    assert result["cmid"] == 9

    lecture = _lecture(video, moodle_deploy_mode="existing", moodle_videotracker_cmid=88)
    await _patch_deploy_common(monkeypatch, lecture)
    result = await publishing.deploy_lecture_to_moodle(1)
    assert result["cmid"] == 88 and result["activity"] is None

    lecture = _lecture(video, moodle_deploy_mode="existing", moodle_videotracker_cmid=None)
    await _patch_deploy_common(monkeypatch, lecture)
    with pytest.raises(RuntimeError, match="CMID"):
        await publishing.deploy_lecture_to_moodle(1)

    lecture = _lecture(video, moodle_deploy_mode="mystery")
    await _patch_deploy_common(monkeypatch, lecture)
    with pytest.raises(RuntimeError, match="지원하지 않는"):
        await publishing.deploy_lecture_to_moodle(1)


@pytest.mark.asyncio
async def test_deploy_rejects_missing_video_and_failed_moodle_attach(tmp_path, monkeypatch):
    missing = tmp_path / "missing.mp4"
    lecture = _lecture(missing, moodle_deploy_mode="existing", moodle_videotracker_cmid=88)
    monkeypatch.setattr(publishing, "ensure_lecture_ready_for_publish", AsyncMock(return_value=lecture))
    with pytest.raises(RuntimeError, match="영상 파일"):
        await publishing.deploy_lecture_to_moodle(1)

    video = tmp_path / "final.mp4"
    video.write_bytes(b"video")
    lecture = _lecture(video, moodle_deploy_mode="existing", moodle_videotracker_cmid=88)
    await _patch_deploy_common(monkeypatch, lecture)
    monkeypatch.setattr(publishing, "set_video_from_file", AsyncMock(return_value={"success": False}))
    with pytest.raises(RuntimeError, match="영상 연결"):
        await publishing.deploy_lecture_to_moodle(1)
