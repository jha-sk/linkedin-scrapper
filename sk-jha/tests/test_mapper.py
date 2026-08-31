from linkedin_public_profile import Profile

from phantom.columns import COLUMN_KEYS
from phantom.scraper.mapper import build_row, split_headline, split_name


def test_split_name():
    assert split_name("Sourabh Jha") == ("Sourabh", "Jha")
    assert split_name("Cher") == ("Cher", None)
    assert split_name("  Ana Maria  Lopez ") == ("Ana", "Maria Lopez")
    assert split_name(None) == (None, None)


def test_split_headline():
    assert split_headline("Staff Engineer at Northwind") == ("Staff Engineer", "Northwind")
    assert split_headline("Backend Engineer @ Acme | Go") == ("Backend Engineer", "Acme")
    assert split_headline("Open to work") == (None, None)


def test_row_always_has_every_column():
    row, _ = build_row(input_url="https://www.linkedin.com/in/x/", profile=None, voyager=None)
    assert set(row) == set(COLUMN_KEYS)


def test_voyager_wins_over_public_page():
    profile = Profile(name="Public Name", headline="Public headline")
    voyager = {"first_name": "Session", "last_name": "Name", "linkedin_headline": "Session headline"}
    row, provenance = build_row(
        input_url="https://www.linkedin.com/in/x/", profile=profile, voyager=voyager
    )
    assert row["first_name"] == "Session"
    assert row["linkedin_headline"] == "Session headline"
    assert provenance["first_name"] == "voyager"
    assert row["scraper_full_name"] == "Public Name"
    assert provenance["scraper_full_name"] == "public"


def test_derived_layer_only_fills_gaps():
    profile = Profile(name="A B", headline="Staff Engineer at Northwind")
    row, provenance = build_row(
        input_url="https://www.linkedin.com/in/x/", profile=profile, voyager=None
    )
    assert row["linkedin_job_title"] == "Staff Engineer"
    assert provenance["linkedin_job_title"] == "derived"

    row2, provenance2 = build_row(
        input_url="https://www.linkedin.com/in/x/",
        profile=profile,
        voyager={"linkedin_job_title": "Associate Software Engineer"},
    )
    assert row2["linkedin_job_title"] == "Associate Software Engineer"
    assert provenance2["linkedin_job_title"] == "voyager"


def test_connection_urls_derive_from_urn():
    row, _ = build_row(
        input_url="https://www.linkedin.com/in/x/",
        profile=None,
        voyager={"linkedin_profile_urn": "ACoAADe92ckBElZ"},
    )
    assert "ACoAADe92ckBElZ" in row["connections_url"]
    assert "ACoAADe92ckBElZ" in row["mutual_connections_url"]


def test_runner_owned_fields_are_forced():
    row, provenance = build_row(
        input_url="https://www.linkedin.com/in/x/",
        profile=None,
        voyager={"profile_url": "https://spoofed.example/"},
    )
    assert row["profile_url"] == "https://www.linkedin.com/in/x/"
    assert provenance["profile_url"] == "runner"
    assert row["refreshed_at"]
