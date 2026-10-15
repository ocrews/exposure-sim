"""End to end: play every stage of every org through HTTP, like a browser would."""
import pytest
from test_oop import perfect_fields as perfect_oop

from exposure_sim import create_app
from exposure_sim.stages import STAGES


def perfect_answers(s):
    return {
        "integrations": {"connect": [x.id for x in s.sources], "gaps": sorted(s.coverage_gaps)},
        "deployment": {"model": s.expected_deployment, "targets": sorted(s.onprem_endpoints), "direction": "outbound"},
        "crown_jewels": {"picks": sorted(s.crown_jewels)},
        "risk": {"signals": ["cvss", "kev", "epss", "exposure", "criticality"], "kev_policy": "targeted", "p1_sla": "7"},
        "ticketing": {"keys": ["remediation", "owner", "platform"], "fallback": "triage", "rollout": "pilot",
                      **{f"route_{t.id}": t.works_in for t in s.teams}},
        "oop": perfect_oop(s),
    }


def weak_answers(s):
    """Every stage answered badly on purpose: maximum pushback, maximum stored data."""
    return {
        "integrations": {"connect": [s.vuln_sources[0].id], "gaps": [g.id for g in s.asset_groups]},
        "deployment": {"model": "saas_direct", "targets": [x.id for x in s.sources], "direction": "inbound"},
        "crown_jewels": {"picks": [g.id for g in s.asset_groups]},
        "risk": {"signals": ["cvss", "scanner_count"], "kev_policy": "everywhere", "p1_sla": "3"},
        "ticketing": {"keys": ["cve", "plugin", "asset"], "fallback": "skip", "rollout": "all",
                      **{f"route_{t.id}": s.ticket_systems[0].id for t in s.teams}},
        "oop": {"role_parse": "shared", "role_fetch": "abstract", "role_norm_hostname": "abstract",
                "role_map_severity": "omit", "returns": "raw", "paginated_class": "yes",
                **{f"parent_{x.id}": "paginated" for x in s.vuln_sources},
                **{f"ovr_{x.id}": ["fetch", "map_severity", "norm_hostname"] for x in s.vuln_sources}},
    }


@pytest.fixture
def client():
    return create_app({"TESTING": True, "SECRET_KEY": "test"}).test_client()


def play(client, sid, answers, action):
    for stage in STAGES:
        r = client.post(f"/play/{sid}/{stage.id}", data={**answers[stage.id], "action": action})
        assert r.status_code == 302, f"{stage.id} did not lock"
        page = client.get(f"/play/{sid}/{stage.id}")
        assert page.status_code == 200 and "fieldset disabled" in page.get_data(as_text=True)


def test_perfect_playthrough_scores_100(client, scenario):
    # "check" (not "lock"): perfect answers must lock on their own, with zero pushback
    play(client, scenario.id, perfect_answers(scenario), "check")
    html = client.get(f"/play/{scenario.id}/debrief").get_data(as_text=True)
    assert "(100%)" in html
    assert html.count("Nothing missed.") == len(STAGES)
    assert "class PaginatedApiParser" in html or len(scenario.paginated_sources) < 2
    assert client.get(f"/play/{scenario.id}").headers["Location"].endswith("/debrief")


def test_weak_playthrough_still_completes(client, scenario):
    play(client, scenario.id, weak_answers(scenario), "lock")
    html = client.get(f"/play/{scenario.id}/debrief").get_data(as_text=True)
    assert "(100%)" not in html and "REVIEW" in html


def test_map_overlay_after_deployment(client, repo):
    s = repo.get("prairie-freight")
    answers = perfect_answers(s)
    for stage_id in ("integrations", "deployment"):
        client.post(f"/play/{s.id}/{stage_id}", data={**answers[stage_id], "action": "check"})
    html = client.get(f"/play/{s.id}/crown_jewels").get_data(as_text=True)
    assert 'data-id="collector"' in html and 'data-id="platform"' in html
    assert 'class="edge edge-uplink"' in html and 'data-src="collector" data-dst="tenable"' in html


def test_cookie_stays_small_after_everything(client, repo):
    """Signed session cookies cap out around 4 KB. Play all 3 orgs with the wordiest answers."""
    for s in repo.all():
        play(client, s.id, weak_answers(s), "lock")
    cookie = client.get_cookie("session")
    assert cookie is not None
    assert len(cookie.value) < 3500, len(cookie.value)
