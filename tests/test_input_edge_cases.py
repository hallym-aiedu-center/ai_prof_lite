import io
import re
from pathlib import Path

import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from app import app
from core.config import server_openai_account_budget_usd
from modules.lecture.references import save_reference_files


def _csrf_token(html: str) -> str:
    match = re.search(
        r'name="csrf_token"\s+value="([^"]+)"',
        html,
    )
    assert match is not None
    return match.group(1)


def test_registration_code_accepts_unicode(monkeypatch):
    """한글 가입 코드가 compare_digest에서 TypeError를 내지 않아야 한다."""
    monkeypatch.setenv(
        "REGISTRATION_CODE",
        "한글-가입-코드",
    )

    with TestClient(app) as client:
        page = client.get("/register")
        token = _csrf_token(page.text)

        denied = client.post(
            "/register",
            data={
                "email": "unicode-code-denied@example.test",
                "password": "password-123",
                "password_confirm": "password-123",
                "registration_code_input": "틀린-가입-코드",
                "csrf_token": token,
            },
        )

        assert denied.status_code == 403

        token = _csrf_token(denied.text)

        allowed = client.post(
            "/register",
            data={
                "email": "unicode-code-allowed@example.test",
                "password": "password-123",
                "password_confirm": "password-123",
                "registration_code_input": "한글-가입-코드",
                "csrf_token": token,
            },
        )

        assert allowed.status_code == 200


async def test_reference_storage_uses_uuid_filename_for_long_unicode_name():
    """긴 한글 원본명과 무관하게 실제 디스크 파일명은 UUID여야 한다."""
    upload = UploadFile(
        io.BytesIO(b"reference text"),
        filename=("한" * 90) + ".txt",
        headers=Headers({
            "content-type": "text/plain",
        }),
    )

    saved = await save_reference_files([upload])

    assert len(saved) == 1

    item = saved[0]
    path = Path(item["path"])

    # UUID hex 32자리 + 검증된 확장자만 디스크에 사용
    assert re.fullmatch(
        r"[0-9a-f]{32}\.txt",
        path.name,
    )

    assert path.read_bytes() == b"reference text"

    # 표시용 이름은 별도 metadata로 유지
    assert item["name"].endswith(".txt")
    assert item["name"].startswith("한")


@pytest.mark.parametrize(
    "raw",
    [
        "NaN",
        "nan",
        "inf",
        "+inf",
        "-inf",
    ],
)
def test_server_budget_rejects_non_finite_values(
    monkeypatch,
    raw,
):
    """NaN/Infinity가 예산 상한 검사를 우회하면 안 된다."""
    monkeypatch.setenv(
        "SERVER_OPENAI_ACCOUNT_BUDGET_USD",
        raw,
    )

    with pytest.raises(
        ValueError,
        match="SERVER_OPENAI_ACCOUNT_BUDGET_USD",
    ):
        server_openai_account_budget_usd()
