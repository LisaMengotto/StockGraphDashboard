#!/usr/bin/env python3
"""Local stock chart dashboard.

Run with:
    python3 app.py

Then open http://127.0.0.1:8765
"""

from __future__ import annotations

import hashlib
import http.cookiejar
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / ".cache"
CACHE_SECONDS = 60 * 60 * 8
HOST = "127.0.0.1"
PORT = 8765


def normalize_symbol(symbol: str) -> str:
    cleaned = "".join(ch for ch in symbol.strip().lower() if ch.isalnum() or ch in ".-")
    if not cleaned:
        raise ValueError("Symbol cannot be empty")
    return cleaned


def display_symbol(symbol: str) -> str:
    return symbol.upper()


def parse_market_number(value: str) -> float:
    cleaned = str(value).replace("$", "").replace(",", "").strip()
    if not cleaned or cleaned.upper() in {"N/A", "NA"}:
        raise ValueError("missing numeric value")
    return float(cleaned)


def nasdaq_headers(symbol: str) -> dict:
    display = display_symbol(symbol)
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://www.nasdaq.com",
        "Referer": f"https://www.nasdaq.com/market-activity/stocks/{display.lower()}",
        "User-Agent": "Mozilla/5.0 local-stock-dashboard/1.0",
    }


def fetch_nasdaq_rows(symbol: str, start: date, end: date) -> list[dict]:
    display = display_symbol(symbol)
    parsed = []
    for asset_class in ("stocks", "etf"):
        query = urllib.parse.urlencode(
            {
                "assetclass": asset_class,
                "fromdate": start.isoformat(),
                "todate": end.isoformat(),
                "limit": "9999",
            }
        )
        url = f"https://api.nasdaq.com/api/quote/{urllib.parse.quote(display)}/historical?{query}"
        request = urllib.request.Request(
            url,
            headers=nasdaq_headers(symbol)
            | {"Referer": f"https://www.nasdaq.com/market-activity/{asset_class}/{display.lower()}/historical"},
        )
        with open_stock_url(request) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        data = payload.get("data") or {}
        rows = data.get("tradesTable", {}).get("rows") or []
        for row in rows:
            try:
                month, day, year = row["date"].split("/")
                parsed.append(
                    {
                        "date": f"{year}-{int(month):02d}-{int(day):02d}",
                        "open": parse_market_number(row["open"]),
                        "high": parse_market_number(row["high"]),
                        "low": parse_market_number(row["low"]),
                        "close": parse_market_number(row["close"]),
                        "volume": int(parse_market_number(row["volume"])),
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
        if parsed:
            break
    parsed.sort(key=lambda point: point["date"])
    return parsed


def fetch_nasdaq_json(url: str, symbol: str) -> dict:
    request = urllib.request.Request(url, headers=nasdaq_headers(symbol))
    with open_stock_url(request) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def fetch_nasdaq_fundamentals(symbol: str) -> dict | None:
    display = display_symbol(symbol)
    summary_url = f"https://api.nasdaq.com/api/quote/{urllib.parse.quote(display)}/summary?assetclass=stocks"
    financials_url = f"https://api.nasdaq.com/api/company/{urllib.parse.quote(display)}/financials?frequency=1"

    summary = fetch_nasdaq_json(summary_url, symbol).get("data") or {}
    summary_data = summary.get("summaryData") or {}
    market_cap_value = (summary_data.get("MarketCap") or {}).get("value")
    market_cap = parse_market_number(market_cap_value)

    if market_cap <= 0:
        return None

    financials = fetch_nasdaq_json(financials_url, symbol).get("data") or {}
    income = financials.get("incomeStatementTable") or {}
    headers = income.get("headers") or {}
    revenue_period = headers.get("value2")
    revenue = None
    for row in income.get("rows") or []:
        if row.get("value1") == "Total Revenue":
            revenue = parse_market_number(row.get("value2")) * 1000
            break
    if not revenue or revenue <= 0:
        return None

    return {
        "marketCap": market_cap,
        "revenue": revenue,
        "revenuePeriod": revenue_period,
        "source": "Nasdaq summary and annual financials",
    }


def open_stock_url(request: urllib.request.Request):
    try:
        return urllib.request.urlopen(request, timeout=20)
    except urllib.error.URLError as exc:
        if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
            raise
        local_context = ssl._create_unverified_context()
        return urllib.request.urlopen(request, timeout=20, context=local_context)


def stooq_opener():
    cookie_jar = http.cookiejar.CookieJar()
    handlers = [urllib.request.HTTPCookieProcessor(cookie_jar)]
    handlers.append(urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
    return urllib.request.build_opener(*handlers)


def solve_stooq_challenge(body: str, opener: urllib.request.OpenerDirector) -> bool:
    challenge = re.search(r'const c="([^"]+)",d=(\d+)', body)
    if not challenge:
        return False
    token, difficulty = challenge.group(1), int(challenge.group(2))
    prefix = "0" * difficulty
    nonce = 0
    while True:
        digest = hashlib.sha256(f"{token}{nonce}".encode("utf-8")).hexdigest()
        if digest.startswith(prefix):
            break
        nonce += 1
    verify_body = urllib.parse.urlencode({"c": token, "n": nonce}).encode("utf-8")
    verify_request = urllib.request.Request(
        "https://stooq.com/__verify",
        data=verify_body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0 local-stock-dashboard/1.0",
        },
        method="POST",
    )
    with opener.open(verify_request, timeout=20) as response:
        return 200 <= response.status < 300


def fetch_stooq_csv(url: str) -> str:
    opener = stooq_opener()
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 local-stock-dashboard/1.0"})
    with opener.open(request, timeout=20) as response:
        body = response.read().decode("utf-8", errors="replace")
    if "/__verify" in body and solve_stooq_challenge(body, opener):
        with opener.open(request, timeout=20) as response:
            body = response.read().decode("utf-8", errors="replace")
    return body


def fetch_history(symbol: str, years: int) -> dict:
    years = max(1, min(int(years), 40))
    normalized = normalize_symbol(symbol)
    today = date.today()
    start = today - timedelta(days=round(years * 365.25) + 10)
    cache_key = f"{normalized}-{years}y-{today.isoformat()}-v3.json"
    cache_path = CACHE_DIR / cache_key

    if cache_path.exists() and time.time() - cache_path.stat().st_mtime < CACHE_SECONDS:
        return json.loads(cache_path.read_text())

    try:
        rows = fetch_nasdaq_rows(normalized, start, today)
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not fetch data for {display_symbol(normalized)}: {exc}") from exc

    if not rows:
        raise ValueError(f"No price history found for {display_symbol(normalized)}")

    try:
        fundamentals = fetch_nasdaq_fundamentals(normalized)
    except (KeyError, TypeError, ValueError, urllib.error.URLError, json.JSONDecodeError):
        fundamentals = None

    data = {
        "symbol": display_symbol(normalized),
        "sourceSymbol": normalized,
        "years": years,
        "source": "Nasdaq daily historical prices",
        "retrievedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fundamentals": fundamentals,
        "prices": rows[-round(years * 253) :],
    }
    CACHE_DIR.mkdir(exist_ok=True)
    cache_path.write_text(json.dumps(data))
    return data


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self.respond_file(ROOT / "index.html", "text/html; charset=utf-8")
            return
        if parsed.path == "/api/history":
            self.respond_history(parsed.query)
            return
        self.send_error(404, "Not found")

    def respond_file(self, path: Path, content_type: str) -> None:
        try:
            body = path.read_bytes()
        except FileNotFoundError:
            self.send_error(404, "Not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def respond_history(self, query: str) -> None:
        params = urllib.parse.parse_qs(query)
        symbols = params.get("symbols", [""])[0].split(",")
        years = params.get("years", ["5"])[0]
        payload = {"results": [], "errors": []}
        for symbol in symbols:
            symbol = symbol.strip()
            if not symbol:
                continue
            try:
                payload["results"].append(fetch_history(symbol, int(years)))
            except Exception as exc:  # noqa: BLE001 - sent to local UI as a user-facing error
                payload["errors"].append({"symbol": symbol.upper(), "message": str(exc)})
        status = 200 if payload["results"] else 422
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}")


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Stock dashboard running at http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
