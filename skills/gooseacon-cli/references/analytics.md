# Search Analytics reference

## Contents

- Options
- Filters
- Pagination
- Response parsing
- Batch queries
- Period comparisons

## Options

Apply these to `analytics query` or any performance shortcut:

| Flag | Default / accepted values |
| --- | --- |
| `--site-url`, `--site` | Exact property from `sites list`; otherwise config/environment |
| `--start-date`, `--start` | Required inclusive YYYY-MM-DD |
| `--end-date`, `--end` | Required inclusive YYYY-MM-DD |
| `--dimensions` | Comma-separated country, device, page, query, searchAppearance, date, hour |
| `--device` | mobile, desktop, tablet |
| `--country` | ISO alpha-3 code, e.g. usa, gbr |
| `--search-type` | web (default), image, video, news, discover, googleNews |
| `--aggregation-type` | auto (default), byPage, byProperty, byNewsShowcasePanel |
| `--data-state` | final (default), all, hourly_all |
| `--row-limit` | 1–25,000 per request; defaults depend on command |
| `--start-row` | 0; nonnegative initial offset |
| `--all-rows` | Disabled; paginate when present |
| `--max-rows` | 100,000 safety cap in pagination mode |
| `--filters` | JSON array, or @path/to/file.json |
| `--format`, `-f` | json, csv, table; set json explicitly for agents |
| `--output`, `-o` | File path instead of stdout; overwrites existing file |

Do not pass GA4-style relative dates such as `30daysAgo`. Compute explicit dates for the user's requested range. Use Pacific dates; note incomplete dates from response metadata when requesting `all`/`hourly_all`.

Use `hour` only with `--data-state hourly_all` and a recent range supported by Google's hourly reporting window. Do not assume hourly data exists for historical months.

Do not combine `byProperty` with page grouping/filtering, discover, or googleNews. Google can reject other incompatible combinations too; simplify the request rather than treating rejection as no data.

## Filters

Use a JSON array of AND groups:

```bash
gooseacon analytics query --site-url 'https://example.com/' \
  --start 2026-09-01 --end 2026-09-30 --dimensions query,page --format json \
  --filters '[{"filters":[{"dimension":"query","operator":"includingRegex","expression":"buy|price"},{"dimension":"page","operator":"contains","expression":"/guides/"}]}]'
```

For complex filters, write a task-specific JSON file and use `--filters @/absolute/path/filters.json`.

- Filter dimensions: query, page, country, device, searchAppearance. **Do not filter by date/hour**; dates belong in the date range.
- Operators: equals (default), notEquals, contains, notContains, includingRegex, excludingRegex.
- `groupType` is optional and only supports `and`. Multiple groups are also ANDed.
- Convenience `--country`/`--device` filters add an AND group. Avoid accidental conflicts with explicit filters.
- Use Google's RE2-compatible regex syntax. Preserve the user's intended matching/case semantics.

## Pagination

```bash
gooseacon analytics query --site-url 'https://example.com/' \
  --start 2026-09-01 --end 2026-09-30 --dimensions query,page \
  --row-limit 25000 --all-rows --max-rows 100000 \
  --format json --output /tmp/gsc-query-pages.json
```

Paginated JSON adds:

```json
{
  "pagination": {
    "startRow": 0,
    "nextStartRow": 100000,
    "rowsReturned": 100000,
    "limitReached": true
  }
}
```

If `limitReached` is true, the local cap was reached; more rows **may** exist. To resume, use the same query with `--start-row` equal to `nextStartRow`. Only expand the cap when needed; save large outputs to files.

If `limitReached` is false, the CLI exhausted the rows returned for that query, not Google's underlying data. Never label the result a complete raw export. Privacy filtering and internal top-row limits remain. CSV/table omit pagination metadata; use JSON when you need to verify pagination or freshness.

## Response parsing

Example for `--dimensions query,page`:

```json
{
  "rows": [
    {
      "keys": ["example query", "https://example.com/article"],
      "clicks": 12,
      "impressions": 120,
      "ctr": 0.1,
      "position": 4.2
    }
  ],
  "responseAggregationType": "byPage"
}
```

Map `keys[0]` to query and `keys[1]` to page. Do not expect named dimension objects in raw JSON. Treat an absent `rows` field as an empty result only after a successful exit. For totals, omit dimensions; rows may have no `keys`.

CSV/table output flatten dimension keys into named columns. CSV prefixes formula-like text with an apostrophe for spreadsheet safety; numeric metrics are unchanged. Use JSON when exact query text matters.

Use a totals query to compare overall clicks/impressions/position, not a sum or simple average of top-N rows. Google normally orders non-date reports by clicks; do not claim they're ordered by impressions/position. Sort returned rows locally for other rankings and disclose the fetched scope.

## Batch queries

Prefer one batch command for multiple independent queries on the same property, including period comparisons. This is a CLI convenience, **not a single HTTP round trip**: queries execute sequentially and consume individual API quota.

Write a JSON array to a task-specific file:

```json
[
  {"startDate":"2026-09-01","endDate":"2026-09-30","dimensions":[],"type":"web"},
  {"startDate":"2026-08-02","endDate":"2026-08-31","dimensions":[],"type":"web"},
  {"startDate":"2026-09-01","endDate":"2026-09-30","dimensions":["page"],"rowLimit":1000}
]
```

```bash
gooseacon analytics batch /tmp/gsc-requests.json \
  --site-url 'https://example.com/' --output /tmp/gsc-batch-results.json
```

Use positional `REQUESTS_FILE`, **not** `--requests-file`. Batch always emits JSON; do not pass `--format`. Both API camelCase and Python snake_case request fields are accepted, including `type` / `search_type` / legacy `searchType`.

Read `results[]` by `request_index` and `request`:

```json
{
  "site_url":"https://example.com/",
  "total_requests":2,
  "results":[
    {"request_index":0,"request":{},"response":{"rows":[]}},
    {"request_index":1,"request":{},"error":{"status":403,"message":"Access denied"}}
  ]
}
```

The example abbreviates request bodies. Validation runs before any API calls. API failures are recorded and later requests continue; any failed request causes exit 1. Inspect saved JSON even when exit is 1. Never convert failed requests to zeros. Retry only the failed request after resolving its cause.

Batch does not support auto-pagination or CLI convenience filters. Set `dimensionFilterGroups`, `rowLimit`, and `startRow` in each request. Use separate paginated `analytics query` calls when large extracts are required.

## Period comparisons

Keep property, search type, filters, dimensions, and aggregation consistent. Compare equal-duration periods or disclose unequal lengths and use per-day rates where appropriate. Join entity rows by dimension keys, not array position; missing entities are absent from the returned scope, not automatically known zeroes.

Calculate change as `(current - previous) / previous * 100`. When previous is zero, mark percentage change undefined/new rather than divide by zero. Report CTR changes in percentage points; a change from 10% to 12% is +2 pp (+20% relative). Avoid causal claims about ranking changes or algorithm updates without independent evidence.
