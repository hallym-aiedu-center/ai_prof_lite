import io
import socket
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.database.client import get_connection
from core.database.migrations import init_database
from modules.lecture.repository import create_lecture


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CREDENTIAL_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("SESSION_SECRET", "test-session-" + "x" * 40)
    monkeypatch.setenv("OPENAI_API_KEY", "test-no-network")
    monkeypatch.setenv("DITTO_ROOT", str(tmp_path / "missing-ditto"))
    for key in (
        "MOODLE_ALLOWED_ORIGINS",
        "MOODLE_PRIVATE_ORIGINS",
        "MOODLE_URL",
        "MOODLE_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)

    from core.database.secrets import _get_cipher

    _get_cipher.cache_clear()
    original_connect = socket.socket.connect

    def blocked_connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError("Tests must not make real network connections")
        return original_connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", blocked_connect)


@pytest.fixture
async def database():
    await init_database()
    db = await get_connection()
    try:
        await db.execute(
            "INSERT INTO users(id,email,password_hash) VALUES(1,'owner@example.test','unused')"
        )
        await db.commit()
    finally:
        await db.close()


@pytest.fixture
async def make_lecture(database, tmp_path):
    async def make(**overrides):
        portrait = tmp_path / "portrait.png"
        Image.new("RGB", (16, 16)).save(portrait)
        values = {
            "user_id": 1,
            "title": "테스트 강의",
            "topic": "테스트 주제",
            "text_model": "test-model",
            "image_model": "test-image",
            "tts_model": "test-tts",
            "tts_voice": "alloy",
            "generate_images": True,
            "moodle_course_id": None,
            "moodle_section_num": None,
            "moodle_deploy_mode": "create",
            "moodle_videotracker_cmid": None,
            "upload_to_moodle": False,
            "portrait_path": str(portrait),
        }
        values.update(overrides)
        return await create_lecture(**values)

    return make


@pytest.fixture
def portrait_bytes():
    stream = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(stream, format="PNG")
    return stream.getvalue()


@pytest.fixture
def plan():
    return {
        "title": "테스트",
        "learning_objectives": ["목표"],
        "slides": [
            {
                "title": f"Slide {i}",
                "bullets": ["Example"],
                "narration": "test narration",
                "image_prompt": "Example image",
            }
            for i in range(4)
        ],
        "quiz": [
            {
                "question": f"Q{i}",
                "choices": ["A", "B", "C", "D"],
                "answer_index": 0,
                "explanation": "A",
            }
            for i in range(3)
        ],
    }
