"""Tests for scripts/canvas_tool.py (layout + validation)."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "canvas_tool.py"
spec = importlib.util.spec_from_file_location("canvas_tool", SCRIPT)
ct = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ct)


def big_spec(layout="mindmap"):
    return {
        "layout": layout,
        "root": {"text": "# Root", "children": [
            {"text": f"## Branch {b}", "key": f"b{b}", "children": [
                {"text": f"Leaf {b}.{i} with some **bold** text and a [link](https://example.com/very/long/url)"}
                for i in range(b + 1)
            ]} for b in range(6)
        ]},
        "links": [{"from": "b0", "to": "b5", "label": "relates"}],
    }


def test_mindmap_is_valid_balanced_and_overlap_free():
    canvas = ct.Layout(big_spec()).build()
    assert ct.validate(canvas) == []
    assert len(canvas["nodes"]) == 1 + 6 + sum(range(1, 7))
    xs = [n["x"] for n in canvas["nodes"][1:]]
    assert any(x > 0 for x in xs) and any(x < 0 for x in xs)  # branches on both sides
    assert all(n["x"] % 10 == 0 and n["y"] % 10 == 0 for n in canvas["nodes"])  # grid aligned
    colors = {n.get("color") for n in canvas["nodes"][1:]}
    assert colors <= set("123456")


def test_tree_layout_is_valid_and_top_down():
    canvas = ct.Layout(big_spec("tree")).build()
    assert ct.validate(canvas) == []
    root = canvas["nodes"][0]
    assert all(n["y"] > root["y"] for n in canvas["nodes"][1:])


def test_ids_are_stable_across_runs():
    a = ct.Layout(big_spec()).build()
    b = ct.Layout(big_spec()).build()
    assert [n["id"] for n in a["nodes"]] == [n["id"] for n in b["nodes"]]


def test_link_sizing_ignores_hidden_url():
    short = ct.auto_size({"text": "[rugcheck](https://rugcheck.xyz/tokens/" + "x" * 80 + ")"})
    assert short[0] <= 250


def test_validator_catches_spec_violations(tmp_path):
    bad = {
        "nodes": [
            {"id": "a" * 16, "type": "text", "x": 0, "y": 0, "width": 100, "height": 50, "text": "bad\\nline"},
            {"id": "a" * 16, "type": "text", "x": 10, "y": 10, "width": 100, "height": 50, "text": "dup + overlap"},
            {"id": "b" * 16, "type": "file", "x": 500, "y": 0, "width": 100, "height": 50, "file": "Missing.md"},
            {"id": "c" * 16, "type": "link", "x": 900, "y": 0, "width": 100, "height": 50, "color": "9"},
        ],
        "edges": [{"id": "e1", "fromNode": "a" * 16, "toNode": "zzz", "toSide": "middle"}],
    }
    errors = " | ".join(ct.validate(bad, tmp_path))
    for needle in ("duplicate id", "backslash-n", "overlap", "file not found", "needs 'url'", "bad color",
                   "does not exist", "bad toSide"):
        assert needle in errors, needle


def test_unknown_link_key_is_rejected():
    s = big_spec()
    s["links"] = [{"from": "b0", "to": "nope"}]
    try:
        ct.Layout(s).build()
    except ValueError as e:
        assert "unknown key" in str(e)
    else:
        raise AssertionError("expected ValueError")
