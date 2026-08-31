from linkedin_public_profile import FetchResult

from phantom.scraper.fetcher import authwall_reason, redirected_to_auth

PROFILE = "https://www.linkedin.com/in/sk-jha/"


def result(**kwargs):
    base = dict(
        url=PROFILE, final_url=PROFILE, status=200, html="<html></html>", transport="session"
    )
    base.update(kwargs)
    return FetchResult(**base)


SIGNED_IN_HTML = """
<html><head>
<link rel="canonical" href="https://www.linkedin.com/in/sk-jha">
<script>window.config={"authwallUrl":"/authwall","loginUrl":"/login"}</script>
</head><body>
<p>Sign in to view more profiles</p>
<code>{"included":[{"$type":"...Profile","publicIdentifier":"sk-jha"}]}</code>
</body></html>
"""


def test_signed_in_page_containing_marker_strings_is_not_a_wall():
    """
    The original regression: a real signed-in render contains the marker strings
    the logged-out detector looks for, and sniffing them threw good scrapes away.
    Evidence of a render outranks the presence of a string.
    """
    assert result(html=SIGNED_IN_HTML).blocked is True
    assert authwall_reason(result(html=SIGNED_IN_HTML), "sk-jha", rendered=True) is None


def test_session_page_that_never_rendered_is_a_wall():
    reason = authwall_reason(result(html="<html><body>shell</body></html>"), "sk-jha", rendered=False)
    assert reason and "no profile content" in reason


def test_session_page_bounced_to_login_reports_the_profile_is_signed_out():
    reason = authwall_reason(
        result(final_url="https://www.linkedin.com/authwall", html=""), "sk-jha", rendered=False
    )
    assert reason and "/authwall" in reason


def test_redirect_to_authwall_is_a_wall():
    reason = authwall_reason(
        result(final_url="https://www.linkedin.com/authwall?trk=gf", html=SIGNED_IN_HTML)
    )
    assert reason and "/authwall" in reason


def test_redirect_to_login_is_a_wall():
    reason = authwall_reason(
        result(final_url="https://www.linkedin.com/uas/login?session_redirect=x")
    )
    assert reason and "login" in reason


def test_block_status_is_a_wall():
    reason = authwall_reason(result(status=999))
    assert reason and "999" in reason


def test_logged_out_transport_still_uses_marker_detection():
    walled = result(
        transport="http",
        html='<html><body><div class="authwall-join-form">Join LinkedIn to see</div></body></html>',
    )
    assert authwall_reason(walled) == "LinkedIn served the sign-in wall"

    clean = result(transport="http", html="<html><body><h1>A profile</h1></body></html>")
    assert authwall_reason(clean) is None


def test_redirected_to_auth_helper():
    assert redirected_to_auth("https://www.linkedin.com/authwall") is True
    assert redirected_to_auth("https://www.linkedin.com/checkpoint/challenge/") is True
    assert redirected_to_auth(PROFILE) is False
