"""Release discovery, safe upgrade, cache, and CLI integration tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from gooseacon import update
from gooseacon.cli import app

runner = CliRunner()
LS_REMOTE = "a\trefs/tags/v0.1.0\nb\trefs/tags/v0.10.0\nc\trefs/tags/v0.2.0-rc1\n"


def completed(stdout: str = "", returncode: int = 0, stderr: str = "") -> MagicMock:
    return MagicMock(stdout=stdout, stderr=stderr, returncode=returncode)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOSEACON_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.delenv(update.DISABLE_ENV, raising=False)
    monkeypatch.delenv("CI", raising=False)


def test_curl_argv_disables_user_config_and_bounds_https(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update.shutil, "which", lambda _: "/usr/bin/curl")
    argv = update._curl_argv(2.5)
    assert argv is not None
    assert argv[:2] == ["/usr/bin/curl", "--disable"]
    assert argv[argv.index("--max-time") + 1] == "2.500"
    assert "=https" in argv
    assert argv[-1] == update.RELEASE_API


def test_latest_release_api_accepts_only_stable_release(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update.shutil, "which", lambda _: "/usr/bin/curl")
    payload = json.dumps({"tag_name": "v0.2.0", "draft": False, "prerelease": False})
    with patch.object(update.subprocess, "run", return_value=completed(payload)):
        assert update.latest_release_api(3.0) == "0.2.0"
    for bad in (
        "not json",
        json.dumps({"tag_name": "v0.2.0-rc1"}),
        json.dumps({"tag_name": "v0.2.0", "draft": True}),
        json.dumps({"tag_name": "v0.2.0", "prerelease": True}),
    ):
        with patch.object(update.subprocess, "run", return_value=completed(bad)):
            assert update.latest_release_api(3.0) is None


@pytest.mark.parametrize("failure", [OSError("missing"), subprocess.TimeoutExpired("curl", 3)])
def test_latest_release_api_failures_are_silent(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    monkeypatch.setattr(update.shutil, "which", lambda _: "/usr/bin/curl")
    with patch.object(update.subprocess, "run", side_effect=failure):
        assert update.latest_release_api(3.0) is None


def test_git_safe_env_ignores_credentials_headers_and_rewrites(tmp_path: Path) -> None:
    global_config = tmp_path / "gitconfig"
    global_config.write_text(
        "[http]\n\textraHeader = Authorization: Bearer secret\n"
        '[url "git@github.com:"]\n\tinsteadOf = https://github.com/\n'
    )
    env = update.git_safe_env(
        {
            "PATH": os.environ.get("PATH", ""),
            "GIT_CONFIG_GLOBAL": str(global_config),
            "GIT_ASKPASS": "/leak/askpass",
            "GIT_SSH_COMMAND": "ssh -i /leak/key",
        }
    )
    resolved = subprocess.run(
        ["git", "ls-remote", "--get-url", update.REPO_GIT_HTTPS],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        check=True,
    )
    headers = subprocess.run(
        ["git", "config", "--get-all", "http.extraHeader"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        check=False,
    )
    assert resolved.stdout.strip() == update.REPO_GIT_HTTPS
    assert "Authorization" not in headers.stdout
    assert "GIT_ASKPASS" not in env
    assert "GIT_SSH_COMMAND" not in env
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"


def test_latest_release_git_picks_highest_stable_tag() -> None:
    with patch.object(update.subprocess, "run", return_value=completed(LS_REMOTE)) as run:
        assert update.latest_release_git(4.0) == "0.10.0"
    assert run.call_args.kwargs["timeout"] == 4.0
    assert run.call_args.kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert run.call_args.kwargs["cwd"]


def test_latest_release_uses_api_then_reserved_git_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = iter([100.0, 100.0, 103.5])
    monkeypatch.setattr(update.time, "monotonic", lambda: next(clock))
    with (
        patch.object(update, "latest_release_api", return_value=None) as api,
        patch.object(update, "latest_release_git", return_value="0.2.0") as git,
    ):
        assert update.latest_release(5.0) == "0.2.0"
    assert api.call_args.args[0] == pytest.approx(3.0)
    assert git.call_args.args[0] == pytest.approx(1.5)


@pytest.mark.parametrize(
    "latest,current,expected",
    [("0.2.0", "0.1.0", True), ("0.1.0", "0.1.0", False), (None, "0.1.0", False)],
)
def test_is_newer(latest: str | None, current: str, expected: bool) -> None:
    assert update.is_newer(latest, current) is expected


class FakeDist:
    def __init__(self, direct_url: str | None) -> None:
        self.direct_url = direct_url

    def read_text(self, _: str) -> str | None:
        return self.direct_url


def test_install_detection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    direct = json.dumps({"url": "file:///src/goose%20acon", "dir_info": {"editable": True}})
    monkeypatch.setattr(update.metadata, "distributions", lambda **_: iter([FakeDist(direct)]))
    assert update.install_info() == {"kind": "editable", "path": "/src/goose acon"}

    monkeypatch.setattr(update.metadata, "distributions", lambda **_: iter([]))
    monkeypatch.setattr(update.sys, "prefix", str(tmp_path))
    (tmp_path / "uv-receipt.toml").write_text("")
    assert update.install_info()["kind"] == "uv"
    (tmp_path / "uv-receipt.toml").unlink()
    assert update.install_info()["kind"] == "pip"


@pytest.mark.parametrize("kind", ["uv", "pip"])
def test_upgrade_commands_are_tag_pinned_github_only(kind: str) -> None:
    with patch.object(update, "install_info", return_value={"kind": kind, "path": ""}):
        command = update.upgrade_command("0.2.0")
        argv = update.upgrade_argv("0.2.0")
    assert "git+https://github.com/damupi/gooseacon@v0.2.0" in command
    assert argv is not None and argv[-1].endswith("gooseacon@v0.2.0")
    assert "pypi" not in command.lower()
    assert not command.endswith(" gooseacon")
    if kind == "pip":
        assert argv[:3] == [sys.executable, "-m", "pip"]


def test_editable_upgrade_is_guidance_only() -> None:
    info = {"kind": "editable", "path": "/src/my gooseacon"}
    with patch.object(update, "install_info", return_value=info):
        assert update.upgrade_argv("0.2.0") is None
        assert update.upgrade_command("0.2.0") == (
            "git -C '/src/my gooseacon' pull  # editable install: update your checkout"
        )


def test_perform_upgrade_uses_safe_environment() -> None:
    run = MagicMock(return_value=completed("installed"))
    with patch.object(update, "install_info", return_value={"kind": "uv", "path": ""}):
        result = update.perform_upgrade("0.2.0", runner=run)
    assert result.stdout == "installed"
    assert run.call_args.kwargs["env"]["GIT_CONFIG_GLOBAL"] == os.devnull
    assert run.call_args.kwargs["check"] is False


def test_perform_upgrade_errors() -> None:
    with patch.object(update, "install_info", return_value={"kind": "editable", "path": "/src"}):
        with pytest.raises(update.UpgradeError, match="editable"):
            update.perform_upgrade("0.2.0", runner=MagicMock())
    run = MagicMock(return_value=completed(returncode=1, stderr="network failed"))
    with patch.object(update, "install_info", return_value={"kind": "uv", "path": ""}):
        with pytest.raises(update.UpgradeError, match="network failed"):
            update.perform_upgrade("0.2.0", runner=run)


def test_cache_is_private_and_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    with patch.object(update, "latest_release", return_value="0.2.0") as latest:
        assert update.cached_latest_release() == "0.2.0"
        assert update.cached_latest_release() == "0.2.0"
    latest.assert_called_once()
    assert update.cache_path().stat().st_mode & 0o777 == 0o600


def test_stale_cache_refreshes(monkeypatch: pytest.MonkeyPatch) -> None:
    update.write_private(
        update.cache_path(),
        json.dumps({"checked_at": int(time.time()) - update.CHECK_INTERVAL - 1, "latest": "0.1.0"}),
    )
    with patch.object(update, "latest_release", return_value="0.2.0"):
        assert update.cached_latest_release() == "0.2.0"


def test_notice_gating_and_network_free_render(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "1")
    assert update.should_check() is False
    monkeypatch.delenv("CI")
    monkeypatch.setenv(update.DISABLE_ENV, "1")
    assert update.should_check() is False
    with patch.object(update, "latest_release") as latest:
        notice = update.upgrade_notice("0.2.0", "0.1.0")
    assert "gooseacon upgrade" in notice
    latest.assert_not_called()


def test_version_command_json() -> None:
    with (
        patch("gooseacon.cli.installed_version", return_value="0.1.0"),
        patch("gooseacon.cli.latest_release", return_value="0.2.0"),
        patch("gooseacon.cli.upgrade_command", return_value="uv tool install X@v0.2.0"),
    ):
        result = runner.invoke(app, ["version", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "installed": "0.1.0",
        "latest": "0.2.0",
        "update_available": True,
        "upgrade_command": "uv tool install X@v0.2.0",
    }


def test_upgrade_yes_executes() -> None:
    with (
        patch("gooseacon.cli.installed_version", return_value="0.1.0"),
        patch("gooseacon.cli.latest_release", return_value="0.2.0"),
        patch("gooseacon.cli.install_info", return_value={"kind": "uv", "path": ""}),
        patch("gooseacon.cli.upgrade_command", return_value="uv tool install X@v0.2.0"),
        patch("gooseacon.cli.perform_upgrade", return_value=completed("installed")) as perform,
    ):
        result = runner.invoke(app, ["upgrade", "--yes"])
    assert result.exit_code == 0
    assert "Upgraded gooseacon to 0.2.0" in result.stdout
    perform.assert_called_once_with("0.2.0")


def test_upgrade_editable_does_not_prompt_or_execute() -> None:
    with (
        patch("gooseacon.cli.installed_version", return_value="0.1.0"),
        patch("gooseacon.cli.latest_release", return_value="0.2.0"),
        patch("gooseacon.cli.install_info", return_value={"kind": "editable", "path": "/src"}),
        patch("gooseacon.cli.upgrade_command", return_value="git -C /src pull"),
        patch("gooseacon.cli.perform_upgrade") as perform,
    ):
        result = runner.invoke(app, ["upgrade"])
    assert result.exit_code == 0
    assert "Editable install detected" in result.stdout
    assert "Proceed" not in result.stdout
    perform.assert_not_called()


def test_normal_command_notice_is_best_effort() -> None:
    with patch("gooseacon.cli.pending_notice", return_value="new release"):
        result = runner.invoke(app, ["auth", "--help"])
    assert result.exit_code == 0
    assert "new release" in result.stderr
    with (
        patch("gooseacon.cli.pending_notice", return_value="notice"),
        patch("gooseacon.cli.typer.echo", side_effect=RuntimeError("closed")),
    ):
        result = runner.invoke(app, ["auth", "--help"])
    assert result.exit_code == 0
