#!/usr/bin/env python3
"""Website health checks for partner landing pages.

This script reads a TOML config, checks each configured URL, prints a detailed
log for GitHub Actions, and sends a Slack webhook alert only when one or more
checks fail.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
    import tomli as tomllib  # type: ignore


UAE_TZ = timezone(timedelta(hours=4))
DEFAULT_TIMEOUT_SECONDS = 20


@dataclass
class CheckTarget:
    name: str
    url: str
    expected_text: str = ""
    cta_text: str = ""
    allow_status_codes: list[int] = field(default_factory=lambda: [200])


@dataclass
class CheckResult:
    target: CheckTarget
    ok: bool
    status_code: int | None
    final_url: str
    response_time_ms: int | None
    title: str
    h1: str
    issues: list[str]
    has_gtm: bool
    has_ga4: bool


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title_parts: list[str] = []
        self.h1_parts: list[str] = []
        self._capture_title = False
        self._capture_h1 = False
        self._capture_interactive = False
        self._current_interactive_tag: str | None = None
        self._interactive_text_parts: list[str] = []
        self.interactive_texts: list[str] = []
        self.raw_text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._capture_title = True
        elif tag == "h1":
            self._capture_h1 = True
        elif tag in {"a", "button"}:
            self._capture_interactive = True
            self._current_interactive_tag = tag
            self._interactive_text_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._capture_title = False
        elif tag == "h1":
            self._capture_h1 = False
        elif tag in {"a", "button"} and self._capture_interactive:
            text = normalize_text("".join(self._interactive_text_parts))
            if text:
                self.interactive_texts.append(text)
            self._capture_interactive = False
            self._current_interactive_tag = None
            self._interactive_text_parts = []

    def handle_data(self, data: str) -> None:
        if not data.strip():
            return
        cleaned = html.unescape(data)
        self.raw_text_parts.append(cleaned)
        if self._capture_title:
            self.title_parts.append(cleaned)
        if self._capture_h1:
            self.h1_parts.append(cleaned)
        if self._capture_interactive:
            self._interactive_text_parts.append(cleaned)


def load_config(path: Path) -> list[CheckTarget]:
    with path.open("rb") as handle:
        data = tomllib.load(handle)

    urls = data.get("urls", [])
    if not isinstance(urls, list):
        raise ValueError("Config key 'urls' must be an array of tables.")

    targets: list[CheckTarget] = []
    for index, item in enumerate(urls, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Entry {index} in 'urls' must be a table.")
        name = str(item.get("name", "")).strip()
        url = str(item.get("url", "")).strip()
        if not name or not url:
            raise ValueError(f"Entry {index} must include non-empty 'name' and 'url'.")

        allow_status_codes = item.get("allow_status_codes", [200])
        if not isinstance(allow_status_codes, list) or not allow_status_codes:
            raise ValueError(f"Entry {index} must set 'allow_status_codes' to a non-empty array.")

        target = CheckTarget(
            name=name,
            url=url,
            expected_text=str(item.get("expected_text", "")).strip(),
            cta_text=str(item.get("cta_text", "")).strip(),
            allow_status_codes=[int(code) for code in allow_status_codes],
        )
        targets.append(target)

    if not targets:
        raise ValueError("No URLs configured. Add at least one entry to [urls].")

    return targets


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def extract_and_check(target: CheckTarget) -> CheckResult:
    start = datetime.now(timezone.utc)
    # Shory blocks common cloud-hosting IPs, so use a read-only availability proxy.
    check_url = f"https://r.jina.ai/{target.url}"
    request = urllib.request.Request(
        check_url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; ShoryWebsiteHealthBot/1.0)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )

    status_code: int | None = None
    final_url = target.url
    response_time_ms: int | None = None
    page_html = ""
    issues: list[str] = []
    title = ""
    h1 = ""
    has_gtm = False
    has_ga4 = False

    try:
        with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            status_code = response.getcode()
            final_url = target.url
            body = response.read()
            response_time_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
            charset = response.headers.get_content_charset() or "utf-8"
            page_html = body.decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        status_code = exc.code
        response_time_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
        try:
            body = exc.read()
            charset = exc.headers.get_content_charset() or "utf-8"
            page_html = body.decode(charset, errors="replace")
            final_url = target.url
        except Exception:
            page_html = ""
        issues.append(f"HTTP status {status_code}")
    except urllib.error.URLError as exc:
        response_time_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
        reason = getattr(exc, "reason", exc)
        issues.append(f"Request failed: {reason}")
    except Exception as exc:  # pragma: no cover - defensive
        response_time_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
        issues.append(f"Unexpected error: {exc}")

    if page_html:
        parser = PageParser()
        parser.feed(page_html)
        title = " ".join(parser.title_parts).strip()
        h1 = " ".join(parser.h1_parts).strip()
        raw_text = normalize_text(" ".join(parser.raw_text_parts))
        interactive_texts = parser.interactive_texts
        lower_html = page_html.lower()
        has_gtm = "googletagmanager.com/gtm.js" in lower_html or "gtm-" in lower_html
        has_ga4 = (
            "googletagmanager.com/gtag/js" in lower_html
            or "gtag(" in lower_html
            or "ga4" in lower_html
            or "google-analytics.com" in lower_html
        )

        if status_code is not None and status_code not in target.allow_status_codes:
            issues.append(f"Unexpected HTTP status {status_code}")
        if not title:
            issues.append("Missing page title")
        if not h1:
            issues.append("Missing H1")

        expected_text = normalize_text(target.expected_text)
        cta_text = normalize_text(target.cta_text)
        if expected_text and expected_text not in raw_text:
            issues.append(f"Expected text not found: {target.expected_text}")
        if cta_text and cta_text not in raw_text and cta_text not in interactive_texts:
            issues.append(f"CTA text not found: {target.cta_text}")
        if not has_gtm:
            issues.append("GTM script not found")
        if not has_ga4:
            issues.append("GA4 script not found")

    # Stakeholder availability is based only on the HTTP response.
    ok = status_code in target.allow_status_codes
    if ok:
        issues = []
    elif status_code is not None and not issues:
        issues.append(f"HTTP status {status_code}")

    return CheckResult(
        target=target,
        ok=ok,
        status_code=status_code,
        final_url=final_url,
        response_time_ms=response_time_ms,
        title=title,
        h1=h1,
        issues=issues,
        has_gtm=has_gtm,
        has_ga4=has_ga4,
    )


def format_utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def format_uae_timestamp() -> str:
    return datetime.now(UAE_TZ).strftime("%Y-%m-%d %H:%M:%S UAE")


def build_slack_payload(results: list[CheckResult]) -> dict[str, Any]:
    failed = [result for result in results if not result.ok]
    lines = [
        ":rotating_light: *Website Health Alert*",
        f"*Checked at:* {format_utc_timestamp()}",
        f"*UAE time:* {format_uae_timestamp()}",
        "",
    ]

    for result in failed:
        lines.extend(
            [
                f"*URL:* {result.target.url}",
                f"*Failure:* {'; '.join(result.issues)}",
                f"*HTTP status:* {result.status_code if result.status_code is not None else 'n/a'}",
                f"*Response time:* {result.response_time_ms if result.response_time_ms is not None else 'n/a'} ms",
                f"*Title:* {result.title or 'n/a'}",
                f"*H1:* {result.h1 or 'n/a'}",
                f"*Final URL:* {result.final_url}",
                "",
            ]
        )

    return {"text": "\n".join(lines).strip()}


def send_slack_alert(webhook_url: str, payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS):
        pass


def print_result(result: CheckResult) -> None:
    status = "PASS" if result.ok else "FAIL"
    print(f"[{status}] {result.target.name}")
    print(f"  URL: {result.target.url}")
    print(f"  Final URL: {result.final_url}")
    print(f"  HTTP status: {result.status_code if result.status_code is not None else 'n/a'}")
    print(f"  Response time: {result.response_time_ms if result.response_time_ms is not None else 'n/a'} ms")
    print(f"  Title: {result.title or 'n/a'}")
    print(f"  H1: {result.h1 or 'n/a'}")
    print(f"  GTM: {'yes' if result.has_gtm else 'no'}")
    print(f"  GA4: {'yes' if result.has_ga4 else 'no'}")
    if result.ok:
        print("  Issues: none")
    else:
        for issue in result.issues:
            print(f"  Issue: {issue}")
    print()


def write_status_file(results: list[CheckResult], output_path: Path) -> None:
    checked_at = datetime.now(timezone.utc)
    payload = {
        "checked_at_utc": checked_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "checked_at_uae": checked_at.astimezone(UAE_TZ).strftime("%Y-%m-%d %H:%M:%S UAE"),
        "all_passed": all(result.ok for result in results),
        "results": [
            {
                "name": result.target.name,
                "url": result.target.url,
                "ok": result.ok,
                "status_code": result.status_code,
                "final_url": result.final_url,
                "response_time_ms": result.response_time_ms,
                "title": result.title,
                "h1": result.h1,
                "issues": result.issues,
                "has_gtm": result.has_gtm,
                "has_ga4": result.has_ga4,
            }
            for result in results
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote status file: {output_path}")


def main() -> int:
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("website_health_config.toml")
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    print(f"Loaded config: {config_path}")
    targets = load_config(config_path)
    results = [extract_and_check(target) for target in targets]

    print(f"Run timestamp (UTC): {format_utc_timestamp()}")
    print(f"Run timestamp (UAE): {format_uae_timestamp()}")
    print()

    for result in results:
        print_result(result)

    if output_path:
        write_status_file(results, output_path)

    failed = [result for result in results if not result.ok]
    if failed:
        webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
        if webhook_url:
            print(f"Sending Slack alert for {len(failed)} failed check(s).")
            send_slack_alert(webhook_url, build_slack_payload(results))
        else:
            print("SLACK_WEBHOOK_URL is not set, so no Slack alert was sent.")
        return 1

    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

