"""
Optional enrichment passes.

Each one is off by default, costs an extra request or an extra credit, and is
allowed to fail without failing the profile that triggered it. A profile row is
the deliverable; enrichment is an upgrade to it.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

from linkedin_public_profile import BROWSER_HEADERS

from . import voyager
from .fetcher import BrowserOptions, fetch_with_session

log = logging.getLogger("phantom.enrich")

_COMPANY_URL_RE = re.compile(r"^https?://([a-z]{2,3}\.)?linkedin\.com/company/[^/?#]+", re.I)


def company_page_url(slug: str) -> str:
    return f"https://www.linkedin.com/company/{slug}/about/"


def enrich_company(slug: str, *, headless: bool = False) -> dict[str, Any]:
    """
    Fetch a company page and return the company columns it yields.

    Returns an empty dict on any failure. The caller merges, so a miss leaves
    whatever the profile page already provided rather than blanking it.
    """
    url = company_page_url(slug)
    if not _COMPANY_URL_RE.match(url):
        return {}
    try:
        page = fetch_with_session(url, BrowserOptions(headless=headless, use_session=True))
        result = page.result
    except Exception as exc:
        log.warning("company enrichment fetch failed for %s: %s", slug, exc)
        return {}

    soup = BeautifulSoup(result.html, "lxml")
    out: dict[str, Any] = {}

    try:
        entities = voyager.collect_entities(soup)
        for company in voyager.by_type(entities, "Company", "Organization"):
            industry = company.get("industry") or company.get("industryName")
            if isinstance(industry, dict):
                industry = industry.get("localizedName") or industry.get("name")
            if isinstance(industry, str):
                out.setdefault("company_industry", industry)
            for key, column in (
                ("name", "company_name"),
                ("description", "linkedin_description"),
                ("universalName", "linkedin_company_slug"),
            ):
                value = company.get(key)
                if isinstance(value, str) and value:
                    out.setdefault(column, value)
            urn = company.get("entityUrn")
            company_id = voyager.urn_id(urn if isinstance(urn, str) else None)
            if company_id:
                out.setdefault("linkedin_company_id", company_id)
            break
    except Exception as exc:
        log.warning("company model-store read failed for %s: %s", slug, exc)

    if "linkedin_description" not in out:
        tag = soup.find("meta", attrs={"property": "og:description"})
        if tag and tag.get("content"):
            out["linkedin_description"] = tag["content"].strip()

    out.setdefault("linkedin_company_slug", slug)
    out.setdefault("linkedin_company_url", f"https://linkedin.com/company/{slug}")
    return out


def save_picture(image_url: str, slug: str, target_dir: Path) -> str | None:
    """Download a profile picture as JPEG. Returns the relative path, or None."""
    if not image_url:
        return None
    target_dir.mkdir(parents=True, exist_ok=True)
    destination = target_dir / f"{slug}.jpg"
    try:
        with httpx.Client(headers=BROWSER_HEADERS, timeout=20.0, follow_redirects=True) as client:
            response = client.get(image_url)
            response.raise_for_status()
            destination.write_bytes(response.content)
    except Exception as exc:
        log.warning("picture download failed for %s: %s", slug, exc)
        return None
    return destination.name




class EmailProvider:
    name = "none"

    def find(self, first_name: str, last_name: str, company: str) -> tuple[str | None, str]:
        raise NotImplementedError


class NullProvider(EmailProvider):
    def find(self, first_name: str, last_name: str, company: str) -> tuple[str | None, str]:
        return None, "not_requested"


class HunterProvider(EmailProvider):
    name = "hunter"
    endpoint = "https://api.hunter.io/v2/email-finder"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def find(self, first_name: str, last_name: str, company: str) -> tuple[str | None, str]:
        params = {
            "company": company,
            "first_name": first_name,
            "last_name": last_name,
            "api_key": self.api_key,
        }
        try:
            with httpx.Client(timeout=25.0) as client:
                response = client.get(self.endpoint, params=params)
            if response.status_code == 401:
                return None, "invalid_key"
            if response.status_code == 429:
                return None, "rate_limited"
            response.raise_for_status()
            data = response.json().get("data") or {}
        except Exception as exc:
            log.warning("hunter lookup failed: %s", exc)
            return None, "provider_error"
        email = data.get("email")
        return email, ("verified" if email else "not_found")


class DropcontactProvider(EmailProvider):
    name = "dropcontact"
    endpoint = "https://api.dropcontact.io/batch"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def find(self, first_name: str, last_name: str, company: str) -> tuple[str | None, str]:
        payload = {
            "data": [{"first_name": first_name, "last_name": last_name, "company": company}],
            "siren": False,
            "language": "en",
        }
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    self.endpoint, json=payload, headers={"X-Access-Token": self.api_key}
                )
            if response.status_code in (401, 403):
                return None, "invalid_key"
            response.raise_for_status()
            body = response.json()
        except Exception as exc:
            log.warning("dropcontact lookup failed: %s", exc)
            return None, "provider_error"
        if body.get("request_id") and not body.get("data"):
            return None, "pending"
        rows = body.get("data") or []
        if rows and isinstance(rows[0], dict):
            emails = rows[0].get("email") or []
            if emails and isinstance(emails, list):
                return emails[0].get("email"), "verified"
        return None, "not_found"


_PROVIDERS: dict[str, type[EmailProvider]] = {
    "hunter": HunterProvider,
    "dropcontact": DropcontactProvider,
}


def build_provider(name: str | None, api_key: str | None) -> EmailProvider:
    if not name or name == "none":
        return NullProvider()
    factory = _PROVIDERS.get(name)
    if not factory or not api_key:
        log.warning("unknown or unconfigured email provider %r", name)
        return NullProvider()
    return factory(api_key)


def company_domain(row: dict[str, Any]) -> str | None:
    """Best available domain hint for an email lookup."""
    return row.get("company_name") or None
