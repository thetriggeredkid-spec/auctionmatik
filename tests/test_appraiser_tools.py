"""Tests for the deep appraiser's escalation tools + comp-collection settings."""
from engine import appraiser
from engine import settings as S


def test_deep_tools_have_no_live_comp_scrape():
    """fetch_more_comps is removed — comps are collected once before the run, so deep
    reasons over a fixed set (stable values, comps shown in the tab)."""
    tools, execute = appraiser._build_tools({"subject": {}, "vision": {}})
    names = {t["name"] for t in tools}
    assert "fetch_more_comps" not in names
    assert names == {"get_carfax_report", "refine_repair_quote"}
    # an unknown/removed tool name degrades gracefully, not crash
    assert "unknown tool" in execute("fetch_more_comps", {})


def test_deep_autocollect_comps_default_on():
    d = S._read_engine_defaults()
    assert d["engine"]["deep_autocollect_comps"] is True
