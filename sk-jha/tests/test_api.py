import pytest
from fastapi.testclient import TestClient

from phantom.db import init_db
from phantom.main import app


@pytest.fixture(scope="module")
def client():
    init_db()
    with TestClient(app) as test_client:
        yield test_client


def test_columns_endpoint_matches_the_contract(client):
    response = client.get("/api/columns")
    assert response.status_code == 200
    columns = response.json()
    keys = [column["key"] for column in columns]

    assert keys[0] == "company_industry"
    assert keys[39] == "email_status"

    assert len(columns) > 40
    for extra in ("linkedin_about", "linkedin_certifications", "linkedin_sections_json"):
        assert extra in keys


def test_agent_lifecycle(client):
    created = client.post("/api/agents", json={"name": "Fixture agent"})
    assert created.status_code == 201
    agent = created.json()
    assert agent["is_configured"] is False

    updated = client.patch(
        f"/api/agents/{agent['id']}",
        json={"input_source": "url", "input_url": "https://www.linkedin.com/in/sk-jha"},
    )
    assert updated.status_code == 200
    assert updated.json()["input_url"] == "https://www.linkedin.com/in/sk-jha/"
    assert updated.json()["is_configured"] is True

    assert client.delete(f"/api/agents/{agent['id']}").status_code == 204
    assert client.get(f"/api/agents/{agent['id']}").status_code == 404


def test_bad_profile_url_is_rejected(client):
    response = client.post(
        "/api/agents", json={"input_source": "url", "input_url": "https://example.com/in/nope"}
    )
    assert response.status_code == 422


def test_cookies_are_never_stored_per_agent(client):
    """
    Sessions are machine-wide, never per agent.

    Pasted cookies live at `/api/session/cookies` and are shared by every agent:
    one account, one identity. Per-agent cookies would mean the same account
    presented from several inconsistent identities, which is the pattern that
    gets sessions invalidated — so those endpoints are gone, not deprecated.
    """
    agent = client.post("/api/agents", json={"name": "Secrets"}).json()
    secret = "AQEDATotallyNotARealCookieValue123456"

    assert client.put(f"/api/agents/{agent['id']}/session", json={"li_at": secret}).status_code == 405
    assert client.delete(f"/api/agents/{agent['id']}/session").status_code == 405

    patched = client.patch(f"/api/agents/{agent['id']}", json={"session_cookie": secret})
    assert patched.status_code == 200
    assert secret not in client.get(f"/api/agents/{agent['id']}").text


def test_session_status_reports_the_shared_browser_profile(client):
    body = client.get("/api/session").json()
    assert set(body) >= {"exists", "logged_in", "summary", "profile_dir"}
    assert body["logged_in"] is False
    assert "phantom.session login" in body["summary"]


def test_launching_an_unconfigured_agent_is_refused(client):
    agent = client.post("/api/agents", json={"name": "Empty"}).json()
    response = client.post(f"/api/agents/{agent['id']}/launch")
    assert response.status_code == 409
    assert "no input configured" in response.json()["detail"]


def test_email_provider_requires_a_key(client):
    agent = client.post("/api/agents", json={"name": "Email"}).json()
    response = client.put(
        f"/api/agents/{agent['id']}/email-provider", json={"provider": "hunter", "api_key": None}
    )
    assert response.status_code == 422


def test_csv_export_has_the_full_header(client):
    from phantom.columns import COLUMNS

    agent = client.post("/api/agents", json={"name": "Export"}).json()
    response = client.get(f"/api/agents/{agent['id']}/export.csv")
    assert response.status_code == 200
    header = response.text.splitlines()[0]
    assert header.startswith("Company Industry,Company Name,First Name,Last Name")
    assert header.split(",") == [column.label for column in COLUMNS]



FULL_COOKIES = (
    'li_at=AQEDSecretSessionValue123456; JSESSIONID="ajax:99"; '
    "bcookie=v=2&abc; bscookie=v=1&def; liap=true"
)


def test_cookie_upload_stores_and_grades(client):
    response = client.put(
        "/api/session/cookies",
        json={"raw": FULL_COOKIES, "user_agent": "Mozilla/5.0 Test"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["grade"] == "complete"
    assert body["count"] == 5
    assert "AQEDSecretSessionValue123456" not in response.text


def test_stored_cookie_values_are_never_returned(client):
    client.put("/api/session/cookies", json={"raw": FULL_COOKIES})
    assert "AQEDSecretSessionValue123456" not in client.get("/api/session").text


def test_session_status_reports_the_cookie_source(client):
    client.put("/api/session/cookies", json={"raw": FULL_COOKIES})
    body = client.get("/api/session").json()
    assert body["source"] == "cookies"
    assert body["grade"] == "complete"
    assert body["logged_in"] is True


def test_upload_without_a_session_cookie_is_refused(client):
    response = client.put("/api/session/cookies", json={"raw": "bcookie=v=2&abc; lang=en"})
    assert response.status_code == 422
    assert "li_at" in response.json()["detail"]


def test_preview_grades_without_storing(client):
    client.delete("/api/session/cookies")
    body = client.post(
        "/api/session/cookies/preview", json={"raw": "AQEDBareTokenOnly1234567890"}
    ).json()
    assert body["grade"] == "minimal"
    assert client.get("/api/session").json()["source"] != "cookies"


def test_uploading_without_a_user_agent_warns(client):
    body = client.put("/api/session/cookies", json={"raw": FULL_COOKIES}).json()
    assert any("user agent" in warning for warning in body["warnings"])


def test_cookies_can_be_removed(client):
    client.put("/api/session/cookies", json={"raw": FULL_COOKIES})
    assert client.delete("/api/session/cookies").status_code == 204
    assert client.get("/api/session").json()["source"] != "cookies"


