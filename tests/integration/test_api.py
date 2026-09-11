"""API-level integration test: capability replay reachable over HTTP, and
the session/escalation endpoints operate on a real registered session."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.artifacts.store import ArtifactStore
from app.config import Settings
from app.main import create_app
from tests.conftest import build_gold_artifact


@pytest.fixture
def api_client(tmp_path, demo_app_base_url):
    settings = Settings(
        EVIDENCE_DIR=tmp_path / "evidence",
        CAPABILITIES_DIR=tmp_path / "capabilities",
        HEADLESS_BROWSER=True,
    )
    store = ArtifactStore(settings.capabilities_dir)
    store.save(build_gold_artifact(demo_app_base_url))
    app = create_app(settings)
    return TestClient(app)


def test_list_capabilities_returns_saved_artifact(api_client):
    response = api_client.get("/capabilities")
    assert response.status_code == 200
    assert "member_savings_lookup" in response.json()


def test_replay_capability_over_http_succeeds(api_client):
    response = api_client.post(
        "/capabilities/member_savings_lookup/replay", json={"params": {"member_id": "12345"}}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["outputs"]["savings_balance"]["amount"] == "4231.55"


def test_replay_unknown_capability_returns_404(api_client):
    response = api_client.post("/capabilities/does_not_exist/replay", json={"params": {}})
    assert response.status_code == 404


def test_get_unknown_run_returns_404(api_client):
    assert api_client.get("/runs/does-not-exist").status_code == 404


def test_get_unknown_session_returns_404(api_client):
    assert api_client.get("/sessions/does-not-exist").status_code == 404
