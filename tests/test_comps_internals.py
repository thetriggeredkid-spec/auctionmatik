"""Characterization tests for engine/comps.py — scoring, tiering, comp pool."""
from datetime import date, timedelta

from engine import comps


def test_recency_weight_bands():
    assert comps._recency_weight(date.today() - timedelta(days=10)) == 3.0
    assert comps._recency_weight(date.today() - timedelta(days=60)) == 1.5
    assert comps._recency_weight(date.today() - timedelta(days=200)) == 1.0
    assert comps._recency_weight(None) == 1.0  # _days_ago(None) == 9999 → oldest band


def test_weighted_median():
    assert comps._weighted_median([(1000, 1.0), (2000, 1.0), (3000, 1.0)]) == 2000
    assert comps._weighted_median([]) == 0
    # weight pulls the median toward the heavy value
    assert comps._weighted_median([(1000, 0.1), (5000, 10.0)]) == 5000


def test_comp_tier_clean_distressed_unknown():
    clean = {"declarations": "", "condition_notes": "clean unit, no accidents reported, well kept",
             "seller_type": "Dealer"}
    assert comps._comp_tier(clean) == "clean"
    # frame damage in notes → distressed
    assert comps._comp_tier({"declarations": "", "condition_notes": "frame damage present",
                             "seller_type": ""}) == "distressed"
    # no data to classify → unknown
    assert comps._comp_tier({"declarations": "", "condition_notes": "", "seller_type": ""}) == "unknown"


def test_finance_repo_comp_is_not_distressed():
    # FR is a same-day release at Regal, not a duress sale — must NOT be tiered distressed
    fr = {"declarations": "FR", "condition_notes": "", "seller_type": ""}
    assert comps._comp_tier(fr) != "distressed"


def test_similarity_identical_is_max():
    v = {"trim": "XLT", "year": 2019, "odometer_km": 100000, "make": "FORD", "model": "F-150"}
    same = comps._similarity_score(v, dict(v, odometer_km=102000))
    diff = comps._similarity_score(v, {"trim": "LARIAT", "year": 2016, "odometer_km": 200000,
                                       "make": "FORD", "model": "F-150"})
    assert same == 1.0
    assert diff < same


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, *a, **k):
        pass

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self, **k):
        return _FakeCursor(self._rows)

    def close(self):
        pass


def _rows(n):
    return [{
        "id": i, "regal_id": str(i), "contract": str(i), "year": 2019, "make": "FORD",
        "model": "F-150", "trim": "XLT", "body_style": None, "driveline": "4WD",
        "odometer_km": 100000 + i * 5000, "sale_price": 2_000_000 + i * 10_000,
        "sold_date": date.today() - timedelta(days=20 + i), "seller_type": "Dealer",
        "declarations": "", "condition_notes": "clean unit, no accidents reported, well kept",
        "options_text": "", "vin": None, "color": None, "engine": None, "transmission": None,
    } for i in range(n)]


def test_get_comp_pool_with_canned_rows():
    res = comps.get_comp_pool(
        {"year": 2019, "make": "FORD", "model": "F-150", "driveline": "4WD", "odometer_km": 110000},
        conn=_FakeConn(_rows(12)),
    )
    assert res["comp_count"] == 12
    assert res["clean_count"] == 12
    assert res["base_median"] > 0
    assert res["confidence"] in ("high", "medium", "low")
    assert "clean" in res["tier_stats"]
    assert isinstance(res["comp_list"], list)


def test_get_comp_pool_exclude_ids_prevents_self_comping():
    rows = _rows(12)
    target_id = rows[0]["id"]
    res = comps.get_comp_pool(
        {"year": 2019, "make": "FORD", "model": "F-150", "driveline": "4WD", "odometer_km": 110000},
        conn=_FakeConn(rows), exclude_ids={target_id},
    )
    assert res["comp_count"] == 11  # the excluded subject is gone
    assert all(c["id"] != target_id for c in res["comp_list"])


def test_get_comp_pool_empty():
    res = comps.get_comp_pool(
        {"year": 2019, "make": "FORD", "model": "F-150", "driveline": "4WD", "odometer_km": 110000},
        conn=_FakeConn([]),
    )
    assert res["comp_count"] == 0
    assert res["confidence"] == "low"
    assert res["base_median"] is None
