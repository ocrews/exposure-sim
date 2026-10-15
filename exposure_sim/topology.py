"""Compute the network map as plain data: zones, nodes, and edges with coordinates.

No HTML here. The Jinja template draws whatever this returns, and `to_dict()` gives the
same layout as JSON, so a future interactive frontend or image export can reuse it.

Layout: zones are full-width horizontal bands stacked top to bottom (internet at the top,
management at the bottom). Inside a band, nodes sit on a grid. Edges are drawn underneath.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from exposure_sim.models import Scenario

WIDTH = 980
PAD = 14
HEADER = 28
NODE_W = 176
NODE_H = 78
GAP = 14
ZONE_GAP = 8
COLS = (WIDTH - 2 * PAD + GAP) // (NODE_W + GAP)


@dataclass
class Node:
    id: str
    kind: str                 # asset | source | ticket | platform | collector
    title: str
    lines: list[str]
    x: int = 0
    y: int = 0
    w: int = NODE_W
    h: int = NODE_H
    classes: list[str] = field(default_factory=list)
    badges: list[str] = field(default_factory=list)   # right-aligned on line 1 (sources: line 2)
    tags: list[str] = field(default_factory=list)     # status chips on the bottom line

    @property
    def cx(self) -> int:
        return self.x + self.w // 2

    @property
    def cy(self) -> int:
        return self.y + self.h // 2


@dataclass
class ZoneBand:
    id: str
    label: str
    kind: str
    x: int
    y: int
    w: int
    h: int


@dataclass
class Edge:
    src: str
    dst: str
    kind: str                 # coverage | link | uplink | relay
    path: str = ""
    label: str = ""
    lx: int = 0
    ly: int = 0


@dataclass
class Overlay:
    """What the player has decided so far. Each field is None until that stage is answered."""
    connected: set[str] | None = None
    reveal_gaps: bool = False
    deployment: str | None = None
    collector_targets: set[str] = field(default_factory=set)
    crown_jewels: set[str] | None = None

    @classmethod
    def from_answers(cls, answers: dict, locked: set[str]) -> "Overlay":
        integ = answers.get("integrations")
        dep = answers.get("deployment")
        cj = answers.get("crown_jewels")
        return cls(
            connected=set(integ["connect"]) if integ else None,
            reveal_gaps="integrations" in locked,
            deployment=dep.get("model") if dep else None,
            collector_targets=set(dep.get("targets", [])) if dep else set(),
            crown_jewels=set(cj["picks"]) if cj else None,
        )


@dataclass
class Layout:
    width: int
    height: int
    zones: list[ZoneBand]
    nodes: list[Node]
    edges: list[Edge]

    def node(self, nid: str) -> Node:
        return next(n for n in self.nodes if n.id == nid)

    def to_dict(self) -> dict:
        return asdict(self)


class TopologyBuilder:
    def __init__(self, scenario: Scenario, overlay: Overlay | None = None):
        self.s = scenario
        self.o = overlay or Overlay()

    # ---- nodes ------------------------------------------------------------------------
    def _source_node(self, src) -> Node:
        api = "API: on-prem" if src.api_location == "onprem" else "API: cloud"
        n = Node(src.id, "source", src.label, [src.vendor_note, api], classes=[f"src-{src.kind}"])
        n.badges.append("vuln scanner" if src.is_vuln_source else src.kind.upper())
        if self.o.connected is not None:
            n.classes.append("connected" if src.id in self.o.connected else "unconnected")
        return n

    def _asset_node(self, g) -> Node:
        n = Node(g.id, "asset", g.label, [f"{g.count} · {g.platform}", f"owner: {g.owner or 'none'}"])
        n.badges.append(g.criticality)
        n.classes.append(f"crit-{g.criticality}")
        if g.internet_facing:
            n.tags.append("internet")
        if g.owner is None:
            n.classes.append("unowned")
        if self.o.reveal_gaps and g.id in self.s.coverage_gaps:
            n.classes.append("gap")
            n.tags.append("no scanner")
        if self.o.crown_jewels is not None and g.id in self.o.crown_jewels:
            n.classes.append("jewel")
            n.tags.append("wave 1")
        return n

    def _overlay_nodes(self) -> dict[str, list[Node]]:
        extra: dict[str, list[Node]] = {}
        model = self.o.deployment
        if not model:
            return extra
        platform_zone = self.s.collector_zone if model == "onprem" else "saas"
        label = "Self-hosted install" if model == "onprem" else "Vendor SaaS"
        extra.setdefault(platform_zone, []).append(
            Node("platform", "platform", "Exposure platform", [label], classes=["overlay"]))
        if model == "saas_collector":
            extra.setdefault(self.s.collector_zone, []).append(
                Node("collector", "collector", "Collector", ["dials out on 443"], classes=["overlay"]))
        return extra

    # ---- layout -----------------------------------------------------------------------
    def build(self) -> Layout:
        overlay_nodes = self._overlay_nodes()
        zones, nodes = [], []
        y = 0
        for z in self.s.zones:
            items = ([self._source_node(x) for x in self.s.sources if x.zone == z.id]
                     + [Node(t.id, "ticket", t.label,
                             ["ticketing", "API: on-prem" if t.api_location == "onprem" else "API: cloud"])
                        for t in self.s.ticket_systems if t.zone == z.id]
                     + overlay_nodes.get(z.id, [])
                     + [self._asset_node(g) for g in self.s.asset_groups if g.zone == z.id])
            rows = max(1, -(-len(items) // COLS))
            h = HEADER + rows * (NODE_H + GAP) + PAD - GAP + 4 if items else HEADER + 18
            zones.append(ZoneBand(z.id, z.label, z.kind, 0, y, WIDTH, h))
            for i, n in enumerate(items):
                n.x = PAD + (i % COLS) * (NODE_W + GAP)
                n.y = y + HEADER + (i // COLS) * (NODE_H + GAP)
                nodes.append(n)
            y += h + ZONE_GAP
        layout = Layout(WIDTH, y - ZONE_GAP, zones, nodes, [])
        layout.edges = self._edges(layout)
        return layout

    def _edges(self, layout: Layout) -> list[Edge]:
        edges = []
        ids = {n.id for n in layout.nodes}
        for src in self.s.vuln_sources:
            if self.o.connected is not None and src.id not in self.o.connected:
                continue
            for gid in src.covers:
                edges.append(self._edge(layout, src.id, gid, "coverage"))

        model = self.o.deployment
        if model and "platform" in ids:
            connected = self.o.connected if self.o.connected is not None else {x.id for x in self.s.sources}
            targets = [*connected, *(t.id for t in self.s.ticket_systems)]
            if model == "saas_collector":
                edges.append(self._edge(layout, "collector", "platform", "uplink", "443 out"))
                for tid in targets:
                    kind, origin = ("relay", "collector") if tid in self.o.collector_targets else ("link", "platform")
                    edges.append(self._edge(layout, origin, tid, kind))
                for tid in self.o.collector_targets - set(targets):
                    edges.append(self._edge(layout, "collector", tid, "relay"))
            else:
                for tid in targets:
                    edges.append(self._edge(layout, "platform", tid, "link"))
        return edges

    @staticmethod
    def _edge(layout: Layout, a: str, b: str, kind: str, label: str = "") -> Edge:
        na, nb = layout.node(a), layout.node(b)
        if abs(na.cy - nb.cy) < NODE_H:               # same row: connect the facing sides
            left, right = (na, nb) if na.x < nb.x else (nb, na)
            x1, y1, x2, y2 = left.x + left.w, left.cy, right.x, right.cy
            path = f"M{x1},{y1} L{x2},{y2}"
        else:                                          # different rows: S-curve bottom to top
            top, bot = (na, nb) if na.y < nb.y else (nb, na)
            x1, y1, x2, y2 = top.cx, top.y + top.h, bot.cx, bot.y
            ym = (y1 + y2) // 2
            path = f"M{x1},{y1} C{x1},{ym} {x2},{ym} {x2},{y2}"
        return Edge(a, b, kind, path, label, (x1 + x2) // 2 + 6, (y1 + y2) // 2)
