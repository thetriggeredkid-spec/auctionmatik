"""Characterization tests for engine/comp_scrutiny.py — normalization + scrutinize."""

from engine import comp_scrutiny as CS


def test_dedupe_reposts_collapses_same_vehicle():
    # a dealer reposting the same truck 4× (different photos) → one comp, not four
    base = {
        "year": 2019,
        "make": "FORD",
        "model": "F-150",
        "trim": "XLT",
        "odometer_km": 100_000,
        "asking_price": 3_000_000,
    }
    comps = [
        {**base, "external_id": "a"},
        {**base, "external_id": "b", "main_photo_url": "http://x/p.jpg"},
        {**base, "external_id": "c"},
        {**base, "external_id": "d"},
        # a genuinely different unit stays
        {
            "year": 2019,
            "make": "FORD",
            "model": "F-150",
            "trim": "XLT",
            "odometer_km": 60_000,
            "asking_price": 3_400_000,
            "external_id": "e",
        },
    ]
    deduped, merged = CS._dedupe_reposts(comps)
    assert merged == 3 and len(deduped) == 2
    # the surviving repost is the one that had a photo
    survivor = next(c for c in deduped if c["odometer_km"] == 100_000)
    assert survivor["main_photo_url"] == "http://x/p.jpg"
    # and scrutinize notes the merge
    res = CS.scrutinize(
        {"year": 2019, "make": "FORD", "model": "F-150", "odometer_km": 90_000}, comps
    )
    assert any("duplicate repost" in n for n in res["narrative"])


def test_vision_condition_levels():
    assert (
        CS._vision_condition({"vision": {"flood_or_frame_concern": True}}) == "damaged"
    )
    assert CS._vision_condition({"vision": {"exterior_grade": 2}}) == "damaged"
    assert (
        CS._vision_condition({"vision": {"damage_details": [{"severity": "severe"}]}})
        == "damaged"
    )
    assert CS._vision_condition({"vision": {"rust_severity": "moderate"}}) == "rough"
    assert CS._vision_condition({"vision": {"exterior_grade": 4}}) is None
    assert CS._vision_condition({"vision": {"error": "x"}}) is None
    assert CS._vision_condition({}) is None


def test_vision_beats_listing_keywords():
    # listing text says "mint" but the photos show grade-2 → treated as rough, not clean
    comp = {"title": "mint immaculate", "vision": {"exterior_grade": 2}}
    assert CS._condition_hint(comp) == "rough"


def test_scrutinize_excludes_vision_damaged_comp():
    subject = {"year": 2019, "make": "FORD", "model": "F-150", "odometer_km": 100_000}
    comps = [
        {
            "asking_price": 3_000_000,
            "year": 2019,
            "make": "FORD",
            "model": "F-150",
            "odometer_km": 100_000,
        },
        {
            "asking_price": 3_000_000,
            "year": 2019,
            "make": "FORD",
            "model": "F-150",
            "odometer_km": 100_000,
        },
        # a cheap one that photos reveal is wrecked — must NOT anchor the clean value down
        {
            "asking_price": 1_500_000,
            "year": 2019,
            "make": "FORD",
            "model": "F-150",
            "odometer_km": 100_000,
            "vision": {"flood_or_frame_concern": True},
        },
    ]
    res = CS.scrutinize(subject, comps)
    assert any("vision" in (e.get("_reason") or "") for e in res["excluded"])
    assert all(
        not c.get("vision", {}).get("flood_or_frame_concern") for c in res["clean"]
    )
    assert res["anchor"] >= 2_900_000  # the wrecked $15k comp didn't drag it down


def test_km_normalize_more_km_adjusts_up():
    # a higher-km comp normalized to a lower-km subject adjusts the price UP
    base = CS._km_normalize(1_000_000, 200_000, 100_000)
    assert base == 1_340_000
    # equal km → unchanged
    assert CS._km_normalize(1_000_000, 100_000, 100_000) == 1_000_000
    # missing data → unchanged
    assert CS._km_normalize(1_000_000, None, 100_000) == 1_000_000


