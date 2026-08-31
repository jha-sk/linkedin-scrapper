"""
Output column contract.

The result table is a flat, ordered, stable set of columns. Everything the
runner produces is keyed by these names, and CSV export writes them in this
order. Adding a column is additive; renaming or reordering one is a breaking
change to every downstream consumer, so the list lives here alone and nothing
else hard-codes a column name.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    kind: str = "text"


COLUMNS: tuple[Column, ...] = (
    Column("company_industry", "Company Industry"),
    Column("company_name", "Company Name"),
    Column("first_name", "First Name"),
    Column("last_name", "Last Name"),
    Column("linkedin_company_url", "Linkedin Company Url", "url"),
    Column("linkedin_company_slug", "Linkedin Company Slug"),
    Column("linkedin_company_id", "Linkedin Company Id"),
    Column("linkedin_description", "Linkedin Description"),
    Column("linkedin_followers_count", "Linkedin Followers Count", "int"),
    Column("linkedin_headline", "Linkedin Headline"),
    Column("linkedin_is_hiring_badge", "Linkedin Is Hiring Badge", "bool"),
    Column("linkedin_is_open_to_work_badge", "Linkedin Is Open To Work Badge", "bool"),
    Column("linkedin_job_date_range", "Linkedin Job Date Range"),
    Column("linkedin_job_description", "Linkedin Job Description"),
    Column("linkedin_job_location", "Linkedin Job Location"),
    Column("linkedin_job_title", "Linkedin Job Title"),
    Column("linkedin_profile_id", "Linkedin Profile Id"),
    Column("linkedin_profile_slug", "Linkedin Profile Slug"),
    Column("linkedin_profile_url", "Linkedin Profile Url", "url"),
    Column("linkedin_profile_urn", "Linkedin Profile Urn"),
    Column("linkedin_profile_image_urn", "Linkedin Profile Image Urn"),
    Column("linkedin_profile_image_url", "Linkedin Profile Image Url", "url"),
    Column("linkedin_school_url", "Linkedin School Url", "url"),
    Column("linkedin_school_company_slug", "Linkedin School Company Slug"),
    Column("linkedin_school_date_range", "Linkedin School Date Range"),
    Column("linkedin_school_degree", "Linkedin School Degree"),
    Column("linkedin_school_field_of_study", "Linkedin School Field Of Study"),
    Column("linkedin_school_name", "Linkedin School Name"),
    Column("linkedin_skills_label", "Linkedin Skills Label"),
    Column("location", "Location"),
    Column("connection_degree", "Connection Degree"),
    Column("refreshed_at", "Refreshed At", "datetime"),
    Column("mutual_connections_url", "Mutual Connections Url", "url"),
    Column("connections_url", "Connections Url", "url"),
    Column("linkedin_connections_count", "Linkedin Connections Count", "int"),
    Column("profile_url", "Profile Url", "url"),
    Column("scraper_profile_id", "Scraper Profile Id"),
    Column("scraper_full_name", "Scraper Full Name"),
    Column("email", "Email"),
    Column("email_status", "Email Status"),
    Column("linkedin_about", "Linkedin About"),
    Column("linkedin_certifications", "Linkedin Certifications"),
    Column("linkedin_projects", "Linkedin Projects"),
    Column("linkedin_interests", "Linkedin Interests"),
    Column("linkedin_languages", "Linkedin Languages"),
    Column("linkedin_honors", "Linkedin Honors"),
    Column("linkedin_volunteering", "Linkedin Volunteering"),
    Column("linkedin_publications", "Linkedin Publications"),
    Column("linkedin_courses", "Linkedin Courses"),
    Column("linkedin_organizations", "Linkedin Organizations"),
    Column("linkedin_recommendations", "Linkedin Recommendations"),
    Column("linkedin_top_skills", "Linkedin Top Skills"),
    Column("linkedin_background_image_url", "Linkedin Background Image Url", "url"),
    Column("linkedin_experience_json", "Linkedin Experience Json", "json"),
    Column("linkedin_education_json", "Linkedin Education Json", "json"),
    Column("linkedin_certifications_json", "Linkedin Certifications Json", "json"),
    Column("linkedin_projects_json", "Linkedin Projects Json", "json"),
    Column("linkedin_languages_json", "Linkedin Languages Json", "json"),
    Column("linkedin_skills_json", "Linkedin Skills Json", "json"),
    Column("linkedin_skills_count", "Linkedin Skills Count", "int"),
    Column("linkedin_experience_count", "Linkedin Experience Count", "int"),
    Column("linkedin_education_count", "Linkedin Education Count", "int"),
    Column("linkedin_sections_json", "Linkedin Sections Json", "json"),
)

COLUMN_KEYS: tuple[str, ...] = tuple(c.key for c in COLUMNS)
COLUMN_LABELS: tuple[str, ...] = tuple(c.label for c in COLUMNS)
BY_KEY: dict[str, Column] = {c.key: c for c in COLUMNS}


def empty_row() -> dict[str, object]:
    """A row with every column present and null — never emit a ragged record."""
    return {key: None for key in COLUMN_KEYS}
