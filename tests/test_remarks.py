"""Tests for condition-report remarks: extraction + downstream signal decoding."""
from collector import regal_enrich as RE
from engine import declarations as D
import evaluate

_FORTE_HTML = """
<div class="w3-light-gray w3-padding">REMARKS:</div>
<div class="w3-padding" style="font-weight: bold;" > </div>
<div class="w3-padding"><pre>This vehicle has a 2.0 litre 4 cylinder gasoline engine and an automatic
transmission. The Check Engine light and Airbag light are on. The front bumper is a
different color from the rest of the vehicle. There is slight hail on the hood. The
windshield is cracked.</pre></div>
</div> <!-- END OF REMARKS -->
"""

_TRUCK_HTML = """
REMARKS:</div> <div class="w3-padding" style="font-weight: bold;" >*SUSPENSION REQUIRES REPAIR* </div>
<div class="w3-padding"><pre>The vehicle has mechanical problems. The suspension is noisy.</pre></div>
</div> <!-- END OF REMARKS -->
"""


def test_extract_remarks_pre_text():
    r = RE._extract_remarks(_FORTE_HTML)
    assert "Check Engine light and Airbag light are on" in r
    assert "different color" in r


def test_extract_remarks_includes_bold_announcement():
    r = RE._extract_remarks(_TRUCK_HTML)
    assert r.startswith("*SUSPENSION REQUIRES REPAIR*")
    assert "suspension is noisy" in r


def test_extract_remarks_none_when_absent():
    assert RE._extract_remarks("<html>no remarks here</html>") is None


def test_remarks_decode_check_engine_airbag_repaint():
    r = RE._extract_remarks(_FORTE_HTML)
    d = D.analyze_declarations("", r)
    assert "check_engine" in d["remark_signals"]
    assert "airbag_light" in d["remark_signals"]
    assert "repaint" in d["remark_signals"]      # "different color" → mismatched/replacement panel
    assert d["mechanical_risk"] is True          # CEL + airbag route to mechanical risk
    msgs = " ".join(f["message"].lower() for f in d["flags"])
    assert "airbag" in msgs


def test_parse_listing_prefers_remarks_over_other():
    rec = {"year": 2019, "make": "KIA", "model": "FORTE",
           "remarks": "Check Engine light is on. Front bumper different color.",
           "other": "*MP*"}
    v = evaluate.parse_listing_to_vehicle(rec)
    assert "Check Engine" in v["condition_notes"]
