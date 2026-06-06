"""Tests for collector.retail_comps odometer parsing (km extraction robustness)."""

from collector.retail_comps import _parse_km_text, _fb_odometer


def test_km_text_formats():
    assert _parse_km_text("259K km") == 259_000
    assert _parse_km_text("140,000 km") == 140_000
    assert _parse_km_text("72 000 km") == 72_000
    assert _parse_km_text("12.5k km") == 12_500
    # European thousands separator must NOT read as 72 km (the bug this guards)
    assert _parse_km_text("72.000 km") == 72_000
    # miles → km
    assert abs(_parse_km_text("85000 miles") - 136_793) <= 2


def test_km_text_rejects_noise_and_out_of_range():
    assert _parse_km_text("clean title, no accidents") is None
    assert _parse_km_text("") is None
    # an implausible sub-100 reading (the European-decimal failure mode) is rejected
    assert _parse_km_text("2018 Jeep 72 km") is None


def test_fb_odometer_falls_back_to_title_then_desc():
    # no subtitle block → recover km from the title
    item = {"customSubTitlesWithRenderingFlags": None}
    assert _fb_odometer(item, "2011 Jeep Wrangler Rubicon 139k km", None) == 139_000
    # subtitle wins when present
    item2 = {"customSubTitlesWithRenderingFlags": [{"subtitle": "110,000 km"}]}
    assert _fb_odometer(item2, "title says 200k km", "desc 300k km") == 110_000
    # neither → None
    assert _fb_odometer({}, "no mileage here", "still nothing") is None
