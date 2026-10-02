"""Exercise Google's real discovery client without sending network requests."""

import json

import pytest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from httplib2 import ServerNotFoundError
from oauthlib.oauth2 import AccessDeniedError
from typer.testing import CliRunner

from gooseacon.analytics import Query
from gooseacon.cli import app
from gooseacon.config import Config, save_config


@pytest.mark.parametrize("inspection", [False, True])
def test_discovery_contract(inspection):
    api = build(
        "searchconsole" if inspection else "webmasters",
        "v1" if inspection else "v3",
        credentials=Credentials(token="test-placeholder"),
        cache_discovery=False,
    )
    if inspection:
        req = (
            api.urlInspection()
            .index()
            .inspect(
                body={"siteUrl": "sc-domain:example.com", "inspectionUrl": "https://example.com/"}
            )
        )
        assert req.uri.startswith("https://searchconsole.googleapis.com/v1/urlInspection")
    else:
        query = Query(startDate="2026-08-01", endDate="2026-08-31", dimensions=["query"])
        req = api.searchanalytics().query(siteUrl="sc-domain:example.com", body=query.body())
        assert json.loads(req.body)["type"] == "web"
        assert "sc-domain%3Aexample.com" in req.uri
        for resource in [
            api.sites().list(),
            api.sites().get(siteUrl="sc-domain:example.com"),
            api.sites().add(siteUrl="sc-domain:example.com"),
            api.sites().delete(siteUrl="sc-domain:example.com"),
            api.sitemaps().list(siteUrl="sc-domain:example.com"),
            api.sitemaps().get(siteUrl="sc-domain:example.com", feedpath="https://e/s.xml"),
            api.sitemaps().submit(siteUrl="sc-domain:example.com", feedpath="https://e/s.xml"),
            api.sitemaps().delete(siteUrl="sc-domain:example.com", feedpath="https://e/s.xml"),
        ]:
            assert resource.uri.startswith("https://www.googleapis.com/webmasters/v3/")
    assert req.method == "POST"


@pytest.mark.parametrize("error", [ServerNotFoundError("dns error"), AccessDeniedError()])
def test_transport_and_oauth_errors(monkeypatch, tmp_path, error):
    monkeypatch.setenv("GOOSEACON_CONFIG_DIR", str(tmp_path))
    save_config(Config())

    def fail(**kwargs):
        raise error

    monkeypatch.setattr("gooseacon.cli.service", fail)
    result = CliRunner().invoke(app, ["sites", "list"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Error:" in result.stderr
    assert "Traceback" not in result.stderr


def test_non_object_config(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOSEACON_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.json").write_text("[]")
    monkeypatch.setenv("GSC_SITE_URL", "sc-domain:example.com")
    result = CliRunner().invoke(app, ["config", "show"])
    assert result.exit_code == 1
    assert "JSON object" in result.stderr
