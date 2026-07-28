"""Live partner checks for the Vercel dashboard."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
import json
from pathlib import Path
import tomllib

from monitoring.website_health import UAE_TZ, extract_and_check, load_config


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "monitoring" / "website_health_config.toml"


def load_upcoming_slots():
    with CONFIG_PATH.open("rb") as config_file:
        return max(0, int(tomllib.load(config_file).get("upcoming_slots", 0)))


def result_payload():
    targets = load_config(CONFIG_PATH)
    with ThreadPoolExecutor(max_workers=min(8, len(targets))) as executor:
        checked_results = list(executor.map(extract_and_check, targets))

    results = [
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
        for result in checked_results
    ]
    results.extend(
        {
            "name": "To be added soon",
            "url": "",
            "ok": None,
            "pending": True,
            "status_code": None,
            "final_url": "",
            "response_time_ms": None,
            "title": "",
            "h1": "",
            "issues": [],
            "has_gtm": None,
            "has_ga4": None,
        }
        for _ in range(load_upcoming_slots())
    )

    checked_at = datetime.now(timezone.utc)
    return {
        "checked_at_utc": checked_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "checked_at_uae": checked_at.astimezone(UAE_TZ).strftime("%Y-%m-%d %H:%M:%S UAE"),
        "all_passed": all(result.ok for result in checked_results),
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
