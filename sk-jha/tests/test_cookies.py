from phantom import cookies

FULL_HEADER = (
    'li_at=AQEDAaaaaaaaaaaaaaaaaaa; JSESSIONID="ajax:1234567890"; '
    "bcookie=v=2&abcdef; bscookie=v=1&ghijkl; liap=true; lidc=b=OGST00:s=O; lang=v=2&lang=en-us"
)


def test_header_string_is_parsed():
    parsed = cookies.parse(FULL_HEADER)
    assert parsed.has_session
    assert "JSESSIONID" in parsed.names
    value = next(c["value"] for c in parsed.cookies if c["name"] == "JSESSIONID")
    assert value == "ajax:1234567890"


def test_a_complete_set_grades_complete():
    assert cookies.parse(FULL_HEADER).grade == "complete"


def test_a_bare_token_grades_minimal_and_says_so():
    parsed = cookies.parse("AQEDAaaaaaaaaaaaaaaaaaaaaaaaaaa")
    assert parsed.has_session
    assert parsed.grade == "minimal"
    assert "signed out" in parsed.advice
    assert parsed.warnings


def test_missing_a_couple_of_device_cookies_grades_partial():
    parsed = cookies.parse("li_at=AQEDAaaaaaaaaaaaaaaaaaa; bcookie=v=2&abc; bscookie=v=1&def")
    assert parsed.grade == "partial"
    assert "JSESSIONID" in parsed.missing_important


def test_input_without_a_session_cookie_is_unusable():
    parsed = cookies.parse("bcookie=v=2&abc; lang=en")
    assert parsed.has_session is False
    assert parsed.grade == "unusable"


def test_json_export_from_an_extension_is_parsed():
    payload = """
    [
      {"name": "li_at", "value": "AQEDAaaa", "domain": ".linkedin.com", "path": "/",
       "httpOnly": true, "secure": true, "sameSite": "no_restriction",
       "expirationDate": 1799999999.5},
      {"name": "bcookie", "value": "v=2&x", "domain": ".linkedin.com", "path": "/"}
    ]
    """
    parsed = cookies.parse(payload)
    assert parsed.names == {"li_at", "bcookie"}
    prepared = {c["name"]: c for c in parsed.to_playwright()}
    assert prepared["li_at"]["httpOnly"] is True
    assert prepared["li_at"]["expires"] == 1799999999.5
    assert "sameSite" not in prepared["li_at"]


def test_cookies_for_other_sites_are_dropped_not_forwarded():
    """A whole-browser export contains everything; other sites' sessions are not ours to take."""
    payload = """
    [
      {"name": "li_at", "value": "AQEDAaaa", "domain": ".linkedin.com"},
      {"name": "SID", "value": "secret", "domain": ".google.com"},
      {"name": "session", "value": "secret", "domain": ".bank.example"}
    ]
    """
    parsed = cookies.parse(payload)
    assert parsed.names == {"li_at"}
    assert any("google" in w for w in parsed.warnings)


def test_name_value_mapping_is_accepted():
    parsed = cookies.parse('{"li_at": "AQEDAaaa", "bcookie": "v=2&x"}')
    assert parsed.names == {"li_at", "bcookie"}


def test_garbage_input_is_reported_not_guessed():
    parsed = cookies.parse("hello there")
    assert not parsed.has_session
    assert parsed.warnings


def test_summary_never_contains_a_cookie_value():
    parsed = cookies.parse(FULL_HEADER)
    assert "AQEDAaaaaaaaaaaaaaaaaaa" not in str(parsed.summary())


def test_playwright_shape_defaults_domain_and_path():
    entry = cookies.parse("li_at=AQEDAaaa").to_playwright()[0]
    assert entry["domain"] == ".linkedin.com"
    assert entry["path"] == "/"
