# Website Health Agent

This repo contains a free Website Health Agent for Shory that runs on GitHub Actions every 2 hours and can also be started manually. Each run publishes a partner-facing status dashboard to GitHub Pages.

## What it checks

- HTTP status
- Response time
- Page title
- H1
- Configured CTA text or expected text
- GTM script presence
- GA4 script presence

If any check fails, the workflow sends a Slack webhook alert with the URL, failure reason, HTTP status, response time, and UTC/UAE timestamps. When checks pass, nothing is sent to Slack.

## Files

- `monitoring/website_health.py`: the monitor
- `monitoring/website_health_config.toml`: the partner URL config
- `.github/workflows/website-health-agent.yml`: the scheduled GitHub Actions job
- `site/index.html`: the shareable partner dashboard
- `site/status.json`: the latest published check result

## Setup

1. Add your partner URLs to `monitoring/website_health_config.toml`.
1. In GitHub, add a repository secret named `SLACK_WEBHOOK_URL`.
1. Point the secret at your Slack incoming webhook.
1. In the repository settings, enable GitHub Pages with `GitHub Actions` as the source.
1. Run the workflow manually once to confirm the checks, alerting, and dashboard.

The dashboard URL will be:

`https://pyadav-debug.github.io/shory-websitechecker/`

The `Refresh checks` button reloads the latest server-side result immediately. A new server-side check is also available by selecting `Run workflow` in the GitHub Actions tab; the scheduled job runs every 2 hours automatically.

## Adding more URLs

To add another partner, copy one `[[urls]]` block in `monitoring/website_health_config.toml` and update:

- `name`
- `url`
- `expected_text`
- `cta_text`
- `allow_status_codes` if the page should accept more than `200`

## Notes

- The workflow is read-only and does not depend on any paid monitoring service.
- Check history is preserved in the GitHub Actions run logs.
- The script uses standard-library Python only, so there are no package installs.

