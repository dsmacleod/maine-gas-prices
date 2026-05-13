# Maine Gas Prices Widget Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an evergreen, daily-updating embeddable widget for the BDN site showing Maine's cheapest county, most expensive county, and state vs. national average gas prices, with a county-level choropleth map.

**Architecture:** GitHub Actions cron runs a Python scraper daily that pulls AAA Maine state-page data and writes `data/prices.json`. GitHub Pages serves a static `embed.html` that BDN embeds as an iframe. No server, no DB, no API keys. Mirrors the existing `flagg-vs-lebron` pattern in this sandbox.

**Tech Stack:**
- Python 3 stdlib (`urllib`, `re`, `html.parser`, `json`) for the scraper — no third-party deps to keep Actions fast and reliable
- Vanilla HTML + CSS + JS for the embed (no framework, no build step)
- Hand-rendered inline SVG for the choropleth (no D3, no Leaflet)
- GitHub Actions for the cron
- GitHub Pages for hosting
- pytest for scraper tests, Playwright for one front-end smoke test

**Reference design doc:** `docs/plans/2026-05-08-maine-gas-prices-widget-design.md`

---

## Plan amendment (discovered during Task 2 — 2026-05-11)

The AAA Maine state page does NOT contain county-level prices in the static HTML. County data is loaded client-side from a separate WordPress endpoint that returns a JS config blob:

- **HTML page** (`https://gasprices.aaa.com/?state=ME`) — has Maine state avg, national avg, and the Yesterday/Week/Month/Year trend table for state. ~100KB.
- **Map config JS** (`https://gasprices.aaa.com/index.php?premiumhtml5map_js_data=true&map_id=21`) — has a `map_data` JSON object with all 16 Maine counties and their current regular-gas prices in the `comment` field. ~4KB.

Example `map_data` row:
```json
"st1":{"id":1,"name":"Androscoggin","comment":"$4.561","color_map":"#ca3338", ...}
```

Tasks 6 and 11 are updated below to fetch both URLs and parse `comment` as the regular price (3 decimal places, e.g. `$4.561`). Tasks 3, 4, 5 (state/national/trend) still parse the main HTML and remain as written. AAA prices use 3 decimal places throughout — every regex range `\d+\.\d{2,3}` already accommodates this; no change needed.

Fixture pair captured:
- `tests/fixtures/aaa-happy.html` (HTML)
- `tests/fixtures/aaa-map-cfg-happy.js` (map config)

---

## Repository layout (target)

```
maine-gas-prices/
├── .github/workflows/fetch-prices.yml
├── data/
│   ├── prices.json              # written by scraper, committed
│   └── maine-counties.geo.json  # static, committed
├── docs/plans/                   # design + this plan
├── tests/
│   ├── fixtures/
│   │   ├── aaa-happy.html
│   │   ├── aaa-missing-county.html
│   │   └── aaa-structure-changed.html
│   ├── fixtures/prices-fresh.json
│   ├── fixtures/prices-stale.json
│   ├── test_scraper.py
│   └── test_embed.py             # Playwright smoke test
├── embed.html                    # the widget BDN iframes
├── index.html                    # standalone preview page
├── fetch-prices.py               # the scraper
├── requirements-dev.txt
├── .gitignore
└── README.md
```

---

## Task 1: Project scaffolding

**Files:**
- Create: `maine-gas-prices/.gitignore`
- Create: `maine-gas-prices/README.md`
- Create: `maine-gas-prices/requirements-dev.txt`

**Step 1: Write `.gitignore`**

```
__pycache__/
*.pyc
.pytest_cache/
.venv/
node_modules/
.DS_Store
test-results/
playwright-report/
```

**Step 2: Write `requirements-dev.txt`**

```
pytest>=8.0
playwright>=1.45
```

**Step 3: Write `README.md`**

```markdown
# Maine Gas Prices Widget

Daily-updating embeddable widget showing Maine's cheapest and most expensive county
gas prices and the state vs. national average. Source: AAA Maine.

## How it works

A GitHub Actions cron runs `fetch-prices.py` every morning, scrapes
gasprices.aaa.com/?state=ME, and writes `data/prices.json`. GitHub Pages serves
`embed.html`, which BDN iframes onto the site.

## Local development

```
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
```

**Step 4: Commit**

```bash
cd maine-gas-prices
git add .gitignore README.md requirements-dev.txt
git commit -m "chore(maine-gas-prices): scaffold project"
```

---

## Task 2: Capture AAA fixture HTML (happy path)

**Files:**
- Create: `maine-gas-prices/tests/fixtures/aaa-happy.html`

**Step 1: Save the live AAA page as a fixture**

Run:
```bash
mkdir -p maine-gas-prices/tests/fixtures
curl -sSL -A "Mozilla/5.0 (compatible; BDN-fixture-capture/1.0)" \
  "https://gasprices.aaa.com/?state=ME" \
  -o maine-gas-prices/tests/fixtures/aaa-happy.html
