import json
from pathlib import Path

from core.version import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_version_metadata_is_consistent():
    manifest = json.loads((ROOT / "bundle_manifest.json").read_text(encoding="utf-8"))
    readme = (ROOT / "README.MD").read_text(encoding="utf-8")

    assert manifest["version"] == __version__
    assert f"현재 애플리케이션 버전은 `{__version__}`" in readme
