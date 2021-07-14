from scripts.resolve_foursight_checks import json_subst_all

def test_json_subst_all():

    subs = {"x": "ex"}
    assert json_subst_all(3, subs) == 3
    assert json_subst_all("x", subs) == "ex"
    assert json_subst_all("y", subs) == "y"
    assert json_subst_all(["x", "y", "z"], subs) == ["ex", "y", "z"]
    assert json_subst_all(["x", "y", "z", "x", "y", "z"], subs) == ["ex", "y", "z", "ex", "y", "z"]

    subs = {3: "three"}
    assert json_subst_all(3, subs) == "three"
    assert json_subst_all(3.0, subs) == "three"  # weird but acceptable

    subs = {"x": "ex", "y": "why", "ex": "y", "why": "y"}
    assert json_subst_all("x", subs) == "ex"
    assert json_subst_all(["x", "y"], subs) == ["ex", "why"]
    assert json_subst_all({"x": "y", "y": "x"}, subs) == {"ex": "why", "why": "ex"}