def test_dom_discount_steps():
    assert CS._dom_discount(10) == 0.0
    assert CS._dom_discount(30) == 0.03
    assert CS._dom_discount(50) == 0.07
    assert CS._dom_discount(120) == 0.12
    assert CS._dom_discount(None) == 0.0


def test_realized_comp_outweighs_asks_and_skips_dom():
    subject = {"year": 2019, "make": "FORD", "model": "F-150", "odometer_km": 100_000}
    comps = [
        # two scraped asks at $30k
        {
            "asking_price": 3_000_000,
            "year": 2019,
            "make": "FORD",
            "model": "F-150",
            "odometer_km": 100_000,
            "posted_at": None,
        },
        {
            "asking_price": 3_000_000,
            "year": 2019,
            "make": "FORD",
            "model": "F-150",
            "odometer_km": 100_000,
            "posted_at": None,
        },
        # one realized sale at $24k — real transaction, should pull the anchor down
        {
            "asking_price": 2_400_000,
            "year": 2019,
            "make": "FORD",
            "model": "F-150",
            "odometer_km": 100_000,
            "posted_at": None,
            "realized": True,
            "source": "personal_sold",
        },
    ]
    res = CS.scrutinize(subject, comps)
    realized = next(r for r in res["clean"] if r.get("_realized"))
    asks = [r for r in res["clean"] if not r.get("_realized")]
    # the realized comp carries the highest similarity weight
    assert all(realized["_score"] > a["_score"] for a in asks)
    # weighted anchor lands below the plain $30k ask median (the real sale pulls it down)
    assert res["anchor"] < 3_000_000
    # a realized sale takes no days-on-market discount
    assert realized["_dom_discount"] == 0.0


def test_norm_cab():
    assert CS._norm_cab("XLT SuperCrew") == "crew"
    assert CS._norm_cab("F-150 SuperCab") == "ext"
    assert CS._norm_cab("Regular Cab") == "reg"
    assert CS._norm_cab("Sedan") is None


def test_trim_token():
    assert CS._trim_token("2019 Ford F-150 Lariat") == "lariat"
    assert CS._trim_token("XLT SuperCrew") == "xlt"
    assert CS._trim_token("plain car") is None


def test_scrutinize_excludes_rebuilt_and_returns_anchor():
    subject = {"year": 2015, "make": "JEEP", "model": "WRANGLER", "odometer_km": 140000}
    comps = [
        {
            "year": 2015,
            "make": "Jeep",
            "model": "Wrangler",
            "odometer_km": 150000,
            "asking_price": 1_600_000,
            "title": "clean",
            "description": "good condition",
        },
        {
            "year": 2014,
            "make": "Jeep",
            "model": "Wrangler",
            "odometer_km": 135000,
            "asking_price": 1_550_000,
            "title": "clean",
            "description": "",
        },
        {
            "year": 2016,
            "make": "Jeep",
            "model": "Wrangler",
            "odometer_km": 120000,
            "asking_price": 1_700_000,
            "title": "clean",
            "description": "",
        },
        {
            "year": 2013,
            "make": "Jeep",
            "model": "Wrangler",
            "odometer_km": 160000,
            "asking_price": 950_000,
            "title": "rebuilt",
            "description": "rebuilt title salvage",
        },
    ]
    res = CS.scrutinize(subject, comps)
    assert set(res) >= {"anchor", "confidence", "clean", "excluded", "narrative"}
    assert isinstance(res["anchor"], int) and res["anchor"] > 0
    assert res["confidence"] in ("high", "medium", "low")
    # the rebuilt comp is excluded from the clean pool
    assert any("rebuilt" in (e.get("_reason") or "") for e in res["excluded"])
    assert all(c.get("_title") != "rebuilt" for c in res["clean"])


def test_scrutinize_empty_pool():
    res = CS.scrutinize(
        {"year": 2015, "make": "X", "model": "Y", "odometer_km": 100000}, []
    )
    assert res["anchor"] is None
    assert res["clean"] == []
