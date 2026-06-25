# Stock Graph Dashboard

A static-friendly stock dashboard for building pages of stock charts with:

- 5-year daily price history
- percent change from the first visible price to the latest price
- markers where a stock doubles
- company names under tickers
- estimated market-cap-to-revenue multiples for stocks when Nasdaq fundamentals are available

## Local Use

```bash
python3 app.py
```

Then open <http://127.0.0.1:8765>.

## GitHub Pages

GitHub Pages serves `index.html` and prebuilt JSON files in `data/history/`.

To refresh the hosted static data manually:

```bash
python3 generate_static_data.py
```

The included GitHub Actions workflow also refreshes static data on weekdays.
