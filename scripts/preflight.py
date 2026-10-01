import importlib
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
from core.config import openai_key_mode, session_secret
from core.database.secrets import _get_cipher
from modules.lecture.avatar import get_ditto_paths


def main():
    failures = []
    for name in (
        "fastapi",
        "aiosqlite",
        "argon2",
        "cryptography",
        "openai",
        "pptx",
        "PIL",
        "jinja2",
        "multipart",
        "jsonschema",
        "httpx",
        "uvicorn",
    ):
        try:
            importlib.import_module(name)
        except ImportError:
            failures.append(f"Python package: {name}")
    for name in (
        os.getenv("FFMPEG_BIN", "ffmpeg"),
        os.getenv("FFPROBE_BIN", "ffprobe"),
    ):
        if not shutil.which(name):
            failures.append(f"Executable: {name}")
    for validator in (session_secret, _get_cipher):
        try:
            validator()
        except (RuntimeError, ValueError) as exc:
            failures.append(str(exc))
    try:
        if (
            openai_key_mode() == "server"
            and not os.getenv("SERVER_OPENAI_API_KEY", "").strip()
        ):
            failures.append(
                "SERVER_OPENAI_API_KEY is required when OPENAI_KEY_MODE=server"
            )
    except ValueError as exc:
        failures.append(str(exc))
    root, data, config = get_ditto_paths()
    for path in (root / "inference.py", data, config):
        if not path.exists():
            failures.append(f"Ditto: {path}")
    python = os.getenv("DITTO_PYTHON")
    if python and not shutil.which(python):
        failures.append("DITTO_PYTHON 실행 파일이 없습니다.")
    if failures:
        for failure in failures:
            print("MISSING:", failure)
        return 1
    print("OK: 필수 패키지, 설정 및 외부 실행 파일 경로 확인 완료")
    print(
        "OpenAI/Moodle 연결, CUDA 및 Ditto 모델 실행 여부는 실제 환경에서 확인하세요."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
