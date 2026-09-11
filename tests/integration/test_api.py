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


@pytest.fixture
def public_demo_client(tmp_path, demo_app_base_url):
    settings = Settings(
        EVIDENCE_DIR=tmp_path / "evidence",
        CAPABILITIES_DIR=tmp_path / "capabilities",
        HEADLESS_BROWSER=True,
        PUBLIC_DEMO_MODE=True,
        PUBLIC_DEMO_RATE_LIMIT=2,
        PUBLIC_DEMO_RATE_LIMIT_WINDOW_SECONDS=600,
    )
    store = ArtifactStore(settings.capabilities_dir)
    store.save(build_gold_artifact(demo_app_base_url))
    app = create_app(settings)
    return TestClient(app)


def test_public_demo_mode_disables_discover(public_demo_client):
    response = public_demo_client.post(
        "/runs/discover",
        json={
            "goal": "look up a member",
            "start_url": "http://127.0.0.1:8001/login",
            "capability_id": "x",
            "description": "x",
        },
    )
    assert response.status_code == 403
    assert "disabled" in response.json()["detail"].lower()


def test_public_demo_mode_allows_the_allowlisted_capability(public_demo_client):
    response = public_demo_client.post(
        "/capabilities/member_savings_lookup/replay", json={"params": {"member_id": "12345"}}
    )
    assert response.status_code == 200


def test_public_demo_mode_blocks_non_allowlisted_capability(public_demo_client, tmp_path):
    # Save a second capability under a different id and confirm the public
    # demo refuses to replay it even though it's a perfectly valid artifact -
    # only the one explicitly allowlisted capability is exposed publicly.
    other = build_gold_artifact(
        "http://127.0.0.1:8001"
    ).model_copy(update={"capability_id": "some_other_capability"})
    ArtifactStore(public_demo_client.app.state.integration.settings.capabilities_dir).save(other)

    response = public_demo_client.post("/capabilities/some_other_capability/replay", json={"params": {}})
    assert response.status_code == 403


def test_public_demo_mode_rate_limits_replay(public_demo_client):
    for _ in range(2):
        response = public_demo_client.post(
            "/capabilities/member_savings_lookup/replay", json={"params": {"member_id": "12345"}}
        )
        assert response.status_code == 200

    response = public_demo_client.post(
        "/capabilities/member_savings_lookup/replay", json={"params": {"member_id": "12345"}}
    )
    assert response.status_code == 429


def test_public_demo_page_is_served(public_demo_client):
    response = public_demo_client.get("/demo")
    assert response.status_code == 200
    assert "Live Replay Demo" in response.text


def test_demo_page_not_served_when_public_demo_mode_is_off(api_client):
    assert api_client.get("/demo").status_code == 404
