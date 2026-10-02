"""Search Console authentication independent of GA4 credentials."""

from __future__ import annotations

import os
from pathlib import Path

import google.auth
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from gooseacon.config import Config, config_dir, write_private

READ_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
WRITE_SCOPE = "https://www.googleapis.com/auth/webmasters"


def token_path() -> Path:
    return config_dir() / "credentials.json"


def login_oauth(
    client_file: Path, *, readonly: bool = True, port: int = 0, open_browser: bool = True
) -> None:
    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_file), scopes=[READ_SCOPE if readonly else WRITE_SCOPE]
    )
    creds = flow.run_local_server(
        port=port, open_browser=open_browser, access_type="offline", prompt="consent"
    )
    write_private(token_path(), creds.to_json())


def get_credentials(config: Config, *, write: bool = False):
    scope = WRITE_SCOPE if write else READ_SCOPE
    method = config.auth_method
    if method == "service-account":
        key = config.key_file or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if not key:
            raise ValueError("Set GSC_KEY_FILE or log in with --key-file.")
        return service_account.Credentials.from_service_account_file(key, scopes=[scope])
    if method == "token":
        token = os.environ.get("GSC_ACCESS_TOKEN")
        if not token:
            raise ValueError("Set GSC_ACCESS_TOKEN. Access tokens are not saved to disk.")
        return Credentials(token=token)
    if method == "adc":
        creds, _ = google.auth.default(scopes=[scope])
        return creds
    if not token_path().exists():
        raise ValueError("Run gooseacon auth login --client-secret /path/to/client_secret.json.")
    creds = Credentials.from_authorized_user_file(str(token_path()))
    if write and not creds.has_scopes([WRITE_SCOPE]):
        raise ValueError("Write access requires gooseacon auth login --client-secret FILE --write.")
    if not creds.valid:
        if not creds.refresh_token:
            raise ValueError("OAuth credentials have expired. Run gooseacon auth login again.")
        creds.refresh(Request())
        write_private(token_path(), creds.to_json())
    return creds
