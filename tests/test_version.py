"""Release automation must keep runtime, packaging, and locked project versions aligned."""

import json
import tomllib
from pathlib import Path

from gooseacon import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_version_alignment():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    manifest = json.loads((ROOT / ".release-please-manifest.json").read_text())
    assert project["project"]["version"] == __version__
    package = next(p for p in lock["package"] if p["name"] == "gooseacon")
    assert package["version"] == __version__
    # Empty only while bootstrapping the first release PR.
    if manifest:
        assert manifest["."] == __version__
