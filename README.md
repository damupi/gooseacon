# gooseacon

A Google Search Console CLI by [damupi](https://github.com/damupi), following the conventions of [gafour](https://github.com/damupi/gafour).

Query search performance, inspect indexed URLs, and manage sites and sitemaps from your terminal. JSON-first output for scripts and agents; CSV and table output for reporting.

## Install

Python 3.11+ required.

```sh
uv tool install git+https://github.com/damupi/gooseacon.git
# Or:
pipx install git+https://github.com/damupi/gooseacon.git

gooseacon --help
gooseacon --version
```

For development:

```sh
git clone https://github.com/damupi/gooseacon.git
cd gooseacon
uv sync --group dev
uv run gooseacon --help
uv run pytest
uv run ruff check .
```

## Authenticate

Enable the **Google Search Console API** in your Google Cloud project. Your user or service account must have access to the exact Search Console property.

### OAuth2 (recommended for your own Google account)

Create an OAuth consent screen and a **Desktop app** OAuth client in Google Cloud. Download its client-secret JSON. If the app is in testing, add your account as a test user.

```sh
gooseacon auth login --client-secret /path/to/client_secret.json
gooseacon auth status --check
```

This opens a browser and uses a local loopback callback. `--no-browser --port 8080` prints the URL instead; the callback still requires access to that machine's loopback port (use SSH port forwarding on a remote machine). This is not the deprecated out-of-band flow.

Read-only scope is the default. For site/sitemap writes, log in again with `--write`:

```sh
gooseacon auth login --client-secret /path/to/client_secret.json --write
```

### Service account

Add the service account email as a user on your GSC property, then:

```sh
gooseacon auth login --method service-account --key-file /path/to/key.json
```

### Access token

Tokens are supplied through the environment and never saved by gooseacon:

```sh
export GSC_ACCESS_TOKEN='your-short-lived-token'
gooseacon auth login --method token
```

### Application Default Credentials

ADC is the default when no login method is configured. Provision ADC with Search Console scopes, for example:

```sh
gcloud auth application-default login \
  --client-id-file=/path/to/client_secret.json \
  --scopes=https://www.googleapis.com/auth/webmasters.readonly
gooseacon auth login --method adc
```

Write operations need `https://www.googleapis.com/auth/webmasters` instead. Normal gcloud defaults do not necessarily include Search Console scopes.

Credentials stay under `~/.config/gooseacon/`; saved OAuth tokens and settings use owner-only permissions and atomic replacement. `auth status` never prints tokens. `auth logout` removes local OAuth credentials and key-file settings, but does **not** revoke Google grants, delete service account keys, or remove ADC/environment credentials. Testing-mode OAuth refresh tokens may expire after seven days.

## Quick start

```sh
gooseacon sites list
gooseacon config set default_site_url sc-domain:example.com

gooseacon analytics top-queries --start 2026-08-01 --end 2026-08-31
gooseacon analytics top-pages --start 2026-08-01 --end 2026-08-31 \
  --country usa --device mobile --format csv --output pages.csv

gooseacon analytics query --start 2026-08-01 --end 2026-08-31 \
  --dimensions date,query,page --all-rows --max-rows 100000

gooseacon urls inspect https://example.com/article
gooseacon sitemaps list
```

Pass `--site-url` (alias `--site`) to any property-scoped command to override the default. Use the exact GSC property identifier: `sc-domain:example.com` or a URL-prefix property such as `https://www.example.com/`. Trailing slashes and prefixes matter; the CLI does not rewrite property identifiers.

## Commands

| Command | Purpose |
| --- | --- |
| `sites list` / `sites get` | Accessible properties and permission levels |
| `sites add` / `sites delete` | Add/remove a property from the authenticated account |
| `analytics query` | Flexible Search Analytics request |
| `analytics top-queries` / `analytics top-pages` | Top queries/pages, default 100 rows |
| `analytics mobile` / `analytics desktop` | Device-specific performance, grouped by date |
| `analytics countries` | Group by country |
| `analytics search-appearance` | Group by search appearance |
| `analytics batch REQUESTS.json` | Sequential batch queries, JSON output |
| `sitemaps list` / `sitemaps get URL` | Sitemap status, contents, errors, warnings |
| `sitemaps submit URL` / `sitemaps delete URL` | Submit/remove a sitemap in GSC |
| `urls inspect URL` | Indexed status and rich-result inspection |
| `auth login` / `auth status` / `auth logout` | Authentication management |
| `config show` / `config set KEY VALUE` / `config unset KEY` | Local settings |

Use `gooseacon <group> <command> --help` for all options. Write operations and logout require confirmation; pass `--yes` only when you intend the change. Adding a property does not verify ownership. Removing a sitemap does not delete the file from your website. The CLI never automates site verification or requests indexing.

## Analytics options

All analytics reports accept:

- Required `--start-date` / `--end-date` (aliases `--start` / `--end`), inclusive YYYY-MM-DD dates in Search Console's Pacific time zone.
- `--dimensions`: comma-separated `query,page,date,country,device,searchAppearance,hour`. Omit for totals. Shortcut dimensions can be overridden.
- `--device`: mobile, desktop, tablet. `--country`: **ISO alpha-3**, e.g. `usa`, `gbr`, not `US`/`GB`.
- `--search-type`: web (default), image, video, news, discover, googleNews.
- `--aggregation-type`: auto (default), byPage, byProperty, byNewsShowcasePanel. Some combinations are rejected by Google. `byProperty` cannot group/filter by page or use discover/googleNews.
- `--data-state`: final (default), all, hourly_all. The hour dimension requires hourly_all; hourly data is only available for Google's recent hourly window.
- `--row-limit`: 1–25,000 per request, default 1,000 (100 for top/country/appearance shortcuts).
- `--start-row`: initial offset. `--all-rows`: paginate up to `--max-rows` (default 100,000).
- `--filters`: JSON array of dimension filter groups, or `@filename`.
- `--format`: json (default), csv, table. `--output`: save to a file instead of stdout.

### Filters

```sh
gooseacon analytics query --start 2026-08-01 --end 2026-08-31 \
  --dimensions query,page \
  --filters '[{"filters":[{"dimension":"query","operator":"includingRegex","expression":"buy|price"}]}]'
```

Supported operators: equals, notEquals, contains, notContains, includingRegex, excludingRegex. Filter groups use AND. Convenience country/device filters are added as another AND group.

### Batch queries

`requests.json`:

```json
[
  {"startDate":"2026-08-01","endDate":"2026-08-31","dimensions":["query"],"rowLimit":100},
  {"start_date":"2026-08-01","end_date":"2026-08-31","dimensions":["page"],"row_limit":100}
]
```

```sh
gooseacon analytics batch requests.json --output batch-results.json
```

Both API camelCase and Python snake_case fields are accepted; search type accepts `type`, `search_type`, or legacy `searchType`. The entire batch is validated before API calls. API failures are recorded per request; remaining requests continue. Any failed request makes the command exit with code 1. Batch is sequential, not Google's HTTP batch API, and does not auto-paginate each request.

## Output and API limits

JSON preserves Google's response, including freshness metadata and nested inspection/sitemap fields. CSV/table analytics flatten dimension keys into named columns; nested values in other commands are JSON strings. CSV prefixes formula-like text cells with an apostrophe to prevent spreadsheet formula execution; use JSON to preserve exact text. Errors go to stderr with nonzero exit codes. Output files are overwritten if they already exist. API requests retry transient errors up to three times.

Pagination adds a `pagination` object with offsets, rows returned, and `limitReached`. When true, the safety cap was reached and more data **may** exist; this is not proof of truncation. Search Console returns top rows, not a guaranteed complete raw export. Anonymized queries, internal row limits, quotas, retention, and reporting delays still apply. CTR remains Google's fractional value (0.1 = 10%). Aggregated totals may differ from sums of dimension rows. URL inspection reports Google's indexed version, not a live crawl.

## Settings

```sh
gooseacon config set output_format table
gooseacon config set default_site_url https://example.com/
gooseacon config show
gooseacon config unset default_site_url
```

Environment overrides:

| Variable | Purpose |
| --- | --- |
| `GSC_AUTH_METHOD` | oauth2, service-account, token, adc |
| `GSC_KEY_FILE` | Service account JSON path |
| `GOOGLE_APPLICATION_CREDENTIALS` | Standard ADC; also fallback key path in service-account mode |
| `GSC_ACCESS_TOKEN` | Token-mode bearer token |
| `GSC_SITE_URL` | Default property identifier |
| `GSC_OUTPUT_FORMAT` | json, csv, table |
| `GOOSEACON_CONFIG_DIR` | Override config/token directory |

Environment overrides are not persisted by `config set` or token refresh.

## Implementation

Python + Typer + Pydantic + Google's API client. Sites, sitemaps, and Search Analytics use `webmasters/v3`; URL Inspection uses `searchconsole/v1`. Inspired by the GSC tools in `mcp-server-google`, with validation, secure local storage, metadata-preserving output, and CLI-friendly pagination.

## License

MIT.
