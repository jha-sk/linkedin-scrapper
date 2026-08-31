import pytest
from fastapi.testclient import TestClient

from phantom import auth
from phantom.config import Settings


def _settings(**overrides):
    base = dict(host="127.0.0.1", api_token="", allowed_origins="")
    base.update(overrides)
    return Settings(**base)


def test_loopback_without_a_token_is_allowed(monkeypatch):
    monkeypatch.setattr(auth, "settings", _settings())
    auth.verify_startup()


def test_public_bind_without_a_token_refuses_to_start(monkeypatch):
    """
    The failure this prevents: an open port where every endpoint is privileged.

    Reachable-and-unauthenticated is a state people arrive at by forgetting a
    variable, not one they choose, so it fails loudly at deploy time instead of
    silently serving.
    """
    monkeypatch.setattr(auth, "settings", _settings(host="0.0.0.0"))
    with pytest.raises(auth.InsecureConfiguration) as excinfo:
        auth.verify_startup()
    assert "PHANTOM_API_TOKEN" in str(excinfo.value)


def test_public_bind_with_a_short_token_is_refused(monkeypatch):
    monkeypatch.setattr(auth, "settings", _settings(host="0.0.0.0", api_token="short"))
    with pytest.raises(auth.InsecureConfiguration):
        auth.verify_startup()


def test_public_bind_with_a_real_token_is_accepted(monkeypatch):
    monkeypatch.setattr(
        auth, "settings", _settings(host="0.0.0.0", api_token="x" * 32)
    )
    auth.verify_startup()



TOKEN = "t" * 40


@pytest.fixture
def guarded(monkeypatch):
    from phantom.db import init_db
    from phantom.main import app

    monkeypatch.setattr(auth, "settings", _settings(api_token=TOKEN))
    init_db()
    with TestClient(app) as client:
        yield client


def test_api_requires_the_token(guarded):
    assert guarded.get("/api/columns").status_code == 401


def test_bearer_header_is_accepted(guarded):
    response = guarded.get("/api/columns", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200


def test_wrong_token_is_rejected(guarded):
    response = guarded.get("/api/columns", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401


def test_query_parameter_works_for_the_event_stream(guarded):
    assert guarded.get(f"/api/columns?token={TOKEN}").status_code == 200


def test_healthz_stays_open_for_monitoring(guarded):
    assert guarded.get("/healthz").status_code == 200
