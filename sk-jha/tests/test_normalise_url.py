import pytest

from phantom.scraper.engine import normalise_url

CANONICAL = "https://www.linkedin.com/in/sk-jha/"


@pytest.mark.parametrize(
    "raw",
    [
        "https://www.linkedin.com/in/sk-jha",
        "https://www.linkedin.com/in/sk-jha/",
        "https://linkedin.com/in/sk-jha?trk=public_profile",
        "http://in.linkedin.com/in/sk-jha/",
        "linkedin.com/in/sk-jha",
        "  https://www.linkedin.com/in/sk-jha/  ",
        "sk-jha",
    ],
)
def test_variants_collapse_to_one_canonical_form(raw):
    assert normalise_url(raw) == CANONICAL


@pytest.mark.parametrize("raw", ["", "   ", "https://example.com/in/nope"])
def test_non_profile_input_is_rejected(raw):
    with pytest.raises(ValueError):
        normalise_url(raw)


def test_company_url_is_not_a_profile():
    with pytest.raises(ValueError):
        normalise_url("https://www.linkedin.com/company/accenture/")
