from __future__ import annotations

from datetime import datetime

WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]


def weekday_load_text(weekday_load: dict[int, int] | None) -> str:
    values = weekday_load or {}
    return ", ".join(f"{WEEKDAY_KO[i]}:{int(values.get(i, 0))}" for i in range(7))


def publish_plan_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["weekday", "hour", "minute", "rationale"],
        "properties": {
            "weekday": {
                "type": "integer",
                "minimum": 0,
                "maximum": 6,
                "description": "0=Monday ... 6=Sunday",
            },
            "hour": {
                "type": "integer",
                "minimum": 8,
                "maximum": 21,
            },
            "minute": {
                "type": "integer",
                "enum": [0, 30],
            },
            "rationale": {
                "type": "string",
                "minLength": 1,
                "maxLength": 240,
            },
        },
    }


def build_publish_prompt(
    *,
    now_local: datetime,
    timezone_name: str,
    title: str,
    topic: str,
    weekday_load: dict[int, int] | None,
) -> str:
    load_text = weekday_load_text(weekday_load)
    return f"""
당신은 온라인 강의 게시 스케줄러입니다.
현재 로컬 날짜/시각과 강의 주제를 보고, 이 강의를 Moodle에 올릴 다음 게시 요일과 시각을 정하세요.

현재 시각: {now_local.isoformat()}
타임존: {timezone_name}
강의 제목: {title}
강의 주제: {topic[:3000]}
현재 다른 강의 예약 건수(월~일): {load_text}

규칙:
- 월요일=0, 화요일=1, 수요일=2, 목요일=3, 금요일=4, 토요일=5, 일요일=6.
- 시각은 08:00~21:30 사이에서 고르세요.
- minute은 0 또는 30만 사용하세요.
- 외부 통계나 존재하지 않는 수강생 행동 데이터를 지어내지 마세요.
- 현재 날짜와 강의 성격을 우선 고려하되, 이미 예약이 몰린 요일은 가능하면 피해서 업로드를 분산하세요.
- 같은 요일/시각이 이미 지났다면 시스템이 자동으로 다음 주 해당 시점으로 보냅니다.
- rationale은 짧은 한국어 한 문장으로 작성하세요.
""".strip()


def fallback_publish_payload(now_local: datetime) -> dict:
    return {
        "weekday": (now_local.weekday() + 1) % 7,
        "hour": 18,
        "minute": 0,
        "rationale": "자동 스케줄 응답을 얻지 못해 다음 가능한 저녁 시간으로 예약했습니다.",
    }


def validate_publish_payload(payload: dict) -> tuple[int, int, int]:
    weekday = int(payload["weekday"])
    hour = int(payload["hour"])
    minute = int(payload["minute"])
    if not 0 <= weekday <= 6:
        raise ValueError("AI publish weekday must be 0..6")
    if not 8 <= hour <= 21:
        raise ValueError("AI publish hour must be 8..21")
    if minute not in {0, 30}:
        raise ValueError("AI publish minute must be 0 or 30")
    return weekday, hour, minute
