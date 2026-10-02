---
name: gooseacon-cli
description: Query and manage Google Search Console (GSC) using the gooseacon CLI. Use when the user asks about Google organic search clicks, impressions, CTR, rankings, top queries/pages, device/country performance, search appearance, submitted sitemaps, indexed URL status, Search Console properties, or GSC reports and exports. Includes authentication, filters, pagination, batch queries, and safe site/sitemap management. Use gafour-cli for GA4 sessions/conversions instead.
---

# Google Search Console CLI (gooseacon)

## Check authentication first

```bash
gooseacon auth status --check
```

Expect JSON containing `configured: true`, `method`, and `accessible_sites`. OAuth credentials refresh automatically. An existing OAuth file is not proof that it has GSC scopes; use the active method and API check.

- Proceed when the API check succeeds.
- On failure, inspect stderr and exit status; do not print or read credential files into the conversation.
- Ask before changing authentication or account settings. Read [references/auth.md](references/auth.md) for setup/recovery.
- Do not copy GA4 OAuth tokens and assume GSC access: the scopes differ.

## Discover the property

```bash
gooseacon sites list --format json
gooseacon sites get --site-url 'https://example.com/' --format json
```

Read the **object** response, not a bare array:

```json
{
  "siteEntry": [
    {"siteUrl":"https://example.com/","permissionLevel":"siteFullUser"},
    {"siteUrl":"sc-domain:example.com","permissionLevel":"siteOwner"}
  ]
}
```

Use the returned `siteUrl` verbatim. URL-prefix, subdirectory, and domain properties are different scopes; retain prefixes and trailing slashes. Do not substitute GA4 numeric property IDs. Ask which property to use if several are plausible.

Pass `--site-url` explicitly on agent calls so another session's defaults cannot select the wrong property. `--site` is an alias.

## Discover help and select output

```bash
gooseacon --help
gooseacon analytics --help
gooseacon analytics query --help
```

Use `--help` on any command before guessing flags. Apply flags at the command level, not before the group name.

- Pass `--format json` explicitly on read/report commands for machine parsing; a saved configuration can otherwise change the default to table/CSV.
- Use `--format csv --output /absolute/path/report.csv` for requested exports.
- Use `--format table` for human-readable output.
- Treat JSON as Google's raw response; analytics keys are in the order of the requested dimensions.
- Use `--output`/`-o` to write rather than print large results. Files are overwritten: choose a new task-specific path unless replacement was requested.
- Check exit codes before parsing. Errors go to stderr; failure normally produces no JSON. **Batch is the exception:** it emits partial results and exits 1 if a request fails.
- Do not claim an export exists without checking the written file.

## Search performance

Always specify an inclusive YYYY-MM-DD start/end range. Use Pacific reporting dates; GSC is not realtime. Confirm ambiguous date ranges and avoid treating recent incomplete data as final.

```bash
# Property totals – no dimensions
# Replace example property and dates with the requested scope/range.
gooseacon analytics query --site-url 'https://example.com/' \
  --start 2026-09-01 --end 2026-09-30 --format json

# Top search terms and pages
gooseacon analytics top-queries --site-url 'https://example.com/' \
  --start 2026-09-01 --end 2026-09-30 --row-limit 100 --format json

gooseacon analytics top-pages --site-url 'https://example.com/' \
  --start 2026-09-01 --end 2026-09-30 --country usa --device mobile --format json

# Daily trends
gooseacon analytics query --site-url 'https://example.com/' \
  --start 2026-09-01 --end 2026-09-30 --dimensions date --format json
```

| Command | Default grouping | Default rows |
| --- | --- | --- |
| `analytics query` | None (totals) | 1,000 |
| `analytics top-queries` | query | 100 |
| `analytics top-pages` | page | 100 |
| `analytics mobile` | date, mobile filter | 1,000 |
| `analytics desktop` | date, desktop filter | 1,000 |
| `analytics countries` | country | 100 |
| `analytics search-appearance` | searchAppearance | 100 |

All shortcuts accept the same report flags, including `--dimensions`, which overrides their grouping. Use `--country usa` / `gbr` (ISO **alpha-3**, not US/GB). Use `--device mobile`, `desktop`, or `tablet`.

Read [references/analytics.md](references/analytics.md) for every option, filters, pagination, response parsing, comparisons, and batch queries.

## Sitemaps

```bash
gooseacon sitemaps list --site-url 'https://example.com/' --format json
gooseacon sitemaps list --site-url 'https://example.com/' \
  --sitemap-index 'https://example.com/sitemap-index.xml' --format json
gooseacon sitemaps get 'https://example.com/sitemap.xml' \
  --site-url 'https://example.com/' --format json
```

Read `sitemap` in list responses. Retain `path`, errors, warnings, timestamps, and contents when relevant. Pass the **full sitemap URL** as the positional argument to `get`.

## Indexed URL inspection

```bash
gooseacon urls inspect 'https://example.com/article' \
  --site-url 'https://example.com/' --language-code en-US --format json
```

Read `inspectionResult.indexStatusResult` for coverage/index status, canonical URLs, crawl information, and verdict; read `richResultsResult` when present. Preserve `inspectionResultLink` as a useful link for the user. Handle optional/missing fields.

Do not describe this as a live crawl, request indexing, or infer a whole site's index coverage from one inspected URL. Keep inspections bounded to requested URLs to conserve quota. The CLI does not offer bulk indexing or full coverage reports.

## Mutations – require explicit user authorization

Do not run writes during audits or reporting. Obtain approval for the exact property/sitemap action before using `--yes`. Do not bypass a confirmation just to avoid an interactive prompt.

```bash
# Only after approval:
gooseacon sites add --site-url 'https://example.com/' --yes
gooseacon sites delete --site-url 'https://example.com/' --yes
gooseacon sitemaps submit 'https://example.com/sitemap.xml' \
  --site-url 'https://example.com/' --yes
gooseacon sitemaps delete 'https://example.com/sitemap.xml' \
  --site-url 'https://example.com/' --yes
```

Adding a site does not verify ownership. Deleting a site removes it from the authenticated account. Deleting a sitemap removes its GSC submission, not the website file. OAuth writes require the `webmasters` scope; service accounts still need appropriate property permissions. Verify the resulting state with read commands.

## Interpretation rules

- Distinguish **GSC clicks/impressions** from **GA4 sessions/users/conversions**. Do not label one as the other.
- Treat CTR as a fraction: `0.1` = 10%. Recompute aggregate CTR as total clicks / total impressions; never average row CTRs.
- Do not take a simple average of row positions; use a matching aggregate API query for overall position.
- Do not assume dimension row sums equal property totals: anonymized queries and aggregation rules affect them.
- Treat default top reports as top-N, not a complete dataset. Pagination cannot bypass Google's internal top-row limits or privacy filtering.
- Report the property, dates, search type, filters, dimensions, row count, and freshness/truncation caveats with findings.
- On 403, check access, API enablement, scopes, or quota. On 429, wait rather than loop; automatic transient retries already occur. On 404, check the exact property/path. Do not interpret API failures as zero traffic.
