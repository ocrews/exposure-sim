"""The web layer, driven through Flask's test client like a browser would."""
import pytest

from exposure_sim import create_app
from exposure_sim.progress import MemoryStore, Progress, SessionStore


@pytest.fixture
def client():
    app = create_app({"TESTING": True, "SECRET_KEY": "test"})
    return app.test_client()


def test_index_lists_scenarios(client):
    html = client.get("/").get_data(as_text=True)
    for name in ("Harbor Lane Outfitters", "Prairie Freight Co.", "Bureau of Regional Logistics"):
        assert name in html


def test_unknown_scenario_and_stage_404(client):
    assert client.get("/play/nope").status_code == 404
    assert client.get("/play/harbor-lane/nope").status_code == 404


def test_play_redirects_to_first_stage(client):
    r = client.get("/play/harbor-lane")
    assert r.status_code == 302 and r.headers["Location"].endswith("/play/harbor-lane/integrations")


def test_stage_page_renders_map_and_form(client):
    html = client.get("/play/prairie-freight/integrations").get_data(as_text=True)
    assert "<svg" in html and 'data-id="tenable"' in html
    assert 'name="connect" value="tenable"' in html
    assert "Customer briefing" in html


def test_later_stage_is_gated(client):
    r = client.get("/play/harbor-lane/deployment")
    assert r.status_code == 302


def test_weak_answer_shows_pushback_and_stays_unlocked(client):
    r = client.post("/play/harbor-lane/integrations", data={"connect": ["wiz"], "action": "check"})
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "Before you lock this in" in html and "Lock in anyway" in html
    assert 'value="wiz" checked' in html                      # the draft is kept in the form
    assert client.get("/play/harbor-lane/deployment").status_code == 302


def test_lock_anyway_then_next_stage_opens(client):
    r = client.post("/play/harbor-lane/integrations", data={"connect": ["wiz"], "action": "lock"})
    assert r.status_code == 302
    html = client.get("/play/harbor-lane/integrations").get_data(as_text=True)
    assert "Questions you locked in past" in html and "fieldset disabled" in html
    assert client.get("/play/harbor-lane/deployment").status_code == 200


def test_strong_answer_locks_without_pushback(client):
    data = {"connect": ["wiz", "snyk", "falcon", "snow-cmdb"], "gaps": ["iot"], "action": "check"}
    r = client.post("/play/harbor-lane/integrations", data=data)
    assert r.status_code == 302
    html = client.get("/play/harbor-lane/integrations").get_data(as_text=True)
    assert "100%" in html and "no scanner" in html                 # gap revealed on the map


def test_redo_reopens_later_stages(client):
    client.post("/play/harbor-lane/integrations", data={"connect": ["wiz"], "action": "lock"})
    client.post("/play/harbor-lane/integrations/retry")
    assert client.get("/play/harbor-lane/deployment").status_code == 302


def test_reset_clears_progress(client):
    client.post("/play/harbor-lane/integrations", data={"connect": ["wiz"], "action": "lock"})
    client.post("/play/harbor-lane/reset")
    assert client.get("/play/harbor-lane").headers["Location"].endswith("/integrations")


def test_topology_json(client):
    data = client.get("/play/prairie-freight/topology.json").get_json()
    assert {n["id"] for n in data["nodes"]} >= {"tenable", "billing", "jira-dc"}


def test_memory_store_is_a_drop_in_replacement():
    """The storage seam: swap the store, nothing else changes."""
    app = create_app({"TESTING": True, "SECRET_KEY": "test"}, store=None)
    from flask import session
    app.extensions["progress"] = MemoryStore(lambda: session)
    c = app.test_client()
    c.post("/play/harbor-lane/integrations", data={"connect": ["wiz"], "action": "lock"})
    assert c.get("/play/harbor-lane/deployment").status_code == 200
    with c.session_transaction() as s:
        assert "p" not in s and "uid" in s                           # progress isn't in the cookie


def test_progress_roundtrip():
    p = Progress()
    p.answers["x"] = {"a": [1]}
    p.lock("x")
    p.lock("x")
    assert Progress.from_dict(p.to_dict()).locked == ["x"]
    p.unlock_from(["x"])
    assert p.locked == []


def test_session_store_isolated_per_scenario():
    data = {}
    store = SessionStore(lambda: data)
    a = Progress(locked=["integrations"])
    store.save("one", a)
    assert store.load("two").locked == []
    assert store.load("one").locked == ["integrations"]


def test_warns_when_secret_missing(monkeypatch, caplog):
    monkeypatch.delenv("EXPOSURE_SIM_SECRET", raising=False)
    with caplog.at_level("WARNING"):
        create_app()
    assert any("EXPOSURE_SIM_SECRET is not set" in r.message for r in caplog.records)


def test_secret_from_environment(monkeypatch):
    monkeypatch.setenv("EXPOSURE_SIM_SECRET", "abc123")
    assert create_app().config["SECRET_KEY"] == "abc123"
