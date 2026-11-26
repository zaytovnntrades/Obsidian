#!/usr/bin/env python3
"""Mind-map layout + validation for Obsidian JSON Canvas files (spec 1.0). Stdlib only.

Agents describe WHAT goes on the map as a simple outline; this script does the geometry.

    python3 scripts/canvas_tool.py layout vault/Maps/specs/wif.json -o vault/Maps/WIF.canvas
    python3 scripts/canvas_tool.py validate vault/Maps/WIF.canvas

Outline spec (JSON):
{
  "root": {"text": "# WIF", "color": "5",
           "children": [
              {"text": "Red flags", "color": "1", "key": "flags",
               "children": [{"text": "FDV 50x liquidity"}]},
              {"file": "Coins/WIF-EKpQGS.md"},                  # embeds a vault note
              {"url": "https://dexscreener.com/solana/..."}     # web preview card
           ]},
  "links": [{"from": "flags", "to": "bear", "label": "feeds"}],  # optional cross-links by "key"
  "layout": "mindmap"   # "mindmap" (branches left+right, default) or "tree" (top-down)
}
Optional per node: "key", "color" ("1"-"6" or "#hex"; children inherit their branch color),
"width"/"height" (auto-sized from text otherwise), "side" ("left"/"right", top-level branches only).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path

H_GAP = 80          # horizontal gap between depth levels
V_GAP = 30          # vertical gap between sibling subtrees
GRID = 10
BRANCH_COLORS = ["1", "2", "3", "4", "5", "6"]
HEX = re.compile(r"^[0-9a-f]{16}$")
COLOR = re.compile(r"^([1-6]|#[0-9A-Fa-f]{6})$")
SIDES = {"top", "right", "bottom", "left"}


def snap(v: float) -> int:
    return int(round(v / GRID) * GRID)


def node_id(path: str) -> str:
    """Deterministic IDs: re-running the layout keeps IDs stable, so git diffs stay readable."""
    return hashlib.sha1(path.encode()).hexdigest()[:16]


def auto_size(n: dict) -> tuple[int, int]:
    if "width" in n and "height" in n:
        return int(n["width"]), int(n["height"])
    if "file" in n:
        return 400, 300
    if "url" in n:
        return 400, 240
    text = n.get("text", "")
    # size by what is VISIBLE: drop link targets and markdown markers
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_`]|^#+\s*", "", text, flags=re.M)
    lines = text.split("\n")
    longest = max((len(line) for line in lines), default=10)
    width = min(420, max(200, longest * 9 + 40))
    chars_per_line = max(10, (width - 40) // 9)
    wrapped = sum(max(1, math.ceil(len(line) / chars_per_line)) for line in lines)
    heading_bonus = 20 * sum(1 for line in n.get("text", "").split("\n") if line.startswith("#"))
    height = max(60, wrapped * 24 + 30 + heading_bonus)
    return snap(n.get("width", width)), snap(n.get("height", height))


class Layout:
    def __init__(self, spec: dict):
        self.spec = spec
        self.nodes: list[dict] = []
        self.edges: list[dict] = []
        self.keys: dict[str, str] = {}

    # -- tree helpers --------------------------------------------------------
    def _span(self, n: dict, vertical: bool) -> int:
        """Space the subtree needs along the stacking axis."""
        w, h = auto_size(n)
        own = h if vertical else w
        kids = n.get("children") or []
        if not kids:
            return own
        total = sum(self._span(c, vertical) for c in kids) + V_GAP * (len(kids) - 1)
        return max(own, total)

    def _emit(self, n: dict, path: str, x: int, y: int, color: str | None) -> str:
        w, h = auto_size(n)
        nid = node_id(path)
        node: dict = {"id": nid, "x": snap(x), "y": snap(y), "width": w, "height": h}
        if "file" in n:
            node["type"] = "file"
            node["file"] = n["file"]
            if n.get("subpath"):
                node["subpath"] = n["subpath"]
        elif "url" in n:
            node["type"] = "link"
            node["url"] = n["url"]
        else:
            node["type"] = "text"
            node["text"] = n.get("text", "")
        if color:
            node["color"] = color
        self.nodes.append(node)
        if n.get("key"):
            if n["key"] in self.keys:
                raise ValueError(f"duplicate key {n['key']!r}")
            self.keys[n["key"]] = nid
        return nid

    def _edge(self, a: str, b: str, from_side: str, to_side: str, color: str | None, label: str | None = None) -> None:
        e = {"id": node_id(f"edge:{a}:{b}:{label}"), "fromNode": a, "fromSide": from_side,
             "toNode": b, "toSide": to_side, "toEnd": "none"}
        if color:
            e["color"] = color
        if label:
            e["label"] = label
        self.edges.append(e)

    # -- mind map: root in the middle, branches left and right ---------------
    def _place_horizontal(self, n, path, x_edge, top, direction, color, parent_id):
        """Place subtree n whose band starts at `top`. direction=+1 grows right, -1 grows left."""
        w, h = auto_size(n)
        span = self._span(n, vertical=True)
        y = top + (span - h) / 2
        x = x_edge if direction > 0 else x_edge - w
        nid = self._emit(n, path, x, y, color)
        if parent_id:
            self._edge(parent_id, nid, "right" if direction > 0 else "left",
                       "left" if direction > 0 else "right", color)
        kids = n.get("children") or []
        kids_span = sum(self._span(c, True) for c in kids) + V_GAP * max(0, len(kids) - 1)
        cy = top + (span - kids_span) / 2
        next_edge = (x + w + H_GAP) if direction > 0 else (x - H_GAP)
        for i, c in enumerate(kids):
            self._place_horizontal(c, f"{path}/{i}", next_edge, cy, direction, c.get("color", color), nid)
            cy += self._span(c, True) + V_GAP

    def mindmap(self) -> None:
        root = self.spec["root"]
        rw, rh = auto_size(root)
        root_id = self._emit(root, "root", -rw / 2, -rh / 2, root.get("color"))
        branches = root.get("children") or []
        for i, b in enumerate(branches):
            b.setdefault("color", BRANCH_COLORS[i % len(BRANCH_COLORS)])
        # balance sides by subtree height unless a branch pins its side
        right, left = [], []
        for idx, br in sorted(enumerate(branches), key=lambda t: -self._span(t[1], True)):
            side = br.get("side")
            if side not in ("left", "right"):
                rs = sum(self._span(x, True) for _, x in right)
                ls = sum(self._span(x, True) for _, x in left)
                side = "right" if rs <= ls else "left"
            (right if side == "right" else left).append((idx, br))
        for side, items, direction in (("right", right, 1), ("left", left, -1)):
            items.sort()  # keep author order within a side
            total = sum(self._span(b, True) for _, b in items) + V_GAP * max(0, len(items) - 1)
            top = -total / 2
            edge_x = (rw / 2 + H_GAP * 1.5) if direction > 0 else (-rw / 2 - H_GAP * 1.5)
            for idx, b in items:
                self._place_horizontal(b, f"root/{idx}", edge_x, top, direction, b["color"], root_id)
                top += self._span(b, True) + V_GAP

    # -- tree: top-down org chart -------------------------------------------
    def _place_vertical(self, n, path, left, y, color, parent_id):
        w, h = auto_size(n)
        span = self._span(n, vertical=False)
        x = left + (span - w) / 2
        nid = self._emit(n, path, x, y, color)
        if parent_id:
            self._edge(parent_id, nid, "bottom", "top", color)
        kids = n.get("children") or []
        kids_span = sum(self._span(c, False) for c in kids) + V_GAP * max(0, len(kids) - 1)
        cx = left + (span - kids_span) / 2
        for i, c in enumerate(kids):
            self._place_vertical(c, f"{path}/{i}", cx, y + h + H_GAP, c.get("color", color), nid)
            cx += self._span(c, False) + V_GAP

    def tree(self) -> None:
        root = self.spec["root"]
        for i, b in enumerate(root.get("children") or []):
            b.setdefault("color", BRANCH_COLORS[i % len(BRANCH_COLORS)])
        self._place_vertical(root, "root", -self._span(root, False) / 2, 0, root.get("color"), None)

    def build(self) -> dict:
        if "root" not in self.spec:
            raise ValueError("spec needs a 'root' node")
        (self.tree if self.spec.get("layout") == "tree" else self.mindmap)()
        for link in self.spec.get("links") or []:
            a, b = self.keys.get(link["from"]), self.keys.get(link["to"])
            if not a or not b:
                raise ValueError(f"link references unknown key: {link}")
            e = {"id": node_id(f"link:{link['from']}:{link['to']}"), "fromNode": a, "toNode": b,
                 "toEnd": "arrow", "color": link.get("color", "6")}
            if link.get("label"):
                e["label"] = link["label"]
            self.edges.append(e)
        return {"nodes": self.nodes, "edges": self.edges}


def overlaps(a: dict, b: dict, pad: int = 10) -> bool:
    return not (a["x"] + a["width"] + pad <= b["x"] or b["x"] + b["width"] + pad <= a["x"]
                or a["y"] + a["height"] + pad <= b["y"] or b["y"] + b["height"] + pad <= a["y"])


def validate(canvas: dict, vault_root: Path | None = None) -> list[str]:
    errors: list[str] = []
    nodes, edges = canvas.get("nodes", []), canvas.get("edges", [])
    ids: set[str] = set()
    for n in nodes:
        nid = n.get("id", "?")
        if nid in ids:
            errors.append(f"duplicate id {nid}")
        ids.add(nid)
        for f in ("id", "type", "x", "y", "width", "height"):
            if f not in n:
                errors.append(f"node {nid}: missing {f}")
        for f in ("x", "y", "width", "height"):
            if f in n and not isinstance(n[f], int):
                errors.append(f"node {nid}: {f} must be an integer")
        t = n.get("type")
        need = {"text": "text", "file": "file", "link": "url"}.get(t)
        if t not in ("text", "file", "link", "group"):
            errors.append(f"node {nid}: bad type {t!r}")
        elif need and need not in n:
            errors.append(f"node {nid}: {t} node needs '{need}'")
        if "color" in n and not COLOR.match(str(n["color"])):
            errors.append(f"node {nid}: bad color {n['color']!r}")
        if t == "text" and "\\n" in n.get("text", ""):
            errors.append(f"node {nid}: text contains a literal backslash-n (renders as '\\n')")
        if t == "file" and vault_root and not (vault_root / n["file"]).exists():
            errors.append(f"node {nid}: file not found in vault: {n['file']}")
    for e in edges:
        eid = e.get("id", "?")
        if eid in ids:
            errors.append(f"duplicate id {eid}")
        ids.add(eid)
        for end in ("fromNode", "toNode"):
            if e.get(end) not in {n.get("id") for n in nodes}:
                errors.append(f"edge {eid}: {end} {e.get(end)!r} does not exist")
        for side in ("fromSide", "toSide"):
            if side in e and e[side] not in SIDES:
                errors.append(f"edge {eid}: bad {side} {e[side]!r}")
        for end in ("fromEnd", "toEnd"):
            if end in e and e[end] not in ("none", "arrow"):
                errors.append(f"edge {eid}: bad {end} {e[end]!r}")
    plain = [n for n in nodes if n.get("type") != "group" and all(k in n for k in ("x", "y", "width", "height"))]
    for i, a in enumerate(plain):  # groups are containers, so only non-group nodes are checked
        for b in plain[i + 1 :]:
            if overlaps(a, b):
                errors.append(f"nodes {a['id']} and {b['id']} overlap")
    return errors


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    lay = sub.add_parser("layout", help="outline spec -> .canvas")
    lay.add_argument("spec")
    lay.add_argument("-o", "--out", required=True)
    val = sub.add_parser("validate", help="check a .canvas file")
    val.add_argument("canvas")
    val.add_argument("--vault", help="vault root, to check file nodes exist")
    args = ap.parse_args()

    if args.cmd == "layout":
        canvas = Layout(json.loads(Path(args.spec).read_text())).build()
        errors = validate(canvas)
        if errors:
            sys.exit("layout produced an invalid canvas:\n  " + "\n  ".join(errors))
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(canvas, indent="\t", ensure_ascii=False) + "\n")
        print(f"wrote {out}: {len(canvas['nodes'])} nodes, {len(canvas['edges'])} edges")
    else:
        canvas = json.loads(Path(args.canvas).read_text())
        errors = validate(canvas, Path(args.vault) if args.vault else None)
        if errors:
            sys.exit(f"INVALID {args.canvas}:\n  " + "\n  ".join(errors))
        print(f"OK {args.canvas}: {len(canvas.get('nodes', []))} nodes, {len(canvas.get('edges', []))} edges")


if __name__ == "__main__":
    main()