```

Expected: file is ~150–400KB and `grep -c "Current Avg" maine-gas-prices/tests/fixtures/aaa-happy.html` returns ≥1.

**Step 2: Inspect the structure**

Run:
```bash
grep -o 'id="[^"]*"' maine-gas-prices/tests/fixtures/aaa-happy.html | sort -u | head -30
grep -oE '(Aroostook|Hancock|Cumberland|Penobscot)[^<]{0,80}' maine-gas-prices/tests/fixtures/aaa-happy.html | head -10
```

Expected: visible county names + price strings near them. Note the surrounding HTML — selectors will be derived from this in Task 3.

**Step 3: Commit the fixture**

```bash
git add maine-gas-prices/tests/fixtures/aaa-happy.html
git commit -m "test(maine-gas-prices): capture AAA happy-path fixture"
```

> **Note for the implementer:** if AAA's structure looks different from the design's assumptions, STOP and report findings before proceeding. Do not improvise selectors that aren't grounded in the fixture.

---

## Task 3: Scraper — parse Maine state average (TDD)

**Files:**
- Create: `maine-gas-prices/tests/test_scraper.py`
- Create: `maine-gas-prices/fetch-prices.py`

**Step 1: Write the failing test**

```python
# tests/test_scraper.py
import os
from fetch_prices import parse_state_average

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

def _load(name):
    with open(os.path.join(FIXTURES, name)) as f:
        return f.read()

def test_parse_state_average_happy():
    html = _load("aaa-happy.html")
    avg = parse_state_average(html)
    assert isinstance(avg, float)
    assert 1.0 < avg < 10.0
```

Add `tests/__init__.py` (empty) so pytest can import. Also add `conftest.py` at repo root:

```python
# conftest.py
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
```

**Step 2: Run test to verify it fails**

Run: `cd maine-gas-prices && pytest tests/test_scraper.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fetch_prices'` (note: import name uses underscore; create `fetch_prices.py` not `fetch-prices.py`, OR use `importlib` — go with underscore filename and update Actions workflow accordingly).

**Step 3: Rename plan target**

Use `fetch_prices.py` (underscore) for Python import compatibility. Update the workflow file later to call `python3 fetch_prices.py`.

**Step 4: Write minimal implementation**

Open `tests/fixtures/aaa-happy.html` and find the markup containing the Maine state average. Common AAA pattern: a `<td>` or `<div>` with class containing `price` near the text "Current Avg." Write a regex grounded in that exact markup. Example sketch (replace with what the fixture actually shows):

```python
# fetch_prices.py
import re

def parse_state_average(html: str) -> float:
    # Match the "Current Avg." block, then the first $X.XX after it
    m = re.search(r'Current Avg\.[^$]{0,500}\$(\d+\.\d{2,3})', html, re.DOTALL)
    if not m:
        raise ValueError("Could not locate Maine state average in AAA HTML")
    return float(m.group(1))
```

**Step 5: Run test to verify it passes**

Run: `pytest tests/test_scraper.py::test_parse_state_average_happy -v`
Expected: PASS.

**Step 6: Commit**

```bash
git add maine-gas-prices/tests/__init__.py maine-gas-prices/conftest.py \
        maine-gas-prices/tests/test_scraper.py maine-gas-prices/fetch_prices.py
git commit -m "feat(maine-gas-prices): parse Maine state avg from AAA"
```

---

## Task 4: Scraper — parse national average (TDD)

**Files:**
- Modify: `maine-gas-prices/tests/test_scraper.py`
- Modify: `maine-gas-prices/fetch_prices.py`

**Step 1: Write the failing test**

```python
def test_parse_national_average_happy():
    html = _load("aaa-happy.html")
    avg = parse_national_average(html)
    assert isinstance(avg, float)
    assert 1.0 < avg < 10.0
```

**Step 2: Run** — Expected FAIL (`parse_national_average` undefined).

**Step 3: Implement** — find the "National Avg." marker in the fixture, write the matching regex.

```python
def parse_national_average(html: str) -> float:
    m = re.search(r'National Avg\.[^$]{0,500}\$(\d+\.\d{2,3})', html, re.DOTALL)
    if not m:
        raise ValueError("Could not locate national average in AAA HTML")
    return float(m.group(1))
```

**Step 4: Run** — Expected PASS.

**Step 5: Commit** — `feat(maine-gas-prices): parse national average`

---

## Task 5: Scraper — parse trend deltas (week/month/year ago) (TDD)

**Files:**
- Modify: `maine-gas-prices/tests/test_scraper.py`
- Modify: `maine-gas-prices/fetch_prices.py`

**Step 1: Write failing test**

```python
def test_parse_state_trend_happy():
    html = _load("aaa-happy.html")
    trend = parse_state_trend(html)
    assert set(trend.keys()) == {"week_ago", "month_ago", "year_ago"}
    for v in trend.values():
        assert 1.0 < v < 10.0
```

**Step 2: Run** — Expected FAIL.

**Step 3: Implement.** AAA's state page typically shows a "Yesterday / Week Ago / Month Ago / Year Ago" row. Parse each. Skip "Yesterday" — design only requires three.

```python
def parse_state_trend(html: str) -> dict:
    keys = [("week_ago", "Week Ago"), ("month_ago", "Month Ago"), ("year_ago", "Year Ago")]
    out = {}
    for k, label in keys:
        m = re.search(rf'{re.escape(label)}[^$]{{0,300}}\$(\d+\.\d{{2,3}})', html, re.DOTALL)
        if not m:
            raise ValueError(f"Could not locate '{label}' in AAA HTML")
        out[k] = float(m.group(1))
    return out
```

**Step 4: Run** — Expected PASS.

**Step 5: Commit** — `feat(maine-gas-prices): parse state trend deltas`

---

## Task 6: Scraper — parse county prices from map config (TDD)

**Files:**
- Modify: `maine-gas-prices/tests/test_scraper.py`
- Modify: `maine-gas-prices/fetch_prices.py`

