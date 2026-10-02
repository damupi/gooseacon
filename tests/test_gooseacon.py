import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import httplib2
import pytest
from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError
from pydantic import ValidationError
from typer.testing import CliRunner

from gooseacon import auth, client, config
from gooseacon.analytics import Query, flatten_rows, run_query
from gooseacon.cli import app
from gooseacon.output import Format, render

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOSEACON_CONFIG_DIR", str(tmp_path / "config"))
    for key in (
        "GSC_AUTH_METHOD",
        "GSC_KEY_FILE",
        "GSC_SITE_URL",
        "GSC_OUTPUT_FORMAT",
        "GSC_ACCESS_TOKEN",
        "GOOGLE_APPLICATION_CREDENTIALS",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def api(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr("gooseacon.cli.service", lambda **kwargs: mock)
    config.save_config(config.Config(default_site_url="sc-domain:example.com"))
    return mock


def request(**kwargs):
    return Query(start_date="2026-08-01", end_date="2026-08-31", **kwargs)


def test_version_and_help():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "gooseacon 0.1.0" in result.stdout
    for group in ["analytics", "auth", "config", "sites", "sitemaps", "urls"]:
        assert runner.invoke(app, [group, "--help"]).exit_code == 0


@pytest.mark.parametrize(
    "command",
    ["query", "top-queries", "top-pages", "mobile", "desktop", "countries", "search-appearance"],
)
def test_report_help(command):
    assert runner.invoke(app, ["analytics", command, "--help"]).exit_code == 0


def test_config_env_not_persisted(monkeypatch):
    config.save_config(config.Config(default_site_url="sc-domain:saved.com"))
    monkeypatch.setenv("GSC_SITE_URL", "sc-domain:env.com")
    assert config.load_config().default_site_url == "sc-domain:env.com"
    assert runner.invoke(app, ["config", "set", "output_format", "table"]).exit_code == 0
    assert config.load_config(overrides=False).default_site_url == "sc-domain:saved.com"
    assert (config.config_dir() / "config.json").stat().st_mode & 0o777 == 0o600
    assert runner.invoke(app, ["config", "unset", "output_format"]).exit_code == 0
    assert config.load_config().output_format == "json"


@pytest.mark.parametrize(
    "args",
    [
        ["config", "set", "unknown", "x"],
        ["config", "set", "output_format", "xml"],
        ["config", "unset", "unknown"],
        ["config", "set", "default_site_url", "bad"],
    ],
)
def test_config_validation(args):
    result = runner.invoke(app, args)
    assert result.exit_code == 1
    assert "Error:" in result.stderr


def test_config_show_and_corrupt_file():
    assert runner.invoke(app, ["config", "show"]).exit_code == 0
    config.write_private(config.config_dir() / "config.json", "not json")
    assert runner.invoke(app, ["config", "show"]).exit_code == 1


@pytest.mark.parametrize(
    "site", ["sc-domain:example.com", "https://example.com/", "http://example.com/path/"]
)
def test_valid_site(site):
    assert client.site_url(site) == site


def test_missing_site():
    with pytest.raises(ValueError):
        client.site_url(None)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"row_limit": 0},
        {"row_limit": 25001},
        {"start_row": -1},
        {"dimensions": ["unknown"]},
        {"dimensions": ["query", "query"]},
        {"dimensions": ["hour"]},
        {"dimensions": ["page"], "aggregation_type": "byProperty"},
        {"search_type": "discover", "aggregation_type": "byProperty"},
        {"search_type": "bogus"},
        {"dimension_filter_groups": [{"filters": []}]},
    ],
)
def test_invalid_query(kwargs):
    with pytest.raises(ValidationError):
        request(**kwargs)


