"""Live page availability checks for the Vercel dashboard."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
import json
from pathlib import Path
import time
import tomllib
import urllib.error
import urllib.request

from monitoring.website_health import UAE_TZ, load_config


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "monitoring" / "website_health_config.toml"
CHECK_TIMEOUT_SECONDS = 30


def load_upcoming_slots():
    with CONFIG_PATH.open("rb") as config_file:
        return max(0, int(tomllib.load(config_file).get("upcoming_slots", 0)))


def check_availability(target):
    """Use a read-only web proxy because Shory blocks Vercel's outgoing request."""
    started = time.monotonic()
    proxy_url = f"https://r.jina.ai/{target.url}"
    request = urllib.request.Request(
        proxy_url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; ShoryStatusChecker/1.0)",
            "Accept": "text/plain",
        },
    )

    status_code = None
    issues = []
    try:
        with urllib.request.urlopen(request, timeout=CHECK_TIMEOUT_SECONDS) as response:
            status_code = response.getcode()
            response.read(1)
    except urllib.error.HTTPError as exc:
        status_code = exc.code
        issues.append(f"Page check returned HTTP {exc.code}")
    except urllib.error.URLError as exc:
        issues.append(f"Page check failed: {getattr(exc, 'reason', exc)}")
    except Exception as exc:
        issues.append(f"Page check failed: {exc}")

    available = status_code is not None and 200 <= status_code < 400
    if not available and not issues:
        issues.append(f"Page check returned HTTP {status_code}")

    return {
        "name": target.name,
        "url": target.url,
        "ok": available,
        "status_code": status_code,
        "final_url": target.url,
        "response_time_ms": int((time.monotonic() - started) * 1000),
        "issues": issues,
    }


def result_payload():
    targets = load_config(CONFIG_PATH)
    with ThreadPoolExecutor(max_workers=1) as executor:
        results = list(executor.map(check_availability, targets))

    results.extend(
        {
            "name": "To be added soon",
            "url": "",
            "ok": None,
            "pending": True,
            "status_code": None,
            "final_url": "",
            "response_time_ms": None,
            "issues": [],
        }
        for _ in range(load_upcoming_slots())
    )

    checked_at = datetime.now(timezone.utc)
    active_results = [result for result in results if not result.get("pending")]
    return {
        "checked_at_utc": checked_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "checked_at_uae": checked_at.astimezone(UAE_TZ).strftime("%Y-%m-%d %H:%M:%S UAE"),
        "all_passed": all(result["ok"] for result in active_results),
        "results": results,
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            payload = result_payload()
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
        except Exception as exc:
            body = json.dumps({"error": str(exc)}).encode("utf-8")
            self.send_response(500)

        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
