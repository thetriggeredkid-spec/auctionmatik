"""Tests for dashboard.mapper.calibration() — segment aggregation over feedback rows."""

import dashboard.mapper as M


class _Cur:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, *a, **k):
        pass

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class _Conn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self, **k):
        return _Cur(self._rows)

    def close(self):
        pass


def _row(**kw):
    base = dict(
        contract="0",
        year=2019,
        make="FORD",
        model="F-150",
        engine_verdict="BID",
        engine_value=None,
        engine_max_bid=None,
        actual_sale_price=None,
        corrected_value=None,
        corrected_max_bid=None,
        verdict_correct=None,
        engine_mode=None,
        notes="",
        updated_at=None,
    )
    base.update(kw)
    return base


def test_calibration_splits_retail_and_wholesale_tracks():
    rows = [
        # human retail correction (deep) → retail track (value + bid)
        _row(
            contract="1",
            make="HYUNDAI",
            engine_mode="deep",
            engine_value=850000,
            corrected_value=980000,
            engine_max_bid=550000,
            corrected_max_bid=650000,
            verdict_correct=False,
            notes="manual",
        ),
        # auto-imported outcomes → wholesale track (bid vs hammer price), never the retail track
        _row(
            contract="2",
            make="FORD",
            engine_mode="auto",
            engine_max_bid=900000,
            actual_sale_price=1000000,
            notes="[auto]",
        ),
        _row(
            contract="3",
            make="FORD",
            engine_mode="auto",
            engine_max_bid=1200000,
            actual_sale_price=1000000,
            notes="[auto]",
        ),
    ]
    cal = M.calibration(_Conn(rows))
    assert cal["total"] == 3

    # retail track: only the human correction; value + bid each n=1
    assert cal["retail"]["total"] == 1
    assert cal["retail"]["value"]["n"] == 1
    assert cal["retail"]["bid"]["n"] == 1
    assert cal["retail"]["verdictN"] == 1
    assert {m["mode"]: m["n"] for m in cal["retail"]["modes"]} == {"deep": 1}

    # wholesale track: the two auto rows; FORD segment with n=2, no retail value error
    assert cal["wholesale"]["total"] == 2
    assert cal["wholesale"]["bid"]["n"] == 2
    ford = next(s for s in cal["wholesale"]["byMake"] if s["key"] == "FORD")
    assert ford["n"] == 2
    # tracks don't pollute each other: HYUNDAI is only in the retail segments
    assert not any(s["key"] == "HYUNDAI" for s in cal["wholesale"]["byMake"])

    # samples carry their track + mode tags
    s1 = next(s for s in cal["samples"] if s["contract"] == "1")
    assert s1["track"] == "retail" and s1["engineMode"] == "deep"


def test_calibration_empty():
    cal = M.calibration(_Conn([]))
    assert cal["total"] == 0
    assert cal["retail"]["value"]["n"] == 0 and cal["retail"]["bid"]["n"] == 0
    assert cal["wholesale"]["bid"]["n"] == 0
    assert cal["retail"]["byMake"] == [] and cal["wholesale"]["byMake"] == []
