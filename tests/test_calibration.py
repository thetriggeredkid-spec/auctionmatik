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
    base = dict(contract="0", year=2019, make="FORD", model="F-150", engine_verdict="BID",
                engine_value=None, engine_max_bid=None, actual_sale_price=None,
                corrected_value=None, corrected_max_bid=None, verdict_correct=None,
                notes="", updated_at=None)
    base.update(kw)
    return base


def test_calibration_segments_include_auto_bid_rows():
    rows = [
        # human retail correction → value track
        _row(contract="1", make="HYUNDAI", engine_value=850000, corrected_value=980000,
             engine_max_bid=550000, corrected_max_bid=650000, verdict_correct=False, notes="manual"),
        # auto-imported outcome → bid track only (no corrected_value)
        _row(contract="2", make="FORD", engine_max_bid=900000, actual_sale_price=1000000, notes="[auto]"),
        _row(contract="3", make="FORD", engine_max_bid=1200000, actual_sale_price=1000000, notes="[auto]"),
    ]
    cal = M.calibration(_Conn(rows))
    assert cal["total"] == 3
    # value track = 1 (only the human row has corrected_value)
    assert cal["value"]["n"] == 1
    # bid track = 3 (human row has corrected_max_bid; both auto rows have actual_sale_price)
    assert cal["bid"]["n"] == 3
    # segments now include the auto bid rows: FORD should appear with n=2
    ford = next(s for s in cal["byMake"] if s["key"] == "FORD")
    assert ford["n"] == 2
    # verdict accuracy from the one row that set it
    assert cal["verdictN"] == 1


def test_calibration_empty():
    cal = M.calibration(_Conn([]))
    assert cal["total"] == 0
    assert cal["value"]["n"] == 0 and cal["bid"]["n"] == 0
    assert cal["byMake"] == []