def test_dates_and_aliases():
    with pytest.raises(ValidationError):
        Query(startDate="2026-09-01", endDate="2026-08-01")
    with pytest.raises(ValidationError):
        Query(startDate="2026-02-30", endDate="2026-08-01")
    query = Query(startDate="2026-08-01", endDate="2026-08-31", searchType="image")
    assert query.body()["type"] == "image"
    assert "searchType" not in query.body()
    assert request(dimensions=["hour"], data_state="hourly_all").body()["dataState"] == "hourly_all"
    with pytest.raises(ValidationError):
        request(
            aggregation_type="byProperty",
            dimension_filter_groups=[{"filters": [{"dimension": "page", "expression": "/foo"}]}],
        )


@pytest.mark.parametrize(
    "command,dimensions,device",
    [
        ("query", [], None),
        ("top-queries", ["query"], None),
        ("top-pages", ["page"], None),
        ("mobile", ["date"], "mobile"),
        ("desktop", ["date"], "desktop"),
        ("countries", ["country"], None),
        ("search-appearance", ["searchAppearance"], None),
    ],
)
def test_reports(api, command, dimensions, device):
    api.searchanalytics().query().execute.return_value = {"rows": [], "metadata": {"fresh": True}}
    result = runner.invoke(
        app, ["analytics", command, "--start", "2026-08-01", "--end", "2026-08-31"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["metadata"] == {"fresh": True}
    body = api.searchanalytics().query.call_args.kwargs["body"]
    assert body["dimensions"] == dimensions
    if device:
        assert body["dimensionFilterGroups"][0]["filters"][0]["expression"] == device


def test_report_filters_csv(api, tmp_path):
    api.searchanalytics().query().execute.return_value = {
        "rows": [{"keys": ["term"], "clicks": 10, "ctr": 0.5}]
    }
    path = tmp_path / "out.csv"
    result = runner.invoke(
        app,
        [
            "analytics",
            "top-queries",
            "--start",
            "2026-08-01",
            "--end",
            "2026-08-31",
            "--country",
            "USA",
            "--device",
            "mobile",
            "--filters",
            '[{"filters":[{"dimension":"query","expression":"term"}]}]',
            "-f",
            "csv",
            "-o",
            str(path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert path.read_text() == "query,clicks,ctr\nterm,10,0.5\n"
    assert result.stdout == ""
    groups = api.searchanalytics().query.call_args.kwargs["body"]["dimensionFilterGroups"]
    assert groups[1]["filters"][1]["expression"] == "usa"


@pytest.mark.parametrize(
    "option,value",
    [
        ("--country", "US"),
        ("--device", "bot"),
        ("--filters", "{}"),
        ("--filters", "bad"),
        ("--dimensions", "bad"),
    ],
)
def test_invalid_report_no_api(api, option, value):
    result = runner.invoke(
        app, ["analytics", "query", "--start", "2026-08-01", "--end", "2026-08-31", option, value]
    )
    assert result.exit_code == 1
    api.searchanalytics.assert_not_called()


def test_pagination():
    api = MagicMock()
    api.searchanalytics().query().execute.side_effect = [
        {"rows": [{"clicks": 1}, {"clicks": 2}]},
        {"rows": [{"clicks": 3}], "metadata": {"first_incomplete_date": "x"}},
    ]
    result = run_query(
        api, "sc-domain:example.com", request(row_limit=2, start_row=3), all_rows=True
    )
    assert len(result["rows"]) == 3
    assert result["pagination"] == {
        "startRow": 3,
        "nextStartRow": 6,
        "rowsReturned": 3,
        "limitReached": False,
    }
    assert result["metadata"]["first_incomplete_date"] == "x"
    assert api.searchanalytics().query.call_args.kwargs["body"]["startRow"] == 5


def test_pagination_cap():
    api = MagicMock()
    api.searchanalytics().query().execute.return_value = {"rows": [{"clicks": 1}]}
    result = run_query(api, "site", request(), all_rows=True, max_rows=1)
    assert result["pagination"]["limitReached"] is True
    assert api.searchanalytics().query.call_args.kwargs["body"]["rowLimit"] == 1
    with pytest.raises(ValueError):
        run_query(api, "site", request(), all_rows=True, max_rows=0)


def test_sites_and_sitemaps(api):
    api.sites().list().execute.return_value = {"siteEntry": [{"siteUrl": "sc-domain:example.com"}]}
    assert "siteUrl" in runner.invoke(app, ["sites", "list", "-f", "csv"]).stdout
    api.sites().get().execute.return_value = {"permissionLevel": "siteOwner"}
    assert runner.invoke(app, ["sites", "get"]).exit_code == 0
    api.sitemaps().list().execute.return_value = {"sitemap": [{"path": "url", "errors": 0}]}
    assert runner.invoke(app, ["sitemaps", "list", "--sitemap-index", "index"]).exit_code == 0
    assert api.sitemaps().list.call_args.kwargs["sitemapIndex"] == "index"
    api.sitemaps().get().execute.return_value = {"path": "url", "contents": []}
    assert runner.invoke(app, ["sitemaps", "get", "https://example.com/sitemap.xml"]).exit_code == 0


@pytest.mark.parametrize(
    "group,action,extra",
    [
        ("sites", "add", []),
        ("sites", "delete", []),
        ("sitemaps", "submit", ["https://e.com/s.xml"]),
        ("sitemaps", "delete", ["https://e.com/s.xml"]),
    ],
)
def test_mutation_confirmation(api, group, action, extra):
    args = [group, action, *extra]
    result = runner.invoke(app, args, input="n\n")
    assert result.exit_code != 0
    getattr(api, group).assert_not_called()
    getattr(api, group)().execute.return_value = {}
    result = runner.invoke(app, [*args, "--yes"])
    assert result.exit_code == 0, result.output
    getattr(getattr(api, group)(), action).assert_called_once()


def test_inspection(api, monkeypatch):
    services = []
    monkeypatch.setattr("gooseacon.cli.service", lambda **kw: services.append(kw) or api)
    api.urlInspection().index().inspect().execute.return_value = {
        "inspectionResult": {"indexStatusResult": {"crawledAs": "MOBILE"}}
    }
    result = runner.invoke(app, ["urls", "inspect", "https://example.com/article"])
    assert result.exit_code == 0
    assert "crawledAs" in result.stdout
    assert services == [{"inspection": True}]
    assert runner.invoke(app, ["urls", "inspect", "bad"]).exit_code == 1


def http_error(status=403):
    return HttpError(
        httplib2.Response({"status": str(status)}), b'{"error":{"message":"Access denied"}}'
    )


def test_api_error(api):
    api.sites().list().execute.side_effect = http_error()
    result = runner.invoke(app, ["sites", "list"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "403" in result.stderr
    assert "Traceback" not in result.stderr


def test_batch_partial_failure(api, tmp_path):
    path = tmp_path / "requests.json"
    path.write_text(json.dumps([request().body(), request(dimensions=["page"]).body()]))
    api.searchanalytics().query().execute.side_effect = [http_error(), {"rows": []}]
    result = runner.invoke(app, ["analytics", "batch", str(path)])
    assert result.exit_code == 1
    data = json.loads(result.stdout)
    assert data["results"][0]["error"]["status"] == 403
    assert data["results"][1]["response"] == {"rows": []}


def test_batch_validation(api, tmp_path):
    path = tmp_path / "requests.json"
    for data in [{}, [], [request().body(), {"bad": True}]]:
        path.write_text(json.dumps(data))
        result = runner.invoke(app, ["analytics", "batch", str(path)])
        assert result.exit_code == 1
        api.searchanalytics.assert_not_called()


def test_batch_success(api, tmp_path):
    path = tmp_path / "requests.json"
    path.write_text(json.dumps([request().body()]))
    api.searchanalytics().query().execute.return_value = {}
    assert runner.invoke(app, ["analytics", "batch", str(path)]).exit_code == 0


def test_render():
    assert render({}, Format.json) == "{}\n"
    assert render([], Format.csv) == ""
    assert "no results" in render([], Format.table)
    assert "nested" in render({"nested": [1, 2], "none": None}, Format.csv)
    assert "clicks" in render([{"clicks": 1}], Format.table)
    assert flatten_rows({"rows": [{"keys": ["term"], "clicks": 1}]}, ["query"]) == [
        {"query": "term", "clicks": 1}
    ]


def test_token_auth(monkeypatch):
    cfg = config.Config(auth_method="token")
    with pytest.raises(ValueError):
        auth.get_credentials(cfg)
    monkeypatch.setenv("GSC_ACCESS_TOKEN", "secret")
    assert auth.get_credentials(cfg).token == "secret"
    result = runner.invoke(app, ["auth", "login", "--method", "token"])
    assert result.exit_code == 0
    assert "secret" not in (config.config_dir() / "config.json").read_text()
    assert "secret" not in runner.invoke(app, ["auth", "status"]).stdout


def test_service_account_auth(monkeypatch, tmp_path):
    cfg = config.Config(auth_method="service-account")
    with pytest.raises(ValueError):
        auth.get_credentials(cfg)
    mocked = MagicMock()
    monkeypatch.setattr(auth.service_account.Credentials, "from_service_account_file", mocked)
    cfg.key_file = str(tmp_path / "key.json")
    auth.get_credentials(cfg, write=True)
    assert mocked.call_args.kwargs["scopes"] == [auth.WRITE_SCOPE]


def test_oauth_refresh_and_write_scope(monkeypatch):
    cfg = config.Config(auth_method="oauth2")
    with pytest.raises(ValueError):
        auth.get_credentials(cfg)
    creds = Credentials(
        token="old",
        refresh_token="refresh",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="id",
        client_secret="secret",
        scopes=[auth.READ_SCOPE],
        expiry=datetime.now() - timedelta(hours=1),
    )
    config.write_private(auth.token_path(), creds.to_json())
    with pytest.raises(ValueError, match="Write access"):
        auth.get_credentials(cfg, write=True)

    def refresh(self, request):
        self.token = "new"
        self.expiry = datetime.now() + timedelta(hours=1)

    monkeypatch.setattr(Credentials, "refresh", refresh)
    assert auth.get_credentials(cfg).token == "new"
    assert json.loads(auth.token_path().read_text())["token"] == "new"
    assert auth.token_path().stat().st_mode & 0o777 == 0o600


def test_oauth_login_logout(monkeypatch, tmp_path):
    flow = MagicMock()
    flow.run_local_server().to_json.return_value = '{"token":"secret"}'
    monkeypatch.setattr(auth.InstalledAppFlow, "from_client_secrets_file", lambda *a, **kw: flow)
    client_file = tmp_path / "client.json"
    client_file.write_text("{}")
    result = runner.invoke(app, ["auth", "login", "--client-secret", str(client_file), "--write"])
    assert result.exit_code == 0
    assert auth.token_path().exists()
    assert runner.invoke(app, ["auth", "logout"], input="n\n").exit_code != 0
    assert auth.token_path().exists()
    assert runner.invoke(app, ["auth", "logout", "--yes"]).exit_code == 0
    assert not auth.token_path().exists()


@pytest.mark.parametrize(
    "args",
    [
        ["auth", "login"],
        ["auth", "login", "--method", "bad"],
        ["auth", "login", "--method", "service-account"],
    ],
)
def test_login_validation(args):
    assert runner.invoke(app, args).exit_code == 1


def test_build_service(monkeypatch):
    monkeypatch.setattr(client, "get_credentials", lambda *a, **kw: "creds")
    build = MagicMock()
    monkeypatch.setattr(client, "build", build)
    client.service()
    assert build.call_args.args == ("webmasters", "v3")
    client.service(inspection=True)
    assert build.call_args.args == ("searchconsole", "v1")


def test_adc(monkeypatch):
    mock = MagicMock(return_value=("credentials", "project"))
    monkeypatch.setattr(auth.google.auth, "default", mock)
    assert auth.get_credentials(config.Config()) == "credentials"
    assert mock.call_args.kwargs["scopes"] == [auth.READ_SCOPE]
