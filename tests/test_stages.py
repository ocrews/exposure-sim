"""Each stage: a perfect answer scores 100% with no pushback; known weak answers trigger pushback.

Perfect answers are built from the scenario's derived truths, so these tests run on all 3 orgs.
"""
from conftest import form

from exposure_sim.stages.crown_jewels import CrownJewelsStage
from exposure_sim.stages.deployment import DeploymentStage
from exposure_sim.stages.integrations import IntegrationsStage
from exposure_sim.stages.risk import RiskStage
from exposure_sim.stages.ticketing import TicketingStage


def run(stage, scenario, **fields):
    answer = stage.parse_form(form(**fields), scenario)
    return answer, stage.evaluate(scenario, answer)


def assert_perfect(ev):
    assert ev.score == ev.max_score > 0, [n.text for n in ev.notes if n.kind == "miss"]
    assert ev.pushback == []


# ---- integrations --------------------------------------------------------------------
def test_integrations_perfect(scenario):
    _, ev = run(IntegrationsStage(), scenario,
                connect=[s.id for s in scenario.sources], gaps=list(scenario.coverage_gaps))
    assert_perfect(ev)


def test_integrations_missing_cmdb_and_gap(scenario):
    vuln = [s.id for s in scenario.vuln_sources]
    _, ev = run(IntegrationsStage(), scenario, connect=vuln, gaps=[])
    assert ev.score < ev.max_score
    assert any("CMDB" in q for q in ev.pushback)
    assert any("scanner line" in q for q in ev.pushback)


def test_integrations_rejects_forged_ids(scenario):
    answer, _ = run(IntegrationsStage(), scenario, connect=["not-a-source"], gaps=["nope"])
    assert answer == {"connect": [], "gaps": []}


def test_integrations_false_gap_is_challenged(repo):
    s = repo.get("prairie-freight")
    _, ev = run(IntegrationsStage(), s, connect=[x.id for x in s.sources], gaps=["build", "billing"])
    assert any("Billing DB" in q and "Tenable SC" in q for q in ev.pushback)


# ---- deployment ----------------------------------------------------------------------
def perfect_deployment(s):
    return dict(model=s.expected_deployment, targets=list(s.onprem_endpoints), direction="outbound")


def test_deployment_perfect(scenario):
    _, ev = run(DeploymentStage(), scenario, **perfect_deployment(scenario))
    assert_perfect(ev)


def test_deployment_saas_direct_with_internal_systems(repo):
    s = repo.get("prairie-freight")
    _, ev = run(DeploymentStage(), s, model="saas_direct")
    assert ev.score < ev.max_score
    assert any("inbound firewall" in q for q in ev.pushback)


def test_deployment_saas_in_federal_hits_constraint(repo):
    s = repo.get("regional-bureau")
    _, ev = run(DeploymentStage(), s, model="saas_collector", direction="outbound")
    assert any("ATO boundary" in q for q in ev.pushback)


def test_deployment_qualys_trap(repo):
    s = repo.get("prairie-freight")
    _, ev = run(DeploymentStage(), s, model="saas_collector",
                targets=["tenable", "jira-dc", "qualys"], direction="outbound")
    assert any("Qualys" in q and "API" in q for q in ev.pushback)


def test_deployment_inbound_challenged(repo):
    s = repo.get("prairie-freight")
    _, ev = run(DeploymentStage(), s, model="saas_collector", targets=["tenable", "jira-dc"], direction="inbound")
    assert any("firewall" in q for q in ev.pushback)


# ---- crown jewels --------------------------------------------------------------------
def test_crown_jewels_perfect(scenario):
    _, ev = run(CrownJewelsStage(), scenario, picks=list(scenario.crown_jewels))
    assert_perfect(ev)


def test_crown_jewels_everything_is_boiling_the_ocean(scenario):
    _, ev = run(CrownJewelsStage(), scenario, picks=[g.id for g in scenario.asset_groups])
    assert any("If everything is wave 1" in q for q in ev.pushback)


def test_crown_jewels_missing_internet_facing(repo):
    s = repo.get("harbor-lane")
    _, ev = run(CrownJewelsStage(), s, picks=["payments", "orderdb"])
    assert any("Storefront web is internet-facing" in q for q in ev.pushback)


# ---- risk ----------------------------------------------------------------------------
GOOD_RISK = dict(signals=["cvss", "kev", "epss", "exposure", "criticality"], kev_policy="targeted", p1_sla="7")


def test_risk_perfect(scenario):
    _, ev = run(RiskStage(), scenario, **GOOD_RISK)
    assert_perfect(ev)


def test_risk_cvss_only(scenario):
    _, ev = run(RiskStage(), scenario, signals=["cvss"], kev_policy="none", p1_sla="30")
    assert ev.percent < 30
    assert any("CVSS describes the flaw" in q for q in ev.pushback)


def test_risk_scanner_count_is_penalized(scenario):
    _, ev = run(RiskStage(), scenario, **{**GOOD_RISK, "signals": GOOD_RISK["signals"] + ["scanner_count"]})
    assert ev.score == ev.max_score - 1
    assert any("twice as likely" in q for q in ev.pushback)


# ---- ticketing -----------------------------------------------------------------------
def perfect_ticketing(s):
    return {"keys": ["remediation", "owner", "platform"], "fallback": "triage", "rollout": "pilot",
            **{f"route_{t.id}": t.works_in for t in s.teams}}


def test_ticketing_perfect(scenario):
    _, ev = run(TicketingStage(), scenario, **perfect_ticketing(scenario))
    assert_perfect(ev)


def test_ticketing_icmp_example(scenario):
    """Grouping by fix without platform puts the Windows and Linux fix in one ticket."""
    _, ev = run(TicketingStage(), scenario, **{**perfect_ticketing(scenario), "keys": ["remediation", "owner"]})
    assert any("ICMP" in q for q in ev.pushback)


def test_ticketing_per_asset_flood(scenario):
    _, ev = run(TicketingStage(), scenario, **{**perfect_ticketing(scenario), "keys": ["asset"]})
    assert any("ticket number 214" in q for q in ev.pushback)


def test_ticketing_skip_unowned(repo):
    s = repo.get("prairie-freight")
    _, ev = run(TicketingStage(), s, **{**perfect_ticketing(s), "fallback": "skip"})
    assert any("Legacy FTP" in q for q in ev.pushback)


def test_ticketing_misroute(repo):
    s = repo.get("prairie-freight")
    fields = perfect_ticketing(s)
    fields["route_Web-Platform"] = "snow"
    _, ev = run(TicketingStage(), s, **fields)
    assert any("Web-Platform works in Jira Data Center" in q for q in ev.pushback)