> **Input:** counties come from the **map config JS endpoint**, not the HTML page. Use the fixture `tests/fixtures/aaa-map-cfg-happy.js`. Each county appears in a `map_data` JSON object with the shape `{"id":N,"name":"Aroostook","comment":"$4.522", ...}`. The `comment` field holds the regular-gas price.

**Step 1: Write failing test**

```python
def test_parse_counties_happy():
    js = _load("aaa-map-cfg-happy.js")
    counties = parse_counties(js)
    assert len(counties) == 16
    names = {c["name"] for c in counties}
    expected = {"Androscoggin","Aroostook","Cumberland","Franklin","Hancock",
                "Kennebec","Knox","Lincoln","Oxford","Penobscot","Piscataquis",
                "Sagadahoc","Somerset","Waldo","Washington","York"}
    assert names == expected
    for c in counties:
        assert "fips" in c and c["fips"].startswith("23")
        assert 1.0 < c["avg_regular"] < 10.0
```

**Step 2: Run** — Expected FAIL.

**Step 3: Implement.**

```python
ME_FIPS = {
    "Androscoggin": "23001", "Aroostook": "23003", "Cumberland": "23005",
    "Franklin": "23007", "Hancock": "23009", "Kennebec": "23011",
    "Knox": "23013", "Lincoln": "23015", "Oxford": "23017",
    "Penobscot": "23019", "Piscataquis": "23021", "Sagadahoc": "23023",
    "Somerset": "23025", "Waldo": "23027", "Washington": "23029", "York": "23031",
}

def parse_counties(map_cfg_js: str) -> list:
    """Extract all 16 Maine county prices from AAA's map config JS.

    The config file contains a line of the form:
        map_data : {"st1":{"id":1,"name":"Androscoggin","comment":"$4.561",...}, ...}
    """
    m = re.search(r'map_data\s*:\s*(\{.*?\})\s*,\s*groups', map_cfg_js, re.DOTALL)
    if not m:
        raise ValueError("Could not locate map_data block in AAA map config JS")
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise ValueError(f"map_data is not valid JSON: {e}") from e

    counties = []
    seen = set()
    for entry in data.values():
        name = entry.get("name", "").strip()
        price_str = entry.get("comment", "")
        pm = re.match(r'\$(\d+\.\d{2,3})', price_str)
        if not pm:
            raise ValueError(f"County {name!r} has unparseable price: {price_str!r}")
        if name not in ME_FIPS:
            raise ValueError(f"Unknown Maine county in map_data: {name!r}")
        counties.append({
            "name": name,
            "fips": ME_FIPS[name],
            "avg_regular": float(pm.group(1)),
        })
        seen.add(name)
    missing = set(ME_FIPS) - seen
    if missing:
        raise ValueError(f"Missing counties in map_data: {sorted(missing)}")
    return counties
```

Make sure `import json` is at the top of `fetch_prices.py`.

**Step 4: Run** — Expected PASS.

**Step 5: Commit** — `feat(maine-gas-prices): parse all 16 Maine county prices from map config`

---

## Task 7: Scraper — assemble full payload + cheapest/most-expensive (TDD)

**Files:**
- Modify: `maine-gas-prices/tests/test_scraper.py`
- Modify: `maine-gas-prices/fetch_prices.py`

**Step 1: Write failing test**

```python
def test_build_payload_happy():
    html = _load("aaa-happy.html")
    map_cfg = _load("aaa-map-cfg-happy.js")
    payload = build_payload(html, map_cfg)
    assert payload["state"]["name"] == "Maine"
    assert payload["state"]["avg_regular"] > 0
    assert set(payload["state"]["trend"].keys()) == {"week_ago","month_ago","year_ago"}
    assert payload["national"]["avg_regular"] > 0
    assert len(payload["counties"]) == 16
    assert payload["cheapest"]["avg_regular"] == min(c["avg_regular"] for c in payload["counties"])
    assert payload["most_expensive"]["avg_regular"] == max(c["avg_regular"] for c in payload["counties"])
    # ISO 8601 UTC timestamp ending in Z
    assert payload["updated"].endswith("Z")
```

**Step 2: Run** — Expected FAIL.

**Step 3: Implement**

```python
from datetime import datetime, timezone

def build_payload(html: str, map_cfg_js: str) -> dict:
    counties = parse_counties(map_cfg_js)
    cheapest = min(counties, key=lambda c: c["avg_regular"])
    most_expensive = max(counties, key=lambda c: c["avg_regular"])
    return {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "state": {
            "name": "Maine",
            "avg_regular": parse_state_average(html),
            "trend": parse_state_trend(html),
        },
        "national": {"avg_regular": parse_national_average(html)},
        "counties": counties,
        "cheapest": {"name": cheapest["name"], "avg_regular": cheapest["avg_regular"]},
        "most_expensive": {"name": most_expensive["name"], "avg_regular": most_expensive["avg_regular"]},
    }
```

**Step 4: Run** — Expected PASS.

**Step 5: Commit** — `feat(maine-gas-prices): build full prices payload`

---

## Task 8: Schema validation (TDD — failure cases)

**Files:**
- Modify: `maine-gas-prices/tests/test_scraper.py`
- Modify: `maine-gas-prices/fetch_prices.py`

**Step 1: Write failing tests**

