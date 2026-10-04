import json
from pathlib import Path

from core.version import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_version_metadata_is_consistent():
    manifest = json.loads((ROOT / "bundle_manifest.json").read_text(encoding="utf-8"))

    assert manifest["version"] == __version__

    version_marker = f"> Version `{__version__}`"

    for filename in (
        "README.md",
        "README_EN.md",
        "README_JA.md",
        "README_ZH.md",
    ):
        readme = (ROOT / filename).read_text(encoding="utf-8")
        assert version_marker in readme, (
            f"{filename} version does not match {__version__}"
        )
