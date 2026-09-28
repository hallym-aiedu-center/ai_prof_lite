import copy
import json
import os
import re
from contextlib import suppress
from pathlib import Path

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


def _responses_input(prompt: str, file_ids: list[str]) -> str | list[dict]:
    if not file_ids:
        return prompt
    return [
        {
            "role": "user",
            "content": [
                *({"type": "input_file", "file_id": file_id} for file_id in file_ids),
                {"type": "input_text", "text": prompt},
            ],
        }
    ]


async def _upload_reference_files(client, files: list[dict] | None) -> list[str]:
    uploaded: list[str] = []
    try:
        for item in files or []:
            path = Path(str(item.get("path") or ""))
            if not path.is_file():
                raise FileNotFoundError(f"참고자료 파일을 찾을 수 없습니다: {path}")
            with path.open("rb") as handle:
                created = await client.files.create(file=handle, purpose="user_data")
            uploaded.append(str(created.id))
        return uploaded
    except BaseException:
        for file_id in uploaded:
            with suppress(Exception):
                await client.files.delete(file_id)
        raise


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



def duration_generation_ratio() -> float:
    """Return the narration headroom used to reliably clear the hard minimum."""
    try:
        value = float(os.getenv("LECTURE_DURATION_GENERATION_RATIO", "1.05"))
    except ValueError:
        value = 1.05
    return max(1.0, min(1.25, value))


def _narration_revision_schema(slide_count: int) -> dict:
    count = max(1, int(slide_count))
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["narrations"],
        "properties": {
            "narrations": {
                "type": "array",
                "minItems": count,
                "maxItems": count,
                "items": {"type": "string"},
            }
        },
    }

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
    reference_context: str = "",
    reference_files: list[dict] | None = None,
    reference_mode: str = "rag",
) -> dict:
    client = get_client(api_key=api_key)
    target_duration_minutes = max(10, min(180, int(target_duration_minutes)))
    target_slide_count = max(4, min(14, int(target_slide_count)))
    generation_minutes = target_duration_minutes * duration_generation_ratio()
    average_minutes = generation_minutes / target_slide_count
    schema = lecture_schema_for_slide_count(target_slide_count)

    reference_mode = str(reference_mode or "rag").strip().lower()
    if reference_mode not in {"rag", "full"}:
        raise ValueError("reference_mode must be 'rag' or 'full'.")

    reference_context = str(reference_context or "").strip()
    has_reference_files = bool(reference_files)
    if reference_mode == "rag" and reference_context:
        grounding = (
            "\n\n참고자료는 RAG 방식으로 분할·검색한 관련 청크입니다. "
            "다음 발췌를 사실 근거로 우선 사용하세요:\n" + reference_context
        )
    elif reference_mode == "full" and has_reference_files:
        grounding = (
            "\n\n첨부 참고자료 원본 파일이 이 요청에 함께 전달됩니다. "
            "파일 전체 내용을 사실 근거로 우선 사용하고, 자료와 충돌하는 내용을 만들지 마세요."
        )
    else:
        grounding = "\n\n첨부 참고자료가 없습니다. 일반 지식으로 작성하되 불확실한 사실은 단정하지 마세요."

    prompt = f"""
대학/전문교육용 강의 콘텐츠를 설계하세요.

강의 제목:
{title}

강의 주제 및 요청:
{topic}

강의 분량 목표:
- 최소 강의시간: 실제 TTS 재생시간 기준 {target_duration_minutes}분 이상
- narration 생성 목표: 약 {generation_minutes:.1f}분
- 슬라이드 수: 정확히 {target_slide_count}장
- 평균 설명시간: 슬라이드당 약 {average_minutes:.1f}분

요구사항:
- slides 배열은 반드시 정확히 {target_slide_count}개로 작성.
- 전체 narration을 실제 TTS로 읽었을 때 최소 {target_duration_minutes}분을 안정적으로 넘기도록 약 {generation_minutes:.1f}분 분량으로 충분히 상세하게 작성.
- 모든 슬라이드를 똑같은 길이로 만들지 말고, 도입/정리는 짧게 하고 핵심 개념·원리·사례·비교·실습 설명은 더 길게 배분.
- 각 슬라이드는 핵심 bullet과 교수 설명용 narration을 함께 작성.
- narration은 실제 교수가 수업하듯 자연스럽고 연결감 있는 한국어 문장으로 작성. 단순 bullet 낭독이나 지나치게 짧은 요약은 금지.
- 슬라이드 내용과 narration이 정확히 대응해야 함.
- image_prompt는 슬라이드 보조 이미지 생성용 영어 프롬프트. 이미지가 불필요하면 빈 문자열.
- quiz는 실제 slides/narration에서 가르친 내용만 출제.
- quiz는 4지선다형으로 작성.
- 과장된 마케팅 문구 대신 교육적으로 명확한 문체 사용.
- 참고자료가 있으면 참고자료와 충돌하는 내용을 만들지 말고, 참고자료에 없는 세부 수치나 고유 사실은 신중하게 다룰 것.
{grounding}
"""

    async with client:
        uploaded_file_ids: list[str] = []
        try:
            if reference_mode == "full" and has_reference_files:
                uploaded_file_ids = await _upload_reference_files(client, reference_files)

            try:
                response = await client.responses.create(
                    model=model,
                    input=_responses_input(prompt, uploaded_file_ids),
                    text={"format": {"type": "json_schema", "name": "lecture_plan",
                                     "strict": True, "schema": schema}},
                )
            except BadRequestError as exc:
                if not structured_output_unsupported(exc):
                    raise
                fallback_prompt = (
                    prompt
                    + "\n반드시 JSON만 출력하세요. 스키마:\n"
                    + json.dumps(schema, ensure_ascii=False)
                )
                response = await client.responses.create(
                    model=model,
                    input=_responses_input(fallback_prompt, uploaded_file_ids),
                )
        finally:
            for file_id in uploaded_file_ids:
                with suppress(Exception):
                    await client.files.delete(file_id)
    plan = _parse_json(response.output_text)
    validate(instance=plan, schema=schema)
    return plan


