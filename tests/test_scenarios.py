"""Scenario loading, validation, and the derived 'right answers' the game grades against."""
import json

import pytest

from exposure_sim.scenarios import ScenarioError, ScenarioRepository


def test_three_scenarios_load_in_order(repo):
    assert [s.id for s in repo.all()] == ["harbor-lane", "prairie-freight", "regional-bureau"]


@pytest.mark.parametrize("sid, deployment, jewels, gaps", [
    ("harbor-lane", "saas_direct", {"payments", "storefront", "orderdb"}, {"iot"}),
    ("prairie-freight", "saas_collector", {"billing", "dcs", "portal"}, {"build"}),
    ("regional-bureau", "onprem", {"portal", "ad", "hrdb"}, {"ot"}),
])
def test_derived_truths(repo, sid, deployment, jewels, gaps):
    s = repo.get(sid)
    assert s.expected_deployment == deployment
    assert s.crown_jewels == jewels
    assert s.coverage_gaps == gaps


def test_qualys_appliance_is_not_a_collector_target(repo):
    """Drawn on-prem, but its API lives in Qualys's cloud. This is a deliberate trap."""
    s = repo.get("prairie-freight")
    assert s.source("qualys").zone == "mgmt"
    assert s.onprem_endpoints == {"tenable", "jira-dc"}


def test_edr_is_context_not_coverage(repo):
    """CrowdStrike seeing the build agents must not count as vulnerability coverage."""
    s = repo.get("prairie-freight")
    assert "build" in s.coverage_gaps
    assert s.source("falcon") not in s.vuln_sources


def test_validation_rejects_bad_reference(tmp_path, repo):
    raw = json.loads((repo.directory / "01_harbor_lane.json").read_text())
    raw["sources"][0]["covers"].append("does-not-exist")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(raw))
    with pytest.raises(ScenarioError, match="does-not-exist"):
        ScenarioRepository.load_file(bad)


def test_validation_rejects_unknown_team(tmp_path, repo):
    raw = json.loads((repo.directory / "01_harbor_lane.json").read_text())
    raw["asset_groups"][0]["owner"] = "Ghost-Team"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(raw))
    with pytest.raises(ScenarioError, match="Ghost-Team"):
        ScenarioRepository.load_file(bad)


def test_rules_come_from_the_file(tmp_path, repo):
    """A scenario can grade differently with no code change."""
    raw = json.loads((repo.directory / "01_harbor_lane.json").read_text())
    raw["rules"]["crown_jewel"] = {"always": ["critical", "high"], "if_internet_facing": []}
    path = tmp_path / "strict.json"
    path.write_text(json.dumps(raw))
    s = ScenarioRepository.load_file(path)
    assert s.crown_jewels == {"payments", "orderdb", "storefront", "eks", "repos"}


def test_missing_rules_use_defaults(tmp_path, repo):
    raw = json.loads((repo.directory / "01_harbor_lane.json").read_text())
    del raw["rules"]
    path = tmp_path / "norules.json"
    path.write_text(json.dumps(raw))
    assert ScenarioRepository.load_file(path).crown_jewels == {"payments", "orderdb", "storefront"}


def test_future_schema_is_refused(tmp_path, repo):
    raw = json.loads((repo.directory / "01_harbor_lane.json").read_text())
    raw["schema_version"] = 99
    path = tmp_path / "future.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ScenarioError, match="newer than this app"):
        ScenarioRepository.load_file(path)
