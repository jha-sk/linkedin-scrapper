from linkedin_public_profile import FetchResult

from phantom.columns import empty_row
from phantom.scraper.engine import _rejection_reason

CLEAN = FetchResult(url="u", final_url="u", status=200, html="<html></html>", transport="http")


def good_row():
    row = empty_row()
    row["scraper_full_name"] = "Sourabh Jha"
    row["first_name"] = "Sourabh"
    row["linkedin_profile_slug"] = "sk-jha"
    return row


def test_a_complete_row_is_accepted():
    assert _rejection_reason(CLEAN, good_row()) is None


def test_block_status_is_rejected():
    blocked = FetchResult(url="u", final_url="u", status=999, html="", transport="http")
    reason = _rejection_reason(blocked, good_row())
    assert reason and "999" in reason


def test_session_shell_that_never_rendered_is_rejected():
    shell = FetchResult(
        url="u", final_url="u", status=200, html="<html></html>", transport="session"
    )
    reason = _rejection_reason(shell, good_row(), rendered=False)
    assert reason and "no profile content" in reason


def test_session_render_is_accepted():
    page = FetchResult(
        url="u", final_url="u", status=200, html="<html></html>", transport="session"
    )
    assert _rejection_reason(page, good_row(), rendered=True) is None


def test_sign_up_page_is_rejected_even_when_it_parses():
    row = good_row()
    row["scraper_full_name"] = "Sign Up"
    reason = _rejection_reason(CLEAN, row)
    assert reason and "sign-in wall" in reason


def test_row_without_identity_is_rejected():
    row = empty_row()
    assert "no identity fields" in (_rejection_reason(CLEAN, row) or "")


def test_row_without_a_slug_is_rejected():
    row = good_row()
    row["linkedin_profile_slug"] = None
    assert "no profile slug" in (_rejection_reason(CLEAN, row) or "")
