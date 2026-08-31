import tarfile

import pytest

from phantom import session


@pytest.fixture
def profile(tmp_path, monkeypatch):
    """A stand-in browser profile directory."""
    directory = tmp_path / "browser-profile"
    directory.mkdir()
    (directory / "Cookies").write_bytes(b"not-a-real-cookie-jar")
    (directory / "Preferences").write_text("{}")
    monkeypatch.setattr(session, "PROFILE_DIR", directory)
    return directory


def test_export_then_import_round_trips(profile, tmp_path, monkeypatch):
    archive = tmp_path / "session.tar.gz"
    assert session.export_profile(archive) == 0
    assert archive.exists()

    assert oct(archive.stat().st_mode)[-3:] == "600"

    import shutil

    shutil.rmtree(profile)
    monkeypatch.setattr(session, "status", lambda headless=True: session.ProfileStatus(
        exists=True, logged_in=True, cookie_names=["li_at"]
    ))
    assert session.import_profile(archive) == 0
    assert (profile / "Cookies").read_bytes() == b"not-a-real-cookie-jar"


def test_import_refuses_to_clobber_without_force(profile, tmp_path):
    archive = tmp_path / "session.tar.gz"
    session.export_profile(archive)
    assert session.import_profile(archive) == 1


def test_export_without_a_profile_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(session, "PROFILE_DIR", tmp_path / "absent")
    assert session.export_profile(tmp_path / "out.tar.gz") == 1


def test_archive_members_escaping_the_target_are_rejected(tmp_path, monkeypatch):
    """A tar entry may carry `..` or an absolute path and land anywhere writable."""
    evil = tmp_path / "evil.tar.gz"
    victim = tmp_path / "payload.txt"
    victim.write_text("owned")
    with tarfile.open(evil, "w:gz") as archive:
        archive.add(victim, arcname="../../escaped.txt")

    with tarfile.open(evil, "r:gz") as archive:
        members = archive.getmembers()
    assert members and all(not session._is_safe_member(m) for m in members)




def test_push_refuses_plaintext_http_to_a_remote_host(monkeypatch):
    """These cookies are a credential; plain HTTP would put them on the wire."""
    monkeypatch.setattr(
        session,
        "collect_local_identity",
        lambda headless=True: {
            "cookies": [{"name": "li_at", "value": "secret", "domain": ".linkedin.com"}],
            "user_agent": "UA",
            "locale": "en-US",
            "timezone": "UTC",
            "viewport_width": 1440,
            "viewport_height": 900,
        },
    )

    def explode(*args, **kwargs):
        raise AssertionError("push must not send anything over plain HTTP")

    monkeypatch.setattr(session.__dict__.setdefault("httpx", type("x", (), {})()), "put", explode, raising=False)
    assert session.push("http://scraper.example.com", token="t") == 2


def test_push_allows_plaintext_to_loopback(monkeypatch):
    """A tunnel to localhost never leaves the machine, so it is not the same risk."""
    sent = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"grade": "complete", "warnings": []}

    class FakeHttpx:
        HTTPError = Exception

        @staticmethod
        def put(url, json=None, headers=None, timeout=None):
            sent["url"] = url
            sent["auth"] = (headers or {}).get("Authorization")
            return FakeResponse()

    monkeypatch.setitem(__import__("sys").modules, "httpx", FakeHttpx)
    monkeypatch.setattr(
        session,
        "collect_local_identity",
        lambda headless=True: {
            "cookies": [{"name": "li_at", "value": "secret", "domain": ".linkedin.com"}],
            "user_agent": "UA",
            "locale": "en-US",
            "timezone": "UTC",
            "viewport_width": 1440,
            "viewport_height": 900,
        },
    )
    assert session.push("http://127.0.0.1:8000", token="tok") == 0
    assert sent["url"] == "http://127.0.0.1:8000/api/session/cookies"
    assert sent["auth"] == "Bearer tok"


def test_push_without_a_local_session_is_an_error(monkeypatch):
    monkeypatch.setattr(session, "collect_local_identity", lambda headless=True: None)
    assert session.push("https://scraper.example.com", token="t") == 1


def test_export_cookies_without_a_local_session_is_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(session, "collect_local_identity", lambda headless=True: None)
    assert session.export_cookies(tmp_path / "cookies.json") == 1
