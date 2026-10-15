"""The map layout: geometry is sane, and player decisions show up as overlay."""
import json

from exposure_sim.topology import WIDTH, Overlay, TopologyBuilder


def boxes_overlap(a, b):
    return a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h


def test_every_node_inside_its_zone_and_no_overlaps(scenario):
    layout = TopologyBuilder(scenario, Overlay(deployment=scenario.expected_deployment,
                                              connected={s.id for s in scenario.sources})).build()
    for n in layout.nodes:
        assert 0 <= n.x and n.x + n.w <= WIDTH
        assert any(z.y <= n.y and n.y + n.h <= z.y + z.h for z in layout.zones), n.id
    for i, a in enumerate(layout.nodes):
        for b in layout.nodes[i + 1:]:
            assert not boxes_overlap(a, b), (a.id, b.id)


def test_zones_stack_without_overlap(scenario):
    zones = TopologyBuilder(scenario).build().zones
    for upper, lower in zip(zones, zones[1:]):
        assert upper.y + upper.h <= lower.y


def test_coverage_edges_match_scenario(scenario):
    layout = TopologyBuilder(scenario).build()
    cov = {(e.src, e.dst) for e in layout.edges if e.kind == "coverage"}
    assert cov == {(s.id, g) for s in scenario.vuln_sources for g in s.covers}


def test_gaps_hidden_until_integrations_locked(repo):
    s = repo.get("prairie-freight")
    hidden = TopologyBuilder(s, Overlay(reveal_gaps=False)).build()
    shown = TopologyBuilder(s, Overlay(reveal_gaps=True)).build()
    assert "gap" not in hidden.node("build").classes
    assert "gap" in shown.node("build").classes


def test_unconnected_scanner_loses_its_lines(repo):
    s = repo.get("prairie-freight")
    layout = TopologyBuilder(s, Overlay(connected={"wiz", "snyk"})).build()
    assert "unconnected" in layout.node("tenable").classes
    assert not any(e.src == "tenable" for e in layout.edges)


def test_collector_overlay(repo):
    s = repo.get("prairie-freight")
    layout = TopologyBuilder(s, Overlay(deployment="saas_collector", collector_targets={"tenable", "jira-dc"},
                                        connected={x.id for x in s.sources})).build()
    zone_of = {n.id: z.id for n in layout.nodes for z in layout.zones if z.y <= n.y < z.y + z.h}
    assert zone_of["platform"] == "saas" and zone_of["collector"] == "mgmt"
    kinds = {(e.src, e.dst): e.kind for e in layout.edges}
    assert kinds[("collector", "platform")] == "uplink"
    assert kinds[("collector", "tenable")] == "relay"
    assert kinds[("platform", "wiz")] == "link"


def test_onprem_platform_sits_inside(repo):
    s = repo.get("regional-bureau")
    layout = TopologyBuilder(s, Overlay(deployment="onprem")).build()
    mgmt = next(z for z in layout.zones if z.id == "mgmt")
    p = layout.node("platform")
    assert mgmt.y <= p.y < mgmt.y + mgmt.h
    assert not any(n.kind == "collector" for n in layout.nodes)


def test_layout_serializes_to_json(scenario):
    data = TopologyBuilder(scenario).build().to_dict()
    assert json.loads(json.dumps(data))["width"] == WIDTH


def test_overlay_from_answers():
    o = Overlay.from_answers({"integrations": {"connect": ["a"], "gaps": []},
                              "deployment": {"model": "onprem", "targets": []},
                              "crown_jewels": {"picks": ["x"]}}, locked={"integrations"})
    assert o.connected == {"a"} and o.reveal_gaps and o.deployment == "onprem" and o.crown_jewels == {"x"}
