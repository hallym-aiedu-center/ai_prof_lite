from types import SimpleNamespace

from modules.lecture import references


class FakeClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


async def test_rag_uses_openai_embeddings_for_semantic_retrieval(tmp_path, monkeypatch):
    source = tmp_path / "reference.txt"
    source.write_text(
        "사과와 배의 영양 성분을 비교하는 일반적인 과일 설명입니다.\n\n"
        "신경망 학습에서 기울기가 너무 작아져 앞단 레이어가 거의 학습되지 않는 현상을 다룹니다.\n\n"
        "운영체제의 파일 시스템과 디스크 스케줄링에 대한 설명입니다.",
        encoding="utf-8",
    )
    monkeypatch.setenv("REFERENCE_RAG_CHUNK_CHARS", "45")
    monkeypatch.setenv("REFERENCE_RAG_CHUNK_OVERLAP_CHARS", "0")
    monkeypatch.setenv("REFERENCE_RAG_TOP_K", "1")
    monkeypatch.setattr(references, "get_client", lambda **_: FakeClient())

    calls = []

    async def fake_embeddings(client, **kwargs):
        calls.append(kwargs)
        vectors = []
        for text in kwargs["input"]:
            # Query deliberately uses a paraphrase with little/no lexical overlap.
            semantic = (
                "역전파" in text
                or "gradient" in text.lower()
                or "기울기" in text
                or "앞단" in text
            )
            vectors.append(
                SimpleNamespace(embedding=[1.0, 0.0] if semantic else [0.0, 1.0])
            )
        return SimpleNamespace(data=vectors)

    monkeypatch.setattr(references, "embeddings_create", fake_embeddings)
    context = await references.build_reference_context(
        [{"name": "reference.txt", "path": str(source)}],
        title="딥러닝 역전파",
        topic="gradient가 앞쪽 층까지 제대로 전달되지 않는 문제와 해결법",
        api_key="test",
        user_id=1,
        lecture_id=7,
    )

    assert "기울기가 너무 작아져" in context
    assert "파일 시스템" not in context
    assert len(calls) >= 2
    assert all(call["model"] == "text-embedding-3-small" for call in calls)
    assert all(call["user_id"] == 1 and call["lecture_id"] == 7 for call in calls)


async def test_full_reference_mode_sends_original_file_to_responses(
    tmp_path, monkeypatch, plan
):
    import json
    from unittest.mock import AsyncMock

    from modules.lecture import planner

    source = tmp_path / "guide.txt"
    source.write_text("원본 전체 파일 내용", encoding="utf-8")

    class Files:
        def __init__(self):
            self.create = AsyncMock(return_value=SimpleNamespace(id="file-test"))
            self.delete = AsyncMock(return_value=None)

    class Responses:
        def __init__(self):
            self.create = AsyncMock(
                return_value=SimpleNamespace(
                    output_text=json.dumps(plan, ensure_ascii=False)
                )
            )

    class Client:
        def __init__(self):
            self.files = Files()
            self.responses = Responses()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    client = Client()
    monkeypatch.setattr(planner, "get_client", lambda **_: client)

    async def passthrough(client, **kwargs):
        kwargs.pop("user_id", None)
        kwargs.pop("lecture_id", None)
        kwargs.pop("budget_input_bytes", None)
        return await client.responses.create(**kwargs)

    monkeypatch.setattr(planner, "responses_create", passthrough)
    result = await planner.create_lecture_plan(
        api_key="test",
        title="전체 파일 테스트",
        topic="첨부 파일 전체를 근거로 작성",
        model="test-model",
        target_slide_count=4,
        reference_files=[
            {
                "name": "guide.txt",
                "path": str(source),
                "content_type": "text/plain",
                "size": source.stat().st_size,
            }
        ],
        reference_mode="full",
        user_id=1,
    )

    assert result == plan
    client.files.create.assert_awaited_once()
    client.files.delete.assert_awaited_once_with("file-test")
    request_input = client.responses.create.call_args.kwargs["input"]
    assert any(
        part.get("type") == "input_file" and part.get("file_id") == "file-test"
        for item in request_input
        if isinstance(item, dict)
        for part in item.get("content", [])
        if isinstance(part, dict)
    )