```python
import pytest

def _good_payload():
    html = _load("aaa-happy.html")
    cfg  = _load("aaa-map-cfg-happy.js")
    return build_payload(html, cfg)

def test_validate_payload_accepts_good():
    validate_payload(_good_payload())  # should not raise

def test_validate_payload_rejects_missing_county():
    payload = _good_payload()
    payload["counties"] = payload["counties"][:15]  # drop one
    with pytest.raises(ValueError, match="16 counties"):
        validate_payload(payload)

def test_validate_payload_rejects_absurd_price():
    payload = _good_payload()
    payload["counties"][0]["avg_regular"] = 99.99
    with pytest.raises(ValueError, match="out of range"):
        validate_payload(payload)
```

**Step 2: Run** — Expected FAIL.

**Step 3: Implement**

```python
def validate_payload(p: dict) -> None:
    if len(p.get("counties", [])) != 16:
        raise ValueError("Expected exactly 16 counties")
    for c in p["counties"]:
        if not (1.0 < c["avg_regular"] < 10.0):
            raise ValueError(f"County {c['name']} price out of range: {c['avg_regular']}")
    for key in ("state", "national"):
        if not (1.0 < p[key]["avg_regular"] < 10.0):
            raise ValueError(f"{key} avg out of range")
```

**Step 4: Run** — Expected PASS.

**Step 5: Commit** — `feat(maine-gas-prices): validate scraped payload`

---

## Task 9: Negative fixture — missing county

**Files:**
- Create: `maine-gas-prices/tests/fixtures/aaa-map-cfg-missing-county.js`
- Modify: `maine-gas-prices/tests/test_scraper.py`

**Step 1: Create the broken fixture**

Copy the happy map-config fixture and remove Piscataquis from the `map_data` JSON.

```bash
cp maine-gas-prices/tests/fixtures/aaa-map-cfg-happy.js \
   maine-gas-prices/tests/fixtures/aaa-map-cfg-missing-county.js
```

Open the copy and delete the `"st11":{"id":11,"name":"Piscataquis",...}` entry from the `map_data` object (including its trailing comma if not last). Use the Edit tool, not sed — verify the JSON still parses by running:

```bash
python3 -c "
import re, json
js = open('maine-gas-prices/tests/fixtures/aaa-map-cfg-missing-county.js').read()
m = re.search(r'map_data\s*:\s*(\{.*?\})\s*,\s*groups', js, re.DOTALL)
data = json.loads(m.group(1))
print('counties:', len(data))
print('names:', sorted(e['name'] for e in data.values()))
"
```

Expected: prints `counties: 15` and a list NOT containing "Piscataquis".

**Step 2: Write failing test**

```python
def test_parse_counties_missing_raises():
    js = _load("aaa-map-cfg-missing-county.js")
    with pytest.raises(ValueError, match="Piscataquis"):
        parse_counties(js)
```

**Step 3: Run** — Expected PASS (`parse_counties` already raises ValueError listing missing counties).

If FAIL, ensure the error message in `parse_counties` includes the county name when listing missing entries.

**Step 4: Commit** — `test(maine-gas-prices): missing-county fixture + test`

---

## Task 10: Negative fixture — structure changed

**Files:**
- Create: `maine-gas-prices/tests/fixtures/aaa-structure-changed.html`
- Modify: `maine-gas-prices/tests/test_scraper.py`

**Step 1: Create the broken fixture**

```bash
echo "<html><body><h1>AAA Site Maintenance</h1></body></html>" \
  > maine-gas-prices/tests/fixtures/aaa-structure-changed.html
```

**Step 2: Write failing test**

```python
def test_parse_state_average_structure_changed_raises():
    html = _load("aaa-structure-changed.html")
    with pytest.raises(ValueError, match="state average"):
        parse_state_average(html)
```

**Step 3: Run** — Expected PASS.

**Step 4: Commit** — `test(maine-gas-prices): structure-changed fixture + test`

---

## Task 11: Scraper — fetch with retries + main entrypoint

**Files:**
- Modify: `maine-gas-prices/fetch_prices.py`

**Step 1: Add retrying fetch + `main()`**

```python
import json, os, sys, time, urllib.request, urllib.error

AAA_HTML_URL    = "https://gasprices.aaa.com/?state=ME"
AAA_MAP_CFG_URL = "https://gasprices.aaa.com/index.php?premiumhtml5map_js_data=true&map_id=21"
OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "prices.json")

def fetch_url(url: str, attempts: int = 3) -> str:
    last_err = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; BDN-gas-widget/1.0)"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            last_err = e
            if i < attempts - 1:
                time.sleep(2 ** i)  # 1s, 2s
    raise RuntimeError(f"Failed to fetch {url} after {attempts} attempts: {last_err}")

def main() -> int:
    try:
        html    = fetch_url(AAA_HTML_URL)
        map_cfg = fetch_url(AAA_MAP_CFG_URL)
        payload = build_payload(html, map_cfg)
        validate_payload(payload)
    except Exception as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"OK: wrote {OUT_PATH} (state ${payload['state']['avg_regular']}, {len(payload['counties'])} counties)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

**Step 2: Run end-to-end against fixtures (manual sanity check)**

```bash
cd maine-gas-prices
pytest -v   # all green
python3 -c "
from fetch_prices import build_payload, validate_payload
import json
html = open('tests/fixtures/aaa-happy.html').read()
cfg  = open('tests/fixtures/aaa-map-cfg-happy.js').read()
p = build_payload(html, cfg)
validate_payload(p)
print(json.dumps(p, indent=2)[:500])
"
```

Expected: prints valid JSON with state/national/counties.

**Step 3: Commit** — `feat(maine-gas-prices): main entrypoint with retrying fetch`

---

## Task 12: GitHub Actions workflow

**Files:**
- Create: `maine-gas-prices/.github/workflows/fetch-prices.yml`

**Step 1: Write workflow**

```yaml
name: Fetch Maine gas prices

