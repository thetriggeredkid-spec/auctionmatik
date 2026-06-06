"""Tests for collector.vin_decode normalization + evaluate.apply_vin_decode gap-fill."""

import evaluate
from collector import vin_decode as VD


def test_norm_driveline():
    assert VD._norm_driveline("4WD/4-Wheel Drive") == "4WD"
    assert VD._norm_driveline("AWD/All-Wheel Drive") == "AWD"
    assert VD._norm_driveline("FWD/Front-Wheel Drive") == "FWD"
    assert VD._norm_driveline("RWD/Rear-Wheel Drive") == "RWD"
    assert VD._norm_driveline("") is None


def test_norm_cab_and_engine():
    assert VD._norm_cab("Crew/Super Crew") == "crew"
    assert VD._norm_cab("Extended/Double Cab") == "ext"
    assert VD._norm_cab("Regular Cab") == "reg"
    assert (
        VD._engine_str(
            {
                "DisplacementL": "3.5000",
                "EngineCylinders": "6",
                "EngineConfiguration": "V-Shaped",
            }
        )
        == "3.5L V6"
    )
    assert (
        VD._engine_str(
            {
                "DisplacementL": "2.0",
                "EngineCylinders": "4",
                "EngineConfiguration": "Inline",
            }
        )
        == "2.0L I4"
    )


def test_normalize_drops_empty_and_uppercases():
    res = {
        "ModelYear": "2019",
        "Make": "Ford",
        "Model": "F-150",
        "Trim": "",
        "Series": "Lariat",
        "DriveType": "4WD/4-Wheel Drive",
        "BodyCabType": "Crew/Super Crew",
        "FuelTypePrimary": "Gasoline",
        "DisplacementL": "5.0",
        "EngineCylinders": "8",
        "EngineConfiguration": "V-Shaped",
        "BedType": "",
        "TransmissionStyle": "Not Applicable",
    }
    out = VD._normalize(res)
    assert out["year"] == 2019 and out["make"] == "FORD"
    assert out["trim"] == "Lariat"  # falls back to Series when Trim blank
    assert (
        out["driveline"] == "4WD"
        and out["cab"] == "crew"
        and out["engine"] == "5.0L V8"
    )
    assert (
        out["bed"] is None and out["transmission"] is None
    )  # "" / "Not Applicable" → None


def test_apply_vin_decode_gap_fills_only_blanks(monkeypatch):
    # apply_vin_decode does `from collector.vin_decode import decode_vin` at call time,
    # so patching the module attribute stubs out the network.
    import collector.vin_decode as vd

    monkeypatch.setattr(
        vd,
        "decode_vin",
        lambda vin, conn=None, allow_fetch=True: {
            "trim": "LARIAT",
            "driveline": "4WD",
            "engine": "5.0L V8",
            "cab": "crew",
        },
    )
    vehicle = {
        "vin": "1FTEW1EG0JFA00000",
        "trim": "XLT",
        "driveline": None,
        "engine": None,
        "cab": None,
    }
    evaluate.apply_vin_decode(conn=None, vehicle=vehicle)
    assert vehicle["trim"] == "XLT"  # present scrape value preserved
    assert vehicle["driveline"] == "4WD"  # blank → filled
    assert vehicle["engine"] == "5.0L V8" and vehicle["cab"] == "crew"
    assert set(vehicle["_vin_filled"]) == {"driveline", "engine", "cab"}
