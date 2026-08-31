"""
Maps extractor output onto the 40-column result contract.

Two inputs, different precedence:

  voyager   authenticated model store. Typed, identity-bearing, highest trust.
  profile   the public-page `Profile` dataclass from the logged-out scraper.
            Coarser — a headline blob rather than separated fields — so it only
            ever fills gaps the session view left.

First writer wins, and the writer is recorded per field. That is what makes
"LinkedIn changed their markup" distinguishable from "this profile has no
education section" when a column comes back empty.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from linkedin_public_profile import Profile

from ..columns import COLUMN_KEYS, empty_row

_AT_SPLIT_RE = re.compile(r"\s+(?:at|@|chez)\s+", re.IGNORECASE)


class RowBuilder:
    """Accumulates a result row, remembering which layer produced each field."""

    def __init__(self) -> None:
        self.row: dict[str, Any] = empty_row()
        self.provenance: dict[str, str] = {}

    def put(self, key: str, value: Any, source: str) -> None:
        if key not in self.row:
            raise KeyError(f"{key!r} is not a declared column")
        if value in (None, "", [], {}):
            return
        if self.row[key] not in (None, "", [], {}):
            return
        self.row[key] = value
        self.provenance[key] = source

    def put_many(self, values: dict[str, Any], source: str) -> None:
        for key, value in values.items():
            if key in self.row:
                self.put(key, value, source)

    def force(self, key: str, value: Any, source: str) -> None:
        """Overwrite unconditionally. Only for fields the runner owns."""
        self.row[key] = value
        self.provenance[key] = source


def split_name(full_name: str | None) -> tuple[str | None, str | None]:
    if not full_name:
        return None, None
    parts = [p for p in full_name.strip().split() if p]
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])


def split_headline(headline: str | None) -> tuple[str | None, str | None]:
    """'Staff Engineer at Northwind' -> ('Staff Engineer', 'Northwind')."""
    if not headline:
        return None, None
    head = headline.split("|")[0].split("·")[0].strip()
    parts = _AT_SPLIT_RE.split(head, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip() or None, parts[1].strip() or None
    return None, None


def company_slug_from_url(url: str | None) -> str | None:
    if not url:
        return None
    m = re.search(r"/company/([^/?#]+)", url)
    return m.group(1) if m else None


def build_row(
    *,
    input_url: str,
    profile: Profile | None,
    voyager: dict[str, Any] | None,
    scraped_at: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    builder = RowBuilder()

    if voyager:
        builder.put_many(voyager, "voyager")

    if profile:
        first, last = split_name(profile.name)
        builder.put("first_name", first, "public")
        builder.put("last_name", last, "public")
        builder.put("scraper_full_name", profile.name, "public")
        builder.put("linkedin_headline", profile.headline, "public")
        builder.put("linkedin_description", profile.about, "public")
        builder.put("location", profile.location, "public")
        builder.put("linkedin_profile_slug", profile.slug, "public")
        builder.put("linkedin_profile_image_url", profile.image_url, "public")
        builder.put("linkedin_followers_count", profile.follower_count, "public")
        builder.put("company_name", profile.current_company, "public")
        builder.put("linkedin_job_title", profile.job_title, "public")

        if profile.experience:
            top = profile.experience[0]
            builder.put("linkedin_job_title", top.get("title"), "public")
            builder.put("company_name", top.get("company"), "public")
            builder.put("linkedin_job_date_range", top.get("date_range"), "public")
            builder.put("linkedin_job_location", top.get("location"), "public")
            builder.put("linkedin_job_description", top.get("description"), "public")
            builder.put("linkedin_company_url", top.get("company_url"), "public")
        if profile.education:
            top = profile.education[0]
            builder.put("linkedin_school_name", top.get("school"), "public")
            builder.put("linkedin_school_degree", top.get("degree"), "public")
            builder.put("linkedin_school_field_of_study", top.get("field_of_study"), "public")
            builder.put("linkedin_school_date_range", top.get("date_range"), "public")
            builder.put("linkedin_school_url", top.get("school_url"), "public")

    title, company = split_headline(builder.row["linkedin_headline"])
    builder.put("linkedin_job_title", title, "derived")
    builder.put("company_name", company, "derived")
    builder.put(
        "linkedin_company_slug",
        company_slug_from_url(builder.row["linkedin_company_url"]),
        "derived",
    )
    builder.put(
        "linkedin_school_company_slug",
        company_slug_from_url(builder.row["linkedin_school_url"]),
        "derived",
    )
    if not builder.row["scraper_full_name"]:
        joined = " ".join(
            p for p in (builder.row["first_name"], builder.row["last_name"]) if p
        )
        builder.put("scraper_full_name", joined or None, "derived")

    slug = builder.row["linkedin_profile_slug"]
    if slug:
        builder.put("linkedin_profile_url", f"https://linkedin.com/in/{slug}", "derived")

    urn = builder.row["linkedin_profile_urn"]
    if urn:
        quoted = f'%5B%22{urn}%22%5D'
        builder.put(
            "connections_url",
            "https://www.linkedin.com/search/results/people/"
            f"?facetConnectionOf={quoted}"
            "&facetNetwork=%5B%22F%22%2C%22S%22%5D"
            "&origin=MEMBER_PROFILE_CANNED_SEARCH",
            "derived",
        )
        builder.put(
            "mutual_connections_url",
            "https://www.linkedin.com/search/results/people/"
            "?facetNetwork=%5B%22F%22%5D"
            f"&facetConnectionOf={quoted}"
            "&origin=MEMBER_PROFILE_CANNED_SEARCH&RESULT_TYPE=PEOPLE",
            "derived",
        )

    builder.force("profile_url", input_url, "runner")
    builder.force(
        "refreshed_at",
        (scraped_at or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "runner",
    )

    assert set(builder.row) == set(COLUMN_KEYS)
    return builder.row, builder.provenance
