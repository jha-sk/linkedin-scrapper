import os

import pytest

from phantom import browser


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in (
        "PHANTOM_BROWSER_EXECUTABLE",
        "PHANTOM_BROWSER_CHANNEL",
        "PHANTOM_HEADLESS",
        "PHANTOM_NO_SANDBOX",
        "DISPLAY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_default_channel_is_full_chromium_not_the_headless_shell():
    assert browser.choose(headless=True).channel == "chromium"


def test_executable_overrides_channel(monkeypatch, tmp_path):
    binary = tmp_path / "ungoogled-chromium"
    binary.write_text("#!/bin/sh\n")
    monkeypatch.setenv("PHANTOM_BROWSER_EXECUTABLE", str(binary))

    choice = browser.choose(headless=True)
    assert choice.executable_path == str(binary)
    kwargs = choice.launch_kwargs()
    assert kwargs["executable_path"] == str(binary)
    assert "channel" not in kwargs


def test_a_missing_executable_is_ignored_rather_than_crashing_at_launch(monkeypatch):
    monkeypatch.setenv("PHANTOM_BROWSER_EXECUTABLE", "/nope/does/not/exist")
    choice = browser.choose(headless=True)
    assert choice.executable_path is None
    assert choice.channel == "chromium"


def test_channel_can_be_disabled(monkeypatch):
    monkeypatch.setenv("PHANTOM_BROWSER_CHANNEL", "none")
    choice = browser.choose(headless=True)
    assert choice.channel is None
    assert "channel" not in choice.launch_kwargs()


def test_sandbox_flags_are_opt_in(monkeypatch):
    assert "--no-sandbox" not in browser.choose(headless=True).args

    monkeypatch.setenv("PHANTOM_NO_SANDBOX", "1")
    assert "--no-sandbox" in browser.choose(headless=True).args


def test_headed_without_a_display_falls_back_on_linux(monkeypatch):
    monkeypatch.setattr(browser, "_is_linux", lambda: True)
    assert browser.choose(headless=False).headless is True

    monkeypatch.setenv("DISPLAY", ":99")
    choice = browser.choose(headless=False)
    assert choice.headless is False
    assert choice.display == ":99"


def test_headless_env_var_is_respected(monkeypatch):
    monkeypatch.setattr(browser, "_is_linux", lambda: False)
    monkeypatch.setenv("PHANTOM_HEADLESS", "true")
    assert browser.choose().headless is True

    monkeypatch.setenv("PHANTOM_HEADLESS", "false")
    assert browser.choose().headless is False


def test_explicit_argument_beats_the_environment(monkeypatch):
    monkeypatch.setattr(browser, "_is_linux", lambda: False)
    monkeypatch.setenv("PHANTOM_HEADLESS", "true")
    assert browser.choose(headless=False).headless is False


def test_environment_report_is_serialisable():
    report = browser.environment_report()
    assert set(report) >= {"channel", "headless", "display", "xvfb_available", "summary"}
    assert isinstance(report["summary"], str)
