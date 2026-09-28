import copy
import json
import re

from jsonschema import validate
from openai import BadRequestError

from core.openai.client import get_client

LECTURE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "title",
        "learning_objectives",
        "slides",
        "quiz",
    ],
    "properties": {
        "title": {"type": "string"},
        "learning_objectives": {
            "type": "array",
            "items": {"type": "string"},
        },
        "slides": {
            "type": "array",
            "minItems": 4,
            "maxItems": 14,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "title",
                    "bullets",
                    "narration",
                    "image_prompt",
                ],
                "properties": {
                    "title": {"type": "string"},
                    "bullets": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "narration": {"type": "string"},
                    "image_prompt": {"type": "string"},
                },
            },
        },
        "quiz": {
            "type": "array",
            "minItems": 3,
            "maxItems": 10,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "question",
                    "choices",
                    "answer_index",
                    "explanation",
                ],
                "properties": {
                    "question": {"type": "string"},
                    "choices": {
                        "type": "array",
                        "minItems": 4,
                        "maxItems": 4,
                        "items": {"type": "string"},
                    },
                    "answer_index": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 3,
                    },
                    "explanation": {"type": "string"},
                },
            },
        },
    },
}


def _parse_json(text: str) -> dict:
    text = text.strip()

    if text.startswith("```"):
        text = re.sub(
            r"^```(?:json)?\s*|\s*```$",
            "",
            text,
            flags=re.IGNORECASE,
        )

    return json.loads(text)


def structured_output_unsupported(error: BadRequestError) -> bool:
    body = error.body if isinstance(error.body, dict) else {}
    body = body.get("error", body)
    if not isinstance(body, dict):
        return False
    code = str(body.get("code") or "").lower()
    param = str(body.get("param") or "").lower()
    message = str(body.get("message") or "").lower()
    if code in {"invalid_json_schema", "invalid_api_key"}:
        return False
    format_related = param in {"text.format", "text.format.type", "response_format"} or "json_schema" in message
    explicitly_unsupported = code in {"unsupported_parameter", "unsupported_value"} or any(
        wording in message for wording in ("not supported", "does not support", "unsupported")
    )
    return format_related and explicitly_unsupported


def lecture_schema_for_slide_count(slide_count: int) -> dict:
    count = max(4, min(14, int(slide_count)))
    schema = copy.deepcopy(LECTURE_SCHEMA)
    schema["properties"]["slides"]["minItems"] = count
    schema["properties"]["slides"]["maxItems"] = count
    return schema


async def create_lecture_plan(
    *,
    api_key: str,
    title: str,
    topic: str,
    model: str,
    target_duration_minutes: int = 40,
    target_slide_count: int = 10,
) -> dict:
    client = get_client(api_key=api_key)
    target_duration_minutes = max(10, min(180, int(target_duration_minutes)))
    target_slide_count = max(4, min(14, int(target_slide_count)))
    average_minutes = target_duration_minutes / target_slide_count
    schema = lecture_schema_for_slide_count(target_slide_count)

    prompt = f"""
대학/전문교육용 강의 콘텐츠를 설계하세요.

강의 제목:
{title}

강의 주제 및 요청:
{topic}

강의 분량 목표:
- 총 강의시간: 약 {target_duration_minutes}분
- 슬라이드 수: 정확히 {target_slide_count}장
- 평균 설명시간: 슬라이드당 약 {average_minutes:.1f}분

요구사항:
- slides 배열은 반드시 정확히 {target_slide_count}개로 작성.
- 전체 narration을 실제 TTS로 읽었을 때 약 {target_duration_minutes}분 분량이 되도록 충분히 상세하게 작성.
- 모든 슬라이드를 똑같은 길이로 만들지 말고, 도입/정리는 짧게 하고 핵심 개념·원리·사례·비교·실습 설명은 더 길게 배분.
- 각 슬라이드는 핵심 bullet과 교수 설명용 narration을 함께 작성.
- narration은 실제 교수가 수업하듯 자연스럽고 연결감 있는 한국어 문장으로 작성. 단순 bullet 낭독이나 지나치게 짧은 요약은 금지.
- 슬라이드 내용과 narration이 정확히 대응해야 함.
- image_prompt는 슬라이드 보조 이미지 생성용 영어 프롬프트. 이미지가 불필요하면 빈 문자열.
- quiz는 실제 slides/narration에서 가르친 내용만 출제.
- quiz는 4지선다형으로 작성.
- 과장된 마케팅 문구 대신 교육적으로 명확한 문체 사용.
"""

    async with client:
        try:
            response = await client.responses.create(
                model=model, input=prompt,
                text={"format": {"type": "json_schema", "name": "lecture_plan",
                                 "strict": True, "schema": schema}},
            )
        except BadRequestError as exc:
            if not structured_output_unsupported(exc):
                raise
            response = await client.responses.create(
                model=model,
                input=prompt + "\n반드시 JSON만 출력하세요. 스키마:\n" + json.dumps(schema, ensure_ascii=False),
            )
    plan = _parse_json(response.output_text)
    validate(instance=plan, schema=schema)
    return plan