on:
  schedule:
    - cron: '0 11 * * *'   # 7am ET (11:00 UTC) daily
  workflow_dispatch:

permissions:
  contents: write

jobs:
  fetch:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: maine-gas-prices
    steps:
      - uses: actions/checkout@v4

      - name: Run scraper
        run: python3 fetch_prices.py

      - name: Commit and push if changed
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/prices.json
          git diff --cached --quiet || (git commit -m "chore(maine-gas-prices): daily price update" && git push)
```

**Step 2: Sanity-check syntax**

Run:
```bash
python3 -c "import yaml; yaml.safe_load(open('maine-gas-prices/.github/workflows/fetch-prices.yml'))"
```
Expected: no error. (If `yaml` isn't installed, skip — GitHub will validate on push.)

**Step 3: Commit** — `ci(maine-gas-prices): daily AAA scrape workflow`

---

## Task 13: Maine county GeoJSON

**Files:**
- Create: `maine-gas-prices/data/maine-counties.geo.json`

**Step 1: Acquire from US Census TIGER/Line via the public CDN**

Run:
```bash
mkdir -p maine-gas-prices/data
curl -sSL "https://raw.githubusercontent.com/deldersveld/topojson/master/countries/us-states/ME-23-maine-counties.json" \
  -o /tmp/me-counties-raw.json
ls -la /tmp/me-counties-raw.json
```

Expected: file ~50–500KB. If 404 or empty, try alternative:
```bash
curl -sSL "https://raw.githubusercontent.com/glynnbird/usstatesgeojson/master/maine.geojson" \
  -o /tmp/me-counties-raw.json
```

> **Implementer note:** if neither works, surface this as a blocker rather than writing GeoJSON by hand. The fallback is to convert from US-wide counties (e.g. `https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json`) and filter to FIPS starting with "23".

**Step 2: Verify it's valid GeoJSON with FIPS properties**

```bash
python3 -c "
import json
g = json.load(open('/tmp/me-counties-raw.json'))
features = g.get('features') or g.get('objects', {}).get('counties', {}).get('geometries', [])
print('features:', len(features))
print('sample props:', features[0].get('properties') if features else None)
"
```

Expected: 16 features, properties contain a county name and/or FIPS. If properties don't include FIPS in form `23xxx`, write a small normalization script to inject it from the name → FIPS map already in `fetch_prices.py`.

**Step 3: Normalize and write final file**

Write a quick one-shot script (do not commit it) that:
1. Loads the raw file
2. Ensures each feature has `properties.fips` like `"23003"` and `properties.name` like `"Aroostook"`
3. Drops every other property to keep file size small
4. Saves to `maine-gas-prices/data/maine-counties.geo.json`

Target final size: under 50KB. If larger, run through `mapshaper` (online tool — paste, simplify to ~10%, export).

**Step 4: Commit** — `data(maine-gas-prices): Maine county GeoJSON`

---

## Task 14: `embed.html` — scaffold + JSON fetch

**Files:**
- Create: `maine-gas-prices/embed.html`

**Step 1: Write skeleton**

```html
<!DOCTYPE html>
<!--
  Maine Gas Prices Widget
  Embed this in a Newspack Custom HTML / iframe block.
