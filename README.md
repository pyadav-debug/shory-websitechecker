# Shory Partners Status Checker

A free stakeholder dashboard that shows whether Shory partner and product pages are available.

## How it works

- GitHub Actions checks every configured page every 2 hours.
- A push to the main branch also runs a fresh check.
- The latest results are published automatically to GitHub Pages.
- The public dashboard shows only the partner, full page URL, and Available or Not available.
- Check history is kept in GitHub Actions logs.
- Slack alerts are sent only when a page is unavailable and the webhook secret is configured.

Dashboard: https://pyadav-debug.github.io/shory-websitechecker/

## Add another page

Add another [[urls]] block to monitoring/website_health_config.toml with:

- name
- url
- allow_status_codes, normally [200]

The next GitHub Actions run will check it and update the dashboard automatically.

## Slack setup

Add a GitHub repository secret named SLACK_WEBHOOK_URL containing the Slack incoming webhook URL. Leave it unset if Slack alerts are not needed.

## Jina setup

Both checkers fall back to a read-only proxy (r.jina.ai) when they can't reach a page directly. Unauthenticated proxy requests can occasionally get a false "not available" from the target site's bot protection even when the page is genuinely up. Adding a Jina Reader API key avoids this.

- Get a key from jina.ai.
- GitHub Actions: add a repository secret named JINA_API_KEY (already wired into the workflow alongside SLACK_WEBHOOK_URL).
- Vercel: add a project environment variable named JINA_API_KEY (Project Settings -> Environment Variables).

This is optional - if unset, both checkers fall back to today's unauthenticated proxy requests with no errors.

## Manual check

Open the Website Health Agent workflow in the repository Actions tab and select Run workflow. The Refresh status button on the public dashboard reloads the latest completed check.
