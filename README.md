# Maine Gas Prices Widget

Daily-updating embeddable widget showing Maine's cheapest and most expensive county
gas prices and the state vs. national average. Source: AAA Maine.

## How it works

A GitHub Actions cron runs `fetch_prices.py` every morning, scrapes
gasprices.aaa.com/?state=ME, and writes `data/prices.json`. GitHub Pages serves
`embed.html`, which BDN iframes onto the site.

## Local development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest                              # run scraper tests
python3 -m http.server 8000         # then open http://localhost:8000/index.html
```

## Embed

```html
<iframe src="https://<gh-pages-url>/embed.html"
        width="100%" height="640" frameborder="0"
        style="border:0;"></iframe>
```
