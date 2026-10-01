from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from core.jobs.errors import AmbiguousDeploymentError


@dataclass(frozen=True)
class MoodleDeploymentSpec:
    user_id: int
    title: str
    deploy_mode: str
    course_id: int | None
    section_num: int | None
    cmid: int | None
    video_path: str
    duration: float | None

    @classmethod
    def from_lecture(
        cls,
        lecture: dict[str, Any],
        *,
        video_path: str,
        duration: float | None,
    ) -> MoodleDeploymentSpec:
        return cls(
            user_id=int(lecture["user_id"]),
            title=str(lecture["title"]),
            deploy_mode=str(lecture.get("moodle_deploy_mode") or "create"),
            course_id=(
                int(lecture["moodle_course_id"])
                if lecture.get("moodle_course_id") is not None
                else None
            ),
            section_num=(
                int(lecture["moodle_section_num"])
                if lecture.get("moodle_section_num") is not None
                else None
            ),
            cmid=(
                int(lecture["moodle_videotracker_cmid"])
                if lecture.get("moodle_videotracker_cmid")
                else None
            ),
            video_path=str(video_path),
            duration=duration,
        )


@dataclass(frozen=True)
class MoodleCreateState:
    status: str = "idle"
    activity: dict[str, Any] | None = None


@dataclass(frozen=True)
class MoodleVideoState:
    status: str = "idle"
    result: Any = None


@dataclass(frozen=True)
class MoodleDeploymentResult:
    mode: str
    cmid: int
    activity: dict[str, Any] | None
    video: Any

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "cmid": self.cmid,
            "activity": self.activity,
            "video": self.video,
        }


class MoodleCreateMarker(Protocol):
    async def load(self) -> MoodleCreateState: ...

    async def mark_running(self) -> None: ...

    async def mark_completed(self, activity: dict[str, Any]) -> None: ...

    async def load_video(self) -> MoodleVideoState: ...

    async def mark_video_running(self) -> None: ...

    async def mark_video_completed(self, result: Any) -> None: ...


GetClient = Callable[[int], Awaitable[Any]]
CreateActivity = Callable[..., Awaitable[dict[str, Any]]]
SetVideo = Callable[..., Awaitable[Any]]


async def deploy_moodle_video(
    spec: MoodleDeploymentSpec,
    *,
    marker: MoodleCreateMarker,
    get_client: GetClient,
    create_activity: CreateActivity,
    set_video_from_file: SetVideo,
) -> MoodleDeploymentResult:
    """Single Moodle deployment path shared by worker and publish scheduler."""
    client = await get_client(spec.user_id)
    cmid = spec.cmid
    activity: dict[str, Any] | None = None

    if spec.deploy_mode == "create":
        if not cmid:
            if spec.course_id is None or spec.section_num is None:
                raise RuntimeError("Moodle 강좌/섹션 정보가 없습니다.")

            state = await marker.load()
            if state.status == "completed":
                activity = state.activity
                try:
                    cmid = int((activity or {})["cmid"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise AmbiguousDeploymentError(
                        "저장된 Moodle 활동 생성 결과가 손상되었습니다. "
                        "Moodle에서 활동을 확인한 뒤 CMID를 수동으로 등록하세요."
                    ) from exc
            elif state.status == "running":
                raise AmbiguousDeploymentError(
                    "이전 Moodle 활동 생성 요청의 결과가 불확실합니다. "
                    "Moodle에서 활동 존재 여부를 확인한 뒤 CMID를 등록하세요. "
                    "중복 생성을 막기 위해 자동 재생성은 중단했습니다."
                )
            else:
                await marker.mark_running()
                try:
                    activity = await create_activity(
                        client=client,
                        course_id=spec.course_id,
                        section_num=spec.section_num,
                        name=spec.title,
                        intro="AI Professor Lite에서 자동 생성한 강의 영상입니다.",
                    )
                except Exception as exc:
                    # Keep the marker in running state because Moodle may have
                    # committed the non-idempotent create request already.
                    raise AmbiguousDeploymentError(
                        "Moodle 활동 생성 응답을 확인하지 못했습니다. "
                        "Moodle에서 생성 여부를 확인하세요."
                    ) from exc
                cmid = int(activity["cmid"])
                await marker.mark_completed(activity)
    elif spec.deploy_mode == "existing":
        if not cmid:
            raise RuntimeError("기존 VideoTracker CMID가 선택되지 않았습니다.")
    else:
        raise RuntimeError(f"지원하지 않는 Moodle 배포 방식: {spec.deploy_mode}")

    if not cmid:
        raise RuntimeError("Moodle VideoTracker CMID가 없습니다.")

    video_state = await marker.load_video()
    if video_state.status == "completed":
        video_result = video_state.result
    elif video_state.status == "running":
        raise AmbiguousDeploymentError(
            "이전 Moodle 영상 업로드/연결 요청의 결과가 불확실합니다. "
            "Moodle에서 영상 연결 상태를 확인한 뒤 다시 진행하세요. "
            "중복 업로드를 막기 위해 자동 재시도는 중단했습니다."
        )
    else:
        await marker.mark_video_running()
        try:
            video_result = await set_video_from_file(
                client=client,
                cmid=int(cmid),
                path=spec.video_path,
                duration=spec.duration,
            )
        except Exception as exc:
            # upload.php or set_video may have committed even if the response was lost.
            # Keep the durable marker in running state so a retry cannot duplicate it.
            raise AmbiguousDeploymentError(
                "Moodle 영상 업로드/연결 응답을 확인하지 못했습니다. "
                "Moodle에서 실제 반영 여부를 확인하세요."
            ) from exc

        if isinstance(video_result, dict) and video_result.get("success") is False:
            raise AmbiguousDeploymentError(
                "Moodle 영상 연결이 실패 응답을 반환했습니다. "
                "업로드된 draft 파일의 반영 여부를 확인하세요."
            )
        await marker.mark_video_completed(video_result)

    return MoodleDeploymentResult(
        mode=spec.deploy_mode,
        cmid=int(cmid),
        activity=activity,
        video=video_result,
    )