-->
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Maine Gas Prices</title>
<style>
  :root { --bdn-red: #d6232a; --ink: #1a1a1a; --muted: #666; --bg: #fff; --line: #e5e7eb; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font: 16px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; color: var(--ink); background: var(--bg); padding: 1rem; }
  #widget { max-width: 720px; margin: 0 auto; }
  .cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: .75rem; margin-bottom: 1rem; }
  @media (max-width: 560px) { .cards { grid-template-columns: 1fr; } }
  .card { border: 1px solid var(--line); border-radius: 8px; padding: 1rem; }
  .card .label { font-size: .8rem; color: var(--muted); text-transform: uppercase; letter-spacing: .03em; margin-bottom: .25rem; }
  .card .name { font-weight: 600; font-size: 1rem; }
  .card .price { font-size: 2rem; font-weight: 700; line-height: 1.1; margin: .25rem 0; }
  .card .delta { font-size: .85rem; color: var(--muted); }
  .card.center .price { color: var(--bdn-red); }
  .trend { font-size: .85rem; color: var(--muted); margin-top: .25rem; }
  #map { width: 100%; height: 360px; }
  #map svg { width: 100%; height: 100%; }
  .county { fill: #ddd; stroke: #fff; stroke-width: 1; cursor: pointer; }
  .county:hover { stroke: #000; stroke-width: 2; }
  .tooltip { position: absolute; background: #1a1a1a; color: #fff; padding: .35rem .55rem; border-radius: 4px; font-size: .85rem; pointer-events: none; opacity: 0; transition: opacity .1s; }
  footer { font-size: .8rem; color: var(--muted); margin-top: .75rem; }
  .stale { background: #fff7d6; border: 1px solid #f0c14b; padding: .5rem .75rem; border-radius: 6px; margin-bottom: 1rem; font-size: .9rem; }
</style>
</head>
<body>
<div id="widget">
  <div id="loading">Loading…</div>
  <div id="content" hidden>
    <div id="stale" class="stale" hidden></div>
    <div class="cards">
      <div class="card cheapest"><div class="label">Cheapest county</div><div class="name" id="cheap-name">—</div><div class="price" id="cheap-price">—</div><div class="delta" id="cheap-delta">—</div></div>
      <div class="card center"><div class="label">Maine average</div><div class="price" id="state-price">—</div><div class="delta" id="state-vs-us">—</div><div class="trend" id="state-trend">—</div></div>
      <div class="card expensive"><div class="label">Most expensive county</div><div class="name" id="exp-name">—</div><div class="price" id="exp-price">—</div><div class="delta" id="exp-delta">—</div></div>
    </div>
    <div id="map"></div>
    <footer id="footer">—</footer>
  </div>
  <div id="error" hidden>Couldn't load price data. Check back soon.</div>
</div>
<div class="tooltip" id="tooltip"></div>

<script>
const DATA_URL  = "data/prices.json";
const GEO_URL   = "data/maine-counties.geo.json";
const STALE_HRS = 72;

async function load() {
  try {
    const [prices, geo] = await Promise.all([
      fetch(DATA_URL).then(r => { if (!r.ok) throw new Error("prices"); return r.json(); }),
      fetch(GEO_URL).then(r => { if (!r.ok) throw new Error("geo"); return r.json(); }),
    ]);
    document.getElementById("loading").hidden = true;
    document.getElementById("content").hidden = false;
    render(prices, geo);
  } catch (e) {
    document.getElementById("loading").hidden = true;
    document.getElementById("error").hidden = false;
    console.error(e);
  }
}

function render(p, geo) { /* filled in next task */ }
load();
</script>
</body>
</html>
```

**Step 2: Local manual sanity check**

```bash
cd maine-gas-prices
# After Task 11, run scraper against fixtures to populate data/prices.json:
python3 -c "
from fetch_prices import build_payload
import json, os
os.makedirs('data', exist_ok=True)
html = open('tests/fixtures/aaa-happy.html').read()
cfg  = open('tests/fixtures/aaa-map-cfg-happy.js').read()
json.dump(build_payload(html, cfg), open('data/prices.json','w'), indent=2)
"
python3 -m http.server 8000
```

Open http://localhost:8000/embed.html — should briefly show "Loading…" then "Couldn't load price data" because `render` is empty (or empty content if both fetches succeed). That's the expected pre-render state.

**Step 3: Commit** — `feat(maine-gas-prices): embed.html scaffold + data fetch`

---

## Task 15: `embed.html` — render stat cards + trend microcopy

**Files:**
- Modify: `maine-gas-prices/embed.html`

**Step 1: Implement `render(p, geo)` for the cards**

```javascript
function fmt(p) { return "$" + p.toFixed(2); }
function delta(a, b) {
  const c = Math.round((a - b) * 100);
  if (c === 0) return "same as state avg";
  const sign = c > 0 ? "↑" : "↓";
  return `${sign} ${Math.abs(c)}¢ ${c > 0 ? "above" : "below"} state avg`;
}
function trendLine(state) {
  const t = state.trend, base = state.avg_regular;
  const fmtDir = (label, prev) => {
    const c = Math.round((base - prev) * 100);
    if (c === 0) return `Even with ${label}`;
    return `${c > 0 ? "Up" : "Down"} ${Math.abs(c)}¢ from ${label}`;
  };
  return [fmtDir("last week", t.week_ago), fmtDir("a year ago", t.year_ago)].join(" · ");
}

function render(p, geo) {
  // Cheapest
  document.getElementById("cheap-name").textContent  = p.cheapest.name + " County";
  document.getElementById("cheap-price").textContent = fmt(p.cheapest.avg_regular);
  document.getElementById("cheap-delta").textContent = delta(p.cheapest.avg_regular, p.state.avg_regular);
  // Most expensive
  document.getElementById("exp-name").textContent  = p.most_expensive.name + " County";
  document.getElementById("exp-price").textContent = fmt(p.most_expensive.avg_regular);
  document.getElementById("exp-delta").textContent = delta(p.most_expensive.avg_regular, p.state.avg_regular);
  // Maine vs national + trend
  document.getElementById("state-price").textContent = fmt(p.state.avg_regular);
  const usDiff = Math.round((p.state.avg_regular - p.national.avg_regular) * 100);
  document.getElementById("state-vs-us").textContent =
    usDiff === 0 ? "Same as US avg" : `${Math.abs(usDiff)}¢ ${usDiff > 0 ? "above" : "below"} US avg ${fmt(p.national.avg_regular)}`;
  document.getElementById("state-trend").textContent = trendLine(p.state);
  // Stale-data warning
  const updated = new Date(p.updated);
  const ageHrs = (Date.now() - updated.getTime()) / 36e5;
  if (ageHrs > STALE_HRS) {
    const el = document.getElementById("stale");
    el.hidden = false;
    el.textContent = `Prices last updated ${updated.toLocaleDateString("en-US",{month:"long",day:"numeric",year:"numeric"})}.`;
  }
  // Footer
  document.getElementById("footer").textContent =
    `Source: AAA Maine · Updated ${updated.toLocaleDateString("en-US",{month:"long",day:"numeric",year:"numeric"})} · Prices for regular gasoline.`;
  // Map
  renderMap(p, geo);
}

function renderMap(p, geo) { /* next task */ }
```

**Step 2: Reload `embed.html` in browser**

Cards should populate with real prices, trend microcopy reads sensibly, footer shows date.

**Step 3: Commit** — `feat(maine-gas-prices): render stat cards and trend`

---

## Task 16: `embed.html` — render choropleth + tooltip

**Files:**
- Modify: `maine-gas-prices/embed.html`

**Step 1: Implement `renderMap`**

```javascript
function renderMap(p, geo) {
  const priceBy = Object.fromEntries(p.counties.map(c => [c.fips, c.avg_regular]));
  const prices = p.counties.map(c => c.avg_regular);
  const min = Math.min(...prices), max = Math.max(...prices);
  const colorAt = v => {
    const t = (v - min) / (max - min || 1);
    // Green (low) -> red (high)
    const r = Math.round(60 + t * 195);
    const g = Math.round(160 - t * 110);
    const b = 60;
    return `rgb(${r},${g},${b})`;
  };

  // Compute bounding box from features
  const features = geo.features;
  let minX=Infinity,minY=Infinity,maxX=-Infinity,maxY=-Infinity;
  const eachCoord = (coords, fn) => {
    if (typeof coords[0] === "number") fn(coords);
    else coords.forEach(c => eachCoord(c, fn));
  };
  features.forEach(f => eachCoord(f.geometry.coordinates, ([x,y]) => {
    if (x<minX) minX=x; if (y<minY) minY=y; if (x>maxX) maxX=x; if (y>maxY) maxY=y;
  }));
  const W = 600, H = 360, pad = 10;
  const sx = (W - 2*pad) / (maxX - minX);
  const sy = (H - 2*pad) / (maxY - minY);
  const s = Math.min(sx, sy);
  // Maine: north is up, longitude west is more negative — flip Y
  const project = ([x,y]) => [pad + (x-minX)*s, H - pad - (y-minY)*s];

  const ringPath = ring => "M" + ring.map(project).map(p => p.join(",")).join("L") + "Z";
  const featurePath = f => {
    const c = f.geometry.coordinates;
    if (f.geometry.type === "Polygon") return c.map(ringPath).join(" ");
    if (f.geometry.type === "MultiPolygon") return c.map(poly => poly.map(ringPath).join(" ")).join(" ");
    return "";
  };
  const fipsOf = f => (f.properties.fips || f.properties.GEOID || f.properties.STATE + f.properties.COUNTY || "");
  const nameOf = f => (f.properties.name || f.properties.NAME || "Unknown");

  const svg = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Map of Maine showing average regular gas prices by county">
    ${features.map(f => {
      const fips = fipsOf(f), name = nameOf(f);
      const price = priceBy[fips];
      const fill = price != null ? colorAt(price) : "#ddd";
      return `<path class="county" d="${featurePath(f)}" fill="${fill}" data-name="${name}" data-price="${price != null ? fmt(price) : "—"}"></path>`;
    }).join("")}
  </svg>`;
  document.getElementById("map").innerHTML = svg;

  const tip = document.getElementById("tooltip");
  document.querySelectorAll(".county").forEach(el => {
    const move = e => {
      tip.style.opacity = "1";
      tip.style.left = (e.pageX + 12) + "px";
      tip.style.top  = (e.pageY + 12) + "px";
      tip.textContent = `${el.dataset.name} County: ${el.dataset.price}`;
    };
    el.addEventListener("mousemove", move);
    el.addEventListener("touchstart", move);
    el.addEventListener("mouseleave", () => { tip.style.opacity = "0"; });
  });
}
```

**Step 2: Reload and verify visually**

- 16 county shapes render
- Each county is colored on a green→red scale
- Hovering a county shows a tooltip with name + price
- No JS errors in console

**Step 3: Commit** — `feat(maine-gas-prices): render Maine choropleth with tooltip`

---

## Task 17: `index.html` — standalone preview page

**Files:**
- Create: `maine-gas-prices/index.html`

**Step 1: Write a minimal landing page that iframes the widget**

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Maine Gas Prices Widget — Preview</title>
<style>
  body { font: 16px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; max-width: 800px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }
  iframe { border: 0; width: 100%; min-height: 700px; }
  pre { background: #f4f4f4; padding: .75rem; border-radius: 6px; overflow-x: auto; }
</style>
</head>
<body>
<h1>Maine Gas Prices — Preview</h1>
<p>This is the preview page for the embeddable widget. Source: AAA Maine.</p>
<iframe src="embed.html" title="Maine gas prices"></iframe>
<h2>Embed code</h2>
<pre>&lt;iframe src="https://&lt;your-pages-domain&gt;/embed.html" width="100%" height="700" frameborder="0"&gt;&lt;/iframe&gt;</pre>
</body>
</html>
```

**Step 2: Reload http://localhost:8000/ — should show preview page with widget embedded.**

**Step 3: Commit** — `feat(maine-gas-prices): standalone index/preview page`

---

## Task 18: Stale-data fixture + Playwright smoke test

**Files:**
- Create: `maine-gas-prices/tests/fixtures/prices-fresh.json`
- Create: `maine-gas-prices/tests/fixtures/prices-stale.json`
- Create: `maine-gas-prices/tests/test_embed.py`

**Step 1: Generate fixtures**

```bash
cd maine-gas-prices
# Fresh: today
python3 -c "
from fetch_prices import build_payload
import json
html = open('tests/fixtures/aaa-happy.html').read()
cfg  = open('tests/fixtures/aaa-map-cfg-happy.js').read()
p = build_payload(html, cfg)
json.dump(p, open('tests/fixtures/prices-fresh.json','w'), indent=2)
"
# Stale: re-stamp updated to 5 days ago
python3 -c "
import json, datetime
p = json.load(open('tests/fixtures/prices-fresh.json'))
p['updated'] = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=5)).strftime('%Y-%m-%dT%H:%M:%SZ')
json.dump(p, open('tests/fixtures/prices-stale.json','w'), indent=2)
"
```

**Step 2: Write Playwright test**

```python
# tests/test_embed.py
import http.server, json, os, shutil, socketserver, subprocess, threading, time
import pytest
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class Server:
    def __init__(self, port=8765):
        self.port = port
        os.chdir(ROOT)
        Handler = http.server.SimpleHTTPRequestHandler
        self.httpd = socketserver.TCPServer(("127.0.0.1", port), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
    def start(self): self.thread.start(); time.sleep(0.2)
    def stop(self): self.httpd.shutdown()

@pytest.fixture(scope="module")
def server():
    srv = Server(); srv.start()
    yield f"http://127.0.0.1:{srv.port}"
    srv.stop()

def _swap_data(src):
    shutil.copy(os.path.join(ROOT, "tests", "fixtures", src),
                os.path.join(ROOT, "data", "prices.json"))

def test_embed_renders_cards_and_map(server):
    _swap_data("prices-fresh.json")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(f"{server}/embed.html")
        page.wait_for_selector("#content:not([hidden])", timeout=5000)
        # Three cards visible
        assert page.locator(".card").count() == 3
        # Cheapest card has a $ price
        assert "$" in page.locator(".cheapest .price").inner_text()
        # 16 county paths in the SVG
        page.wait_for_selector(".county")
        assert page.locator(".county").count() == 16
        # Stale warning hidden
        assert page.locator("#stale").is_hidden()
        browser.close()

def test_embed_shows_stale_warning(server):
    _swap_data("prices-stale.json")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(f"{server}/embed.html")
        page.wait_for_selector("#stale:not([hidden])", timeout=5000)
        assert "last updated" in page.locator("#stale").inner_text().lower()
        browser.close()
```

**Step 3: Install Playwright browsers + run tests**

```bash
pip install -r requirements-dev.txt
python3 -m playwright install chromium
pytest tests/test_embed.py -v
```

Expected: both tests PASS. If the second fails because the page already loaded the fresh fixture, add a `?v=stale` cachebuster param to the URL in the second test.

**Step 4: Commit** — `test(maine-gas-prices): playwright smoke test for embed`

---

## Task 19: Manual visual QA + screenshots

**Files:**
- Create: `maine-gas-prices/docs/screenshots/embed-fresh.png`
- Create: `maine-gas-prices/docs/screenshots/embed-stale.png`

**Step 1: Capture screenshots with Playwright**

```bash
cd maine-gas-prices
mkdir -p docs/screenshots
python3 -m http.server 8000 &
SERVER_PID=$!
sleep 1
python3 - <<'PY'
from playwright.sync_api import sync_playwright
import shutil
for label in ("fresh", "stale"):
    shutil.copy(f"tests/fixtures/prices-{label}.json", "data/prices.json")
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page(viewport={"width": 760, "height": 800})
        page.goto("http://127.0.0.1:8000/embed.html")
        page.wait_for_selector("#content:not([hidden])")
        page.screenshot(path=f"docs/screenshots/embed-{label}.png", full_page=True)
        b.close()
PY
kill $SERVER_PID
```

**Step 2: Visually inspect both screenshots**

Verify:
- Fresh: three cards readable, map shows 16 distinct counties, no stale warning
- Stale: yellow warning band shows above cards, otherwise identical
- BDN red appears on the center card price
- Mobile breakpoint: open http://127.0.0.1:8000/embed.html at 400px wide and confirm cards stack

**Step 3: Restore fresh data so the repo doesn't ship the stale fixture as live data**

```bash
cp tests/fixtures/prices-fresh.json data/prices.json
```

**Step 4: Commit** — `docs(maine-gas-prices): screenshots + final visual QA`

---

## Task 20: Final review and push

**Step 1: Run the whole test suite**

```bash
cd maine-gas-prices
pytest -v
```

Expected: all tests pass.

**Step 2: Tree check**

```bash
find . -type f -not -path "./.git/*" -not -path "./.pytest_cache/*" -not -path "./__pycache__/*" -not -path "./node_modules/*" | sort
```

Expected files match the "Repository layout (target)" section at the top of this plan.

**Step 3: Push**

```bash
git push
```

If push fails because of the parent sandbox repo's misconfigured remote, document the failure mode in `docs/plans/` and surface to Dan.

**Step 4: Manual GitHub Actions trigger**

Once on GitHub: Actions tab → "Fetch Maine gas prices" → "Run workflow" → confirm the run succeeds and a `chore(maine-gas-prices): daily price update` commit lands.

**Step 5: Enable GitHub Pages**

Repo settings → Pages → deploy from branch (root or `/docs` depending on host repo layout). Confirm `embed.html` is reachable.

**Step 6: Verify embed in production**

Drop the iframe snippet into a Newspack Custom HTML block on a draft BDN post. Preview, confirm widget renders identically to local.

---

## Out-of-scope reminders (do NOT implement)

- Station-level prices
- Diesel / mid-grade / premium grades
- Time-series chart beyond the four trend points
- Reader-submitted prices
- Multi-state comparison
