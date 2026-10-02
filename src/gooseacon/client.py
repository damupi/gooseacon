from __future__ import annotations

from functools import wraps
from typing import Any
from urllib.parse import urlparse

import typer
from google.auth.exceptions import GoogleAuthError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from httplib2 import HttpLib2Error
from oauthlib.oauth2 import OAuth2Error
from pydantic import ValidationError
from requests.exceptions import RequestException

from gooseacon.auth import get_credentials
from gooseacon.config import load_config


def guarded(fn):
    """Stable CLI failures, stderr only, no tracebacks or credential contents."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except HttpError as exc:
            hints = {
                401: "Credentials expired; log in again.",
                403: "Check property access, OAuth scopes, API enablement, and quota.",
                404: "Check the exact property URL (including trailing slash) or sitemap path.",
                429: "Quota exceeded; wait before retrying.",
            }
            message = f"Google API error {exc.resp.status}: {exc.reason}"
            if hint := hints.get(exc.resp.status):
                message += f". {hint}"
        except (GoogleAuthError, OAuth2Error):
            message = "Google authentication failed. Check credentials or run gooseacon auth login."
        except (HttpLib2Error, RequestException):
            message = "Network request failed. Check your connection and try again."
        except ValidationError as exc:
            message = "; ".join(
                f"{'.'.join(map(str, e['loc'])) or 'request'}: {e['msg']}"
                for e in exc.errors(include_input=False, include_url=False)
            )
        except (ValueError, OSError) as exc:
            message = str(exc)
        else:
            return None
        typer.echo(f"Error: {message}", err=True)
        raise typer.Exit(1)

    return wrapper


def service(*, inspection: bool = False, write: bool = False) -> Any:
    credentials = get_credentials(load_config(), write=write)
    return build(
        "searchconsole" if inspection else "webmasters",
        "v1" if inspection else "v3",
        credentials=credentials,
        cache_discovery=False,
    )


def site_url(value: str | None) -> str:
    value = value or load_config().default_site_url
    if not value:
        raise ValueError("Pass --site-url or set GSC_SITE_URL / config default_site_url.")
    if value.startswith("sc-domain:") and value.removeprefix("sc-domain:"):
        return value
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Site must be an http(s) URL or sc-domain:example.com.")
    return value


def execute(request: Any) -> dict:
    return request.execute(num_retries=3)
