# Authentication and settings

Run `gooseacon auth status --check` first. Do not expose secrets, open credential JSON into model context, or change accounts/scopes without authorization.

## Existing local setup

Use `gooseacon config show` to inspect effective nonsensitive settings. Credentials normally live in `~/.config/gooseacon/`. A service-account setup may use `~/.config/gooseacon/key.json`; confirm the configured method rather than assuming.

Use existing working authentication. A copied GA4 service-account key can authenticate to GSC if its email has property access; copied GA4 OAuth credentials generally need a new GSC consent grant.

## Configure auth only when requested

```bash
# OAuth2: Desktop app OAuth client, read-only by default
gooseacon auth login --client-secret /path/to/client_secret.json

# OAuth2: explicit write consent
gooseacon auth login --client-secret /path/to/client_secret.json --write

# Service account: must be added to the GSC property
gooseacon auth login --method service-account --key-file /path/to/key.json

# Access token: read from GSC_ACCESS_TOKEN, never persisted by CLI
gooseacon auth login --method token

# ADC: credentials must have GSC scopes
gooseacon auth login --method adc
```

OAuth opens a browser and uses a local callback. Ask the user to complete consent if needed; do not pretend authentication succeeded. `--no-browser --port 8080` prints the URL but still uses a loopback callback, not an out-of-band flow. Remote machines need port forwarding.

Enable the Google Search Console API in the Google Cloud project. Read-only scope is `https://www.googleapis.com/auth/webmasters.readonly`; writes need `https://www.googleapis.com/auth/webmasters`. Scope alone does not grant property permissions.

OAuth tokens refresh automatically. If refreshing fails, reauthenticate only with approval. Treat `auth status` without `--check` as a local configuration check, not proof of live API access.

## Settings

```bash
gooseacon config show
gooseacon config set default_site_url 'https://example.com/'
gooseacon config set output_format json
gooseacon config unset default_site_url
```

Prefer per-command property/output flags during agent work instead of changing shared defaults.

| Environment variable | Purpose |
| --- | --- |
| `GSC_AUTH_METHOD` | oauth2, service-account, token, adc |
| `GSC_KEY_FILE` | Service-account key path |
| `GOOGLE_APPLICATION_CREDENTIALS` | Standard ADC; key fallback in service-account mode |
| `GSC_ACCESS_TOKEN` | Short-lived access token for token mode |
| `GSC_SITE_URL` | Default exact property URL |
| `GSC_OUTPUT_FORMAT` | json, csv, table |
| `GOOSEACON_CONFIG_DIR` | Override config/token directory |

Environment values override saved configuration; changing disk settings will not override an active environment variable. Do not echo token variables into output.

`gooseacon auth logout` removes local OAuth credentials and saved key path, not Google grants, service-account key files, ADC, or environment credentials. It requires confirmation; use `--yes` only after approval.

If the executable is missing, state that access is unavailable. With installation approval, use `uv tool install git+https://github.com/damupi/gooseacon.git` or `pipx install git+https://github.com/damupi/gooseacon.git`. Do not silently switch to another GSC client or data source.
