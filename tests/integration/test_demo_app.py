"""Direct checks on the demo application's business rules, independent of
the automation layer - using FastAPI's TestClient rather than a browser."""

from __future__ import annotations

from fastapi.testclient import TestClient

from demo_app.app import app


def _authenticated_client() -> TestClient:
    client = TestClient(app)
    client.post("/login", data={"username": "op", "password": "pw"})
    return client


def test_unauthenticated_dashboard_redirects_to_login():
    client = TestClient(app)
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 303
    assert "/login" in response.headers["location"]


def test_search_returns_matching_member():
    client = _authenticated_client()
    response = client.post("/members/search", data={"member_id": "67890"})
    assert response.status_code == 200
    assert "Priya Natarajan" in response.text


def test_search_nonexistent_member_shows_no_results_banner():
    client = _authenticated_client()
    response = client.post("/members/search", data={"member_id": "00001"})
    assert response.status_code == 200
    assert "No members found" in response.text


def test_error_trigger_member_returns_500():
    client = _authenticated_client()
    response = client.post("/members/search", data={"member_id": "40404"})
    assert response.status_code == 500
    assert "unexpected error" in response.text.lower()


def test_transfer_funds_actually_moves_money_when_invoked_directly():
    """The risky action is real, not a stub - it's the SAFETY POLICY that
    stops automation from reaching it, not a missing implementation."""

    client = _authenticated_client()
    before = client.get("/members/13579").text
    assert "0.00" in before

    response = client.post(
        "/members/13579/transfer", data={"amount": "25.00"}, follow_redirects=True
    )
    assert response.status_code == 200
    assert "25.00" in response.text

    # Restore state so this test is repeatable / doesn't leak into others.
    client.post("/members/13579/transfer", data={"amount": "-25.00"})
