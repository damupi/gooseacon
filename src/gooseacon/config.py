"""Disk settings and environment overrides. Secrets never appear in config show."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    auth_method: Literal["oauth2", "service-account", "token", "adc"] = "adc"
    key_file: str | None = None
    default_site_url: str | None = None
    output_format: Literal["json", "csv", "table"] = "json"


def config_dir() -> Path:
    return Path(os.environ.get("GOOSEACON_CONFIG_DIR", Path.home() / ".config" / "gooseacon"))


def load_config(*, overrides: bool = True) -> Config:
    path = config_dir() / "config.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(data, dict):
        raise ValueError("Config file must contain a JSON object.")
    if overrides:
        for env, field in {
            "GSC_AUTH_METHOD": "auth_method",
            "GSC_KEY_FILE": "key_file",
            "GSC_SITE_URL": "default_site_url",
            "GSC_OUTPUT_FORMAT": "output_format",
        }.items():
            if os.environ.get(env):
                data[field] = os.environ[env]
    return Config.model_validate(data)


def write_private(path: Path, text: str) -> None:
    """Atomic replacement with owner-only permissions, including refresh tokens."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(text)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save_config(config: Config) -> None:
    write_private(config_dir() / "config.json", config.model_dump_json(indent=2))
