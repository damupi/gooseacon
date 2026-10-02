"""Typer command surface. JSON is the default for scripts and agents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from gooseacon import __version__
from gooseacon.analytics import Query, flatten_rows, run_query
from gooseacon.auth import get_credentials, login_oauth, token_path
from gooseacon.client import execute, guarded, service, site_url
from gooseacon.config import Config, load_config, save_config
from gooseacon.output import Format, emit

app = typer.Typer(help="Google Search Console CLI.", no_args_is_help=True)
auth = typer.Typer(
    help="OAuth2, service account, token, or ADC authentication.", no_args_is_help=True
)
config = typer.Typer(help="Manage local settings.", no_args_is_help=True)
sites = typer.Typer(help="List and manage Search Console properties.", no_args_is_help=True)
sitemaps = typer.Typer(help="List and manage submitted sitemaps.", no_args_is_help=True)
analytics = typer.Typer(
    help="Search traffic reports and performance shortcuts.", no_args_is_help=True
)
urls = typer.Typer(help="Inspect Google's indexed version of a URL.", no_args_is_help=True)
for name, group in [
    ("auth", auth),
    ("config", config),
    ("sites", sites),
    ("sitemaps", sitemaps),
    ("analytics", analytics),
    ("urls", urls),
]:
    app.add_typer(group, name=name)

Site = Annotated[str | None, typer.Option("--site-url", "--site", help="Exact GSC property URL.")]
Output = Annotated[Path | None, typer.Option("--output", "-o", help="Write output to a file.")]
Fmt = Annotated[Format | None, typer.Option("--format", "-f", help="json, csv, or table.")]


def output_format(value: Format | None) -> Format:
    return value or Format(load_config().output_format)


def version(value: bool) -> None:
    if value:
        typer.echo(f"gooseacon {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version_flag: Annotated[
        bool, typer.Option("--version", "-V", callback=version, is_eager=True)
    ] = False,
) -> None:
    """Google Search Console CLI."""


@auth.command("login")
@guarded
def auth_login(
    method: str = typer.Option("oauth2", help="oauth2, service-account, token, or adc."),
    client_secret: Path | None = typer.Option(None, exists=True, dir_okay=False),
    key_file: Path | None = typer.Option(None, exists=True, dir_okay=False),
    write: bool = typer.Option(
        False, "--write", help="Request permission to modify GSC resources."
    ),
    port: int = typer.Option(0, min=0, max=65535),
    no_browser: bool = typer.Option(False, help="Print auth URL instead of opening the browser."),
) -> None:
    """Configure authentication. OAuth needs a Desktop app client-secret JSON."""
    # Validate before starting browser authentication or writing anything.
    candidate = Config(auth_method=method)
    if method == "oauth2":
        if not client_secret:
            raise ValueError("OAuth2 requires --client-secret FILE (Desktop app OAuth client).")
        login_oauth(client_secret, readonly=not write, port=port, open_browser=not no_browser)
    elif method == "service-account":
        if not key_file:
            raise ValueError("Service account authentication requires --key-file FILE.")
        candidate.key_file = str(key_file.resolve())
        get_credentials(candidate, write=write)
    else:
        get_credentials(candidate, write=write)
    stored = load_config(overrides=False)
    stored.auth_method = candidate.auth_method
    if candidate.key_file:
        stored.key_file = candidate.key_file
    save_config(stored)
    emit({"authenticated": True, "method": method}, Format.json)


@auth.command("status")
@guarded
def auth_status(
    check: bool = typer.Option(False, help="Verify access by listing GSC sites."),
) -> None:
    """Validate local credentials; use --check for an API round trip."""
    cfg = load_config()
    creds = get_credentials(cfg)
    result = {
        "configured": True,
        "method": cfg.auth_method,
        "oauth_credentials_stored": token_path().exists(),
        "service_account_email": getattr(creds, "service_account_email", None),
    }
    if check:
        result["accessible_sites"] = len(execute(service().sites().list()).get("siteEntry", []))
    emit(result, Format.json)


@auth.command("logout")
@guarded
def auth_logout(yes: bool = typer.Option(False, "--yes", "-y")) -> None:
    """Remove local OAuth credentials and saved key path, not Google grants or ADC."""
    if not yes:
        typer.confirm("Remove gooseacon's local authentication settings?", abort=True)
    token_path().unlink(missing_ok=True)
    cfg = load_config(overrides=False)
    cfg.auth_method = "adc"
    cfg.key_file = None
    save_config(cfg)
    emit(
        {"logged_out": True, "note": "ADC and environment credentials are unchanged."}, Format.json
    )


@config.command("show")
@guarded
def config_show() -> None:
    """Show effective settings (never tokens or client secrets)."""
    emit(load_config().model_dump(), Format.json)


@config.command("set")
@guarded
def config_set(key: str, value: str) -> None:
    """Set auth_method, key_file, default_site_url, or output_format."""
    if key not in Config.model_fields:
        raise ValueError(f"Unknown setting: {key}. Choose {', '.join(Config.model_fields)}.")
    if key == "default_site_url":
        site_url(value)
    cfg = load_config(overrides=False)
    setattr(cfg, key, value)
    save_config(cfg)
    emit({key: value}, Format.json)


@config.command("unset")
@guarded
def config_unset(key: str) -> None:
    if key not in Config.model_fields:
        raise ValueError(f"Unknown setting: {key}.")
    cfg = load_config(overrides=False)
    setattr(cfg, key, getattr(Config(), key))
    save_config(cfg)
    emit({key: getattr(cfg, key)}, Format.json)


@sites.command("list")
@guarded
def sites_list(fmt: Fmt = None, output: Output = None) -> None:
    data = execute(service().sites().list())
    emit(data, output_format(fmt), output, data.get("siteEntry", []))


@sites.command("get")
@guarded
def sites_get(site: Site = None, fmt: Fmt = None, output: Output = None) -> None:
    target = site_url(site)
    emit(execute(service().sites().get(siteUrl=target)), output_format(fmt), output)


def register_site_mutation(name: str) -> None:
    @sites.command(name)
    @guarded
    def mutation(site: Site = None, yes: bool = typer.Option(False, "--yes", "-y")) -> None:
        """Add/remove a property from your account. Add does not verify ownership."""
        target = site_url(site)
        if not yes:
            typer.confirm(f"{name.title()} property {target}?", abort=True)
        execute(getattr(service(write=True).sites(), name)(siteUrl=target))
        emit({"action": name, "siteUrl": target}, Format.json)


for action in ("add", "delete"):
    register_site_mutation(action)


@sitemaps.command("list")
@guarded
def sitemaps_list(
    site: Site = None,
    sitemap_index: str | None = typer.Option(None),
    fmt: Fmt = None,
    output: Output = None,
) -> None:
    target = site_url(site)
    params = {"sitemapIndex": sitemap_index} if sitemap_index else {}
    data = execute(service().sitemaps().list(siteUrl=target, **params))
    emit(data, output_format(fmt), output, data.get("sitemap", []))


@sitemaps.command("get")
@guarded
def sitemaps_get(feedpath: str, site: Site = None, fmt: Fmt = None, output: Output = None) -> None:
    """Get a sitemap by its full URL."""
    target = site_url(site)
    emit(
        execute(service().sitemaps().get(siteUrl=target, feedpath=feedpath)),
        output_format(fmt),
        output,
    )


def register_sitemap_mutation(name: str) -> None:
    @sitemaps.command(name)
    @guarded
    def mutation(
        feedpath: str, site: Site = None, yes: bool = typer.Option(False, "--yes", "-y")
    ) -> None:
        """Submit/remove a sitemap in GSC. Does not alter files on your website."""
        target = site_url(site)
        if not yes:
            typer.confirm(f"{name.title()} sitemap {feedpath} for {target}?", abort=True)
        execute(getattr(service(write=True).sitemaps(), name)(siteUrl=target, feedpath=feedpath))
        emit({"action": name, "siteUrl": target, "feedpath": feedpath}, Format.json)


for action in ("submit", "delete"):
    register_sitemap_mutation(action)


@urls.command("inspect")
@guarded
def urls_inspect(
    url: str,
    site: Site = None,
    language_code: str = typer.Option("en-US"),
    fmt: Fmt = None,
    output: Output = None,
) -> None:
    """Inspect indexed status, not a live test or indexing request."""
    target = site_url(site)
    if not url.startswith(("https://", "http://")):
        raise ValueError("Inspection URL must be a fully qualified http(s) URL.")
    data = execute(
        service(inspection=True)
        .urlInspection()
        .index()
        .inspect(
            body={
                "inspectionUrl": url,
                "siteUrl": target,
                "languageCode": language_code,
            }
        )
    )
    emit(data, output_format(fmt), output)


def register_report(
    name: str,
    preset_dimensions: str = "",
    preset_device: str | None = None,
    default_limit: int = 1000,
) -> None:
    @analytics.command(name)
    @guarded
    def report(
        start_date: str = typer.Option(
            ..., "--start-date", "--start", help="YYYY-MM-DD (Pacific)."
        ),
        end_date: str = typer.Option(..., "--end-date", "--end", help="YYYY-MM-DD (Pacific)."),
        site: Site = None,
        dimensions: str = typer.Option(
            preset_dimensions, help="Comma-separated grouping dimensions."
        ),
        filters: str | None = typer.Option(
            None, help="JSON filter groups, or @path/to/filters.json."
        ),
        device: str | None = typer.Option(preset_device, help="mobile, desktop, or tablet."),
        country: str | None = typer.Option(None, help="ISO 3166-1 alpha-3 code, e.g. usa, gbr."),
        search_type: str = typer.Option("web"),
        aggregation_type: str = typer.Option("auto"),
        data_state: str = typer.Option("final"),
        row_limit: int = typer.Option(default_limit, min=1, max=25000),
        start_row: int = typer.Option(0, min=0),
        all_rows: bool = typer.Option(False, help="Paginate returned API rows up to --max-rows."),
        max_rows: int = typer.Option(100000, min=1),
        fmt: Fmt = None,
        output: Output = None,
    ) -> None:
        """Query clicks, impressions, CTR, and average position."""
        target = site_url(site)
        groups = read_json(filters) if filters else []
        if not isinstance(groups, list):
            raise ValueError("--filters must be a JSON array of filter groups.")
        extra = []
        if device:
            if device.lower() not in {"mobile", "desktop", "tablet"}:
                raise ValueError("Device must be mobile, desktop, or tablet.")
            extra.append({"dimension": "device", "expression": device.lower()})
        if country:
            if len(country) != 3 or not country.isalpha():
                raise ValueError("Country must be an ISO alpha-3 code, e.g. usa or gbr.")
            extra.append({"dimension": "country", "expression": country.lower()})
        if extra:
            groups.append({"filters": extra})
        query = Query(
            start_date=start_date,
            end_date=end_date,
            dimensions=[d.strip() for d in dimensions.split(",") if d.strip()],
            dimension_filter_groups=groups,
            row_limit=row_limit,
            start_row=start_row,
            search_type=search_type,
            aggregation_type=aggregation_type,
            data_state=data_state,
        )
        data = run_query(service(), target, query, all_rows=all_rows, max_rows=max_rows)
        emit(data, output_format(fmt), output, flatten_rows(data, query.dimensions))

    report.__doc__ = {
        "query": "Flexible Search Analytics query with dimensions, filters, and pagination.",
        "top-queries": "Top search queries, ordered by clicks by Google.",
        "top-pages": "Top pages, ordered by clicks by Google.",
        "mobile": "Mobile search performance, grouped by date by default.",
        "desktop": "Desktop search performance, grouped by date by default.",
        "countries": "Search performance grouped by country.",
        "search-appearance": "Search performance grouped by rich-result/search appearance.",
    }[name]


for args in [
    ("query", "", None, 1000),
    ("top-queries", "query", None, 100),
    ("top-pages", "page", None, 100),
    ("mobile", "date", "mobile", 1000),
    ("desktop", "date", "desktop", 1000),
    ("countries", "country", None, 100),
    ("search-appearance", "searchAppearance", None, 100),
]:
    register_report(*args)


def read_json(value: str):
    return json.loads(Path(value[1:]).read_text() if value.startswith("@") else value)


@analytics.command("batch")
@guarded
def analytics_batch(
    requests_file: Path = typer.Argument(..., exists=True, dir_okay=False),
    site: Site = None,
    output: Output = None,
) -> None:
    """Run a JSON array of queries sequentially. Partial failures exit with code 1."""
    target = site_url(site)
    requests = json.loads(requests_file.read_text())
    if not isinstance(requests, list) or not requests:
        raise ValueError("Batch file must contain a nonempty JSON array of request objects.")
    # Validate the entire batch before sending any requests.
    queries = [Query.model_validate(request) for request in requests]
    api = service()
    results = []
    failed = False
    from googleapiclient.errors import HttpError

    for index, query in enumerate(queries):
        result = {"request_index": index, "request": query.body()}
        try:
            result["response"] = run_query(api, target, query)
        except HttpError as exc:
            failed = True
            result["error"] = {"status": exc.resp.status, "message": exc.reason}
        results.append(result)
    emit(
        {"site_url": target, "total_requests": len(queries), "results": results},
        Format.json,
        output,
    )
    if failed:
        raise typer.Exit(1)