async def expand_lecture_narrations(
    *,
    api_key: str,
    plan: dict,
    model: str,
    actual_duration_seconds: float,
    minimum_duration_seconds: float,
    attempt: int = 1,
) -> dict:
    """Expand narration only, preserving slide structure and quiz content."""
    slides = list(plan.get("slides") or [])
    if not slides:
        raise ValueError("Lecture plan has no slides to expand.")

    actual = max(1.0, float(actual_duration_seconds))
    minimum = max(actual, float(minimum_duration_seconds))
    buffered_target = minimum * duration_generation_ratio()
    requested_factor = max(1.10, buffered_target / actual)
    # Avoid asking the model for an extreme one-shot rewrite. Repeated corrections
    # are more reliable and keep individual responses within a manageable size.
    requested_factor = min(2.0, requested_factor)

    payload = [
        {
            "slide_index": index,
            "title": str(slide.get("title") or ""),
            "bullets": list(slide.get("bullets") or []),
            "narration": str(slide.get("narration") or ""),
        }
        for index, slide in enumerate(slides, start=1)
    ]
    schema = _narration_revision_schema(len(slides))
    prompt = f"""
기존 대학/전문교육용 강의의 narration만 보강하세요.

실제 TTS 측정 결과:
- 현재 재생시간: {actual / 60:.2f}분
- 반드시 충족해야 하는 최소 재생시간: {minimum / 60:.2f}분
- 이번 보강의 안전 목표: 약 {buffered_target / 60:.2f}분
- 권장 narration 분량 증가 배수: 약 {requested_factor:.2f}배
- 보강 시도: {max(1, int(attempt))}회차

규칙:
- 슬라이드 수, 순서, 제목, bullets, image_prompt, quiz는 변경하지 않습니다.
- 반환값에는 슬라이드 순서대로 narration 문자열만 정확히 {len(slides)}개 넣습니다.
- 기존 narration보다 짧게 만들지 마세요.
- 도입과 결론은 과도하게 늘리지 말고, 핵심 개념·원리·사례·비교·적용·주의점 설명을 중심으로 확장하세요.
- 슬라이드에 없는 전혀 새로운 주제를 억지로 추가하지 마세요.
- 단순 반복이나 의미 없는 문장으로 시간을 채우지 말고 실제 강의에 도움이 되는 설명을 추가하세요.
- 실제 교수가 자연스럽게 설명하는 한국어 구어체 문장으로 작성하세요.

현재 슬라이드:
{json.dumps(payload, ensure_ascii=False)}
"""

    client = get_client(api_key=api_key)
    async with client:
        try:
            response = await client.responses.create(
                model=model,
                input=prompt,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "lecture_narration_revision",
                        "strict": True,
                        "schema": schema,
                    }
                },
            )
        except BadRequestError as exc:
            if not structured_output_unsupported(exc):
                raise
            response = await client.responses.create(
                model=model,
                input=prompt + "\n반드시 JSON만 출력하세요. 스키마:\n" + json.dumps(schema, ensure_ascii=False),
            )

    revised = _parse_json(response.output_text)
    validate(instance=revised, schema=schema)

    updated = copy.deepcopy(plan)
    for slide, new_text in zip(updated["slides"], revised["narrations"], strict=True):
        old_text = str(slide.get("narration") or "").strip()
        candidate = str(new_text or "").strip()
        # The model is instructed not to shorten narration. Enforce that invariant
        # locally so a correction pass can never make the duration problem worse.
        if len(candidate) < len(old_text):
            candidate = old_text
        slide["narration"] = candidate
    return updated
