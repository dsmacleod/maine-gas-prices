import os
import pytest
from fetch_prices import parse_state_average, parse_national_average, parse_state_trend, parse_counties, build_payload, validate_payload

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

def _load(name):
    with open(os.path.join(FIXTURES, name)) as f:
        return f.read()

def test_parse_state_average_happy():
    html = _load("aaa-happy.html")
    avg = parse_state_average(html)
    assert isinstance(avg, float)
    assert 1.0 < avg < 10.0

def test_parse_national_average_happy():
    html = _load("aaa-happy.html")
    avg = parse_national_average(html)
    assert isinstance(avg, float)
    assert 1.0 < avg < 10.0

def test_parse_state_trend_happy():
    html = _load("aaa-happy.html")
    trend = parse_state_trend(html)
    assert set(trend.keys()) == {"week_ago", "month_ago", "year_ago"}
    for v in trend.values():
        assert 1.0 < v < 10.0

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
    assert payload["updated"].endswith("Z")

def _good_payload():
    html = _load("aaa-happy.html")
    cfg  = _load("aaa-map-cfg-happy.js")
    return build_payload(html, cfg)

def test_validate_payload_accepts_good():
    validate_payload(_good_payload())  # should not raise

def test_validate_payload_rejects_missing_county():
    payload = _good_payload()
    payload["counties"] = payload["counties"][:15]
    with pytest.raises(ValueError, match="16 counties"):
        validate_payload(payload)

def test_validate_payload_rejects_absurd_price():
    payload = _good_payload()
    payload["counties"][0]["avg_regular"] = 99.99
    with pytest.raises(ValueError, match="out of range"):
        validate_payload(payload)

def test_parse_counties_missing_raises():
    js = _load("aaa-map-cfg-missing-county.js")
    with pytest.raises(ValueError, match="Piscataquis"):
        parse_counties(js)

def test_parse_state_average_structure_changed_raises():
    html = _load("aaa-structure-changed.html")
    with pytest.raises(ValueError, match="state average"):
        parse_state_average(html)
