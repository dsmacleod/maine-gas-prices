# Maine Gas Prices Widget — Design

**Date:** 2026-05-08
**Status:** Approved, ready for implementation planning
**Owner:** Dan MacLeod (BDN)

## Goal

A small, evergreen interactive widget embedded on the Bangor Daily News site that shows:

1. The cheapest county in Maine for regular gasoline
2. The most expensive county in Maine
3. Maine's average price compared with the national average, plus week/month/year trends

The widget launches with a story but stays evergreen — it auto-updates daily and remains correct months later without intervention.

## Data source

- **AAA Maine state page:** https://gasprices.aaa.com/?state=ME
- **Coverage:** state average, national average, all 16 Maine counties, trend deltas (yesterday / week / month / year)
- **Update cadence:** AAA refreshes around 5am ET daily
- **Grade:** regular gasoline only (matches AAA's headline figure and reader expectations)
- **Why not station-level:** GasBuddy is the only credible station-level source. Their public site blocks scrapers and their Business API requires a paid partnership. County-level is the realistic, sustainable choice.

## Architecture

```
GitHub Actions cron (daily ~7am ET)
    │
    ▼
fetch-prices.py  ──── scrapes gasprices.aaa.com/?state=ME
    │
    ▼
data/prices.json  ──── committed back to repo
    │
    ▼
GitHub Pages serves: index.html, embed.html, JS, JSON, GeoJSON
    │
    ▼
BDN site embeds <iframe src="…/embed.html">
```

No server, no database, no API keys. Mirrors the existing `flagg-vs-lebron` pattern in this sandbox.

## Data shape

`data/prices.json` is rewritten on every successful scrape:

```json
{
  "updated": "2026-05-08T11:02:00Z",
  "state": {
    "name": "Maine",
    "avg_regular": 3.42,
    "trend": {
      "week_ago": 3.45,
      "month_ago": 3.51,
      "year_ago": 3.30
    }
  },
  "national": { "avg_regular": 3.15 },
  "counties": [
    { "name": "Aroostook", "fips": "23003", "avg_regular": 3.21 },
    { "name": "Hancock",   "fips": "23009", "avg_regular": 3.58 }
  ],
  "cheapest":       { "name": "Aroostook", "avg_regular": 3.21 },
  "most_expensive": { "name": "Hancock",   "avg_regular": 3.58 }
}
```

- Cheapest / most expensive are precomputed in Python so the front-end never sorts.
- FIPS codes are included so the choropleth map joins cleanly to a county GeoJSON.

## Visual layout

Mobile-first. No framework. System font stack. Black / white / BDN-red palette.

**Top — three stat cards (stack on mobile):**
- Cheapest county: name, price, "↓ Xc below state avg"
- Maine vs national: big "$3.42", "Xc above/below US avg", trend microcopy ("Down 3c from last week · Up 12c from a year ago")
- Most expensive county: name, price, "↑ Xc above state avg"

**Middle — Maine choropleth:**
- SVG-based, hand-rendered or D3-geo (Leaflet rejected: 40KB+ overhead, tile attribution clutter, overkill for a single state outline)
- Simplified county GeoJSON, target ~30KB
- Sequential green-to-red color scale anchored to state min/max so contrast stays readable when the spread is small
- Hover/tap a county → tooltip with name and current price

**Bottom — footer:**
- "Source: AAA Maine · Updated [date] · Prices for regular gasoline."

**Page weight target:** under 80KB total including GeoJSON.

## Error handling

| Failure mode | Behavior |
|---|---|
| AAA page structure changes | Scraper raises, Actions job fails, previous `prices.json` stays in place. GitHub default failure email fires. Widget keeps showing yesterday's data. |
| AAA temporarily down / 5xx | Scraper retries 3x with exponential backoff, exits cleanly without committing. |
| Partial data (e.g. only 14 of 16 counties) | Treated as failure — don't overwrite. Skip a day rather than publish a half-map. |
| Stale data | Front-end checks `updated` timestamp; if >72 hours old, shows "Prices last updated [date]" warning under the cards. |
| Front-end JSON fetch fails | Cards show "—", map renders gray, no JS errors, layout intact. |

The scraper logs to the Actions run output so a failed selector is immediately visible.

## Testing

- **Scraper unit tests** — fixture HTML files captured from AAA: happy path, missing-county case, structure-changed case. Tests assert correct JSON output or loud failure on malformed fixtures. Run on every push.
- **Schema validation** — after every scrape, validate the JSON: 16 counties present, all prices numeric and in [1, 10], timestamp parseable. Fail blocks the commit.
- **Front-end smoke test** — single Playwright test loading `embed.html` against a fixture JSON. Asserts three cards render, map has 16 county paths, "updated" timestamp shows.
- **Manual visual check** — capture screenshots of `embed.html` against fresh data and stale-data fixture before merging.
- **No end-to-end against live AAA** — flaky and unnecessary; fixture-based parser tests cover the same surface reliably.

## Out of scope (v1)

- Station-level prices
- Diesel, mid-grade, premium grades
- Historical chart / time series beyond the four trend points
- Reader-submitted prices
- New England / multi-state comparison
