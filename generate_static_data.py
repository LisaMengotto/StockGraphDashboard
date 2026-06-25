#!/usr/bin/env python3
"""Generate static stock history JSON for GitHub Pages."""

from __future__ import annotations

import json
from pathlib import Path

import app


YEARS = 5
SYMBOLS = [
    "AAPL",
    "MSFT",
    "NVDA",
    "SPY",
    "QQQ",
    "DIA",
    "MU",
    "SNDK",
    "WDC",
    "AMD",
    "SNPS",
    "CDNS",
    "ASML",
    "AMAT",
    "LRCX",
    "KLAC",
    "ONTO",
    "BRKR",
    "TMO",
    "NVMI",
    "AMKR",
    "ASX",
    "TSM",
    "INTC",
    "CRWV",
    "IT",
]


def main() -> None:
    out_dir = Path("data/history")
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"years": YEARS, "symbols": [], "errors": []}

    for symbol in SYMBOLS:
        try:
            data = app.fetch_history(symbol, YEARS)
            path = out_dir / f"{data['symbol']}-{YEARS}y.json"
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            manifest["symbols"].append(data["symbol"])
            print(f"wrote {path}")
        except Exception as exc:  # noqa: BLE001 - report all static generation misses
            manifest["errors"].append({"symbol": symbol, "message": str(exc)})
            print(f"skipped {symbol}: {exc}")

    Path("data").mkdir(exist_ok=True)
    Path("data/manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
