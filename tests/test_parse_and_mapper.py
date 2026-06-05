"""Characterization tests for evaluate.py parsing + dashboard/mapper.py pure helpers."""
import evaluate
import dashboard.mapper as M


def test_parse_truck_style():
    s = evaluate.parse_truck_style("CREW CAB 4WD 2.7L")
    assert s == {"cab": "Crew Cab", "engine": "2.7L", "driveline": "4WD"}
    assert evaluate.parse_truck_style("REGULAR CAB 2WD") == {"cab": "Regular Cab", "driveline": "RWD"} or \
        evaluate.parse_truck_style("REGULAR CAB 2WD")["cab"] == "Regular Cab"
    assert evaluate.parse_truck_style("") == {}


def test_parse_listing_recovers_trim_from_raw_json():
    rec = {
        "year": "2019", "make": "FORD", "model": "F-150",
        "raw_json": '{"trim":"LARIAT","style":"CREW CAB 4WD 2.7L"}',
        "odometer": "100000 km",
    }
    v = evaluate.parse_listing_to_vehicle(rec)
    assert v["trim"] == "LARIAT"
    assert v["cab"] == "Crew Cab"
    assert v["driveline"] == "4WD"
    assert v["odometer_km"] == 100000


def test_norm_verdict():
    assert M._norm_verdict("BID-TO-FIX") == "BID_TO_FIX"
    assert M._norm_verdict("BID") == "BID"
    assert M._norm_verdict("PASS (thin margin)") == "PASS"
    assert M._norm_verdict("") == "PASS"


def test_lot_of_numeric_and_placeholders():
    assert M._lot_of({"raw_json": '{"lot":"300R"}'}) == ("300R", 300)
    assert M._lot_of({"raw_json": '{"lot":"R019"}'}) == ("R019", 19)
    # placeholders are hidden + sorted last
    assert M._lot_of({"raw_json": '{"lot":"NOTSET-4"}'}) == ("", 10 ** 9)
    assert M._lot_of({"raw_json": '{"lot":"RXXX"}'}) == ("", 10 ** 9)


def test_band():
    assert M._band(400_000) == "< $5k"
    assert M._band(1_800_000) == "$10–20k"
    assert M._band(None) == "—"


def test_fee_gst_separated_from_margin():
    # buyer fee by band + 5% GST on (bid + fee) — the pieces the waterfall now shows separately
    fee, gst = M._fee_gst(6900)
    assert fee == 385                       # $5k–10k band
    assert gst == round((6900 + 385) * 0.05)  # 364
    fee0, gst0 = M._fee_gst(0)
    assert fee0 == 285 and gst0 == round(285 * 0.05)


def test_photo_fields_upscales_cover():
    pf = M._photo_fields({"main_photo_url": "https://x/160x120/a.jpg"})
    assert pf["photos"] == ["https://x/800x600w/a.jpg"]
    assert pf["photo"] == "https://x/160x120/a.jpg"
    assert M._photo_fields({})["photos"] == []
