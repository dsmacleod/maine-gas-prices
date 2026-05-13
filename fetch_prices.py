import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

AAA_HTML_URL    = "https://gasprices.aaa.com/?state=ME"
AAA_MAP_CFG_URL = "https://gasprices.aaa.com/index.php?premiumhtml5map_js_data=true&map_id=21"
OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "prices.json")

ME_FIPS = {
    "Androscoggin": "23001", "Aroostook": "23003", "Cumberland": "23005",
    "Franklin": "23007", "Hancock": "23009", "Kennebec": "23011",
    "Knox": "23013", "Lincoln": "23015", "Oxford": "23017",
    "Penobscot": "23019", "Piscataquis": "23021", "Sagadahoc": "23023",
    "Somerset": "23025", "Waldo": "23027", "Washington": "23029", "York": "23031",
}

def parse_state_average(html: str) -> float:
    """Extract Maine's regular-gas state average from the AAA state-page HTML.

    Target markup (first table on the state page):
        <td>Current Avg.</td>
        <td>$4.539</td>   <-- regular (first $ after the label)
    """
    m = re.search(r'Current Avg\.\s*</td>\s*<td>\s*\$(\d+\.\d{2,3})', html, re.DOTALL)
    if not m:
        raise ValueError("Could not locate Maine state average in AAA HTML")
    return float(m.group(1))

def parse_national_average(html: str) -> float:
    """Extract the US national average from the AAA state-page HTML.

    Target markup:
        <p>Today's AAA<br />
        National Average </p>
        <p class="numb">
          $4.546 ...
    """
    m = re.search(
        r'National Average\s*</p>\s*<p[^>]*class="numb"[^>]*>\s*\$(\d+\.\d{2,3})',
        html, re.DOTALL,
    )
    if not m:
        raise ValueError("Could not locate national average in AAA HTML")
    return float(m.group(1))

def parse_state_trend(html: str) -> dict:
    """Pull the Week/Month/Year-ago regular-gas averages from the state trend table.

    Target markup (each in the first such table):
        <td>Week Ago Avg.</td>
        <td>$4.323</td>   <-- regular (first $ after the label)
    """
    keys = [("week_ago", "Week Ago Avg."), ("month_ago", "Month Ago Avg."), ("year_ago", "Year Ago Avg.")]
    out = {}
    for k, label in keys:
        m = re.search(
            rf'{re.escape(label)}\s*</td>\s*<td>\s*\$(\d+\.\d{{2,3}})',
            html, re.DOTALL,
        )
        if not m:
            raise ValueError(f"Could not locate '{label}' in AAA HTML")
        out[k] = float(m.group(1))
    return out

def parse_counties(map_cfg_js: str) -> list:
    """Extract 16 Maine county prices from AAA's map-config JS blob.

    The config has a line like:
        map_data : {"st1":{"id":1,"name":"Androscoggin","comment":"$4.561",...},
                    "st2":{"id":2,"name":"Aroostook","comment":"$4.522",...}, ...}
    The 'comment' field holds the regular-gas price.
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

def validate_payload(p: dict) -> None:
    if len(p.get("counties", [])) != 16:
        raise ValueError("Expected exactly 16 counties")
    for c in p["counties"]:
        if not (1.0 < c["avg_regular"] < 10.0):
            raise ValueError(f"County {c['name']} price out of range: {c['avg_regular']}")
    for key in ("state", "national"):
        if not (1.0 < p[key]["avg_regular"] < 10.0):
            raise ValueError(f"{key} avg out of range")

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
                time.sleep(2 ** i)
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
