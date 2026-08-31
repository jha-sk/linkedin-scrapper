"""
Extractor for LinkedIn's embedded model store (authenticated view).

An authenticated profile page ships its data as JSON inside `<code>` elements
rather than as markup. Each blob has an `included` array of entities, every one
carrying a `$type` naming its model. Reading those entities is stable in a way
that CSS selectors are not: class names are build-generated and rotate weekly,
but a model type rename is a client-wide migration.

Nothing here raises on a shape it does not recognise. LinkedIn ships model
changes continuously; a parser that throws on an unexpected entity takes the
whole run down with it, so every reader is total and returns None on a miss.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterator

from bs4 import BeautifulSoup

log = logging.getLogger("phantom.voyager")

_URN_ID_RE = re.compile(r"urn:li:fsd?_?\w*:\(?([A-Za-z0-9_\-]+)")
_MEMBER_URN_RE = re.compile(r"urn:li:(?:fsd_profile|member):([A-Za-z0-9_\-]+)")
_IMAGE_URN_RE = re.compile(r"urn:li:digitalmediaAsset:([A-Za-z0-9_\-]+)")


def iter_blobs(soup: BeautifulSoup) -> Iterator[dict[str, Any]]:
    """Yield every parseable JSON object embedded in a <code> element."""
    for tag in soup.find_all("code"):
        raw = (tag.string or tag.get_text() or "").strip()
        if not raw.startswith("{") or '"included"' not in raw:
            continue
        try:
            yield json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue


def collect_entities(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Flatten every `included` array on the page into one entity list."""
    entities: list[dict[str, Any]] = []
    for blob in iter_blobs(soup):
        included = blob.get("included")
        if isinstance(included, list):
            entities.extend(e for e in included if isinstance(e, dict))
    return entities


def by_type(entities: list[dict[str, Any]], *suffixes: str) -> list[dict[str, Any]]:
    """Entities whose $type ends with any of the given model names."""
    out = []
    for e in entities:
        t = e.get("$type") or ""
        if any(t.endswith(s) for s in suffixes):
            out.append(e)
    return out


def urn_id(urn: str | None) -> str | None:
    if not urn:
        return None
    m = _MEMBER_URN_RE.search(urn) or _URN_ID_RE.search(urn)
    return m.group(1) if m else None


def image_urn(value: Any) -> str | None:
    """Pull the digitalmediaAsset urn out of whatever wrapper it arrived in."""
    text = json.dumps(value) if not isinstance(value, str) else value
    m = _IMAGE_URN_RE.search(text or "")
    return f"urn:li:digitalmediaAsset:{m.group(1)}" if m else None


def image_url(value: Any) -> str | None:
    """Rebuild the largest CDN URL from a vectorImage root + artifact path."""
    if not isinstance(value, dict):
        return None
    root = value.get("rootUrl")
    artifacts = value.get("artifacts")
    if not root or not isinstance(artifacts, list) or not artifacts:
        return None
    best = max(
        (a for a in artifacts if isinstance(a, dict)),
        key=lambda a: a.get("width") or 0,
        default=None,
    )
    if not best:
        return None
    segment = best.get("fileIdentifyingUrlPathSegment")
    return f"{root}{segment}" if segment else None


def _find_vector_image(node: Any) -> dict | None:
    """Depth-first hunt for a vectorImage dict anywhere inside an entity."""
    if isinstance(node, dict):
        if "rootUrl" in node and "artifacts" in node:
            return node
        for value in node.values():
            found = _find_vector_image(value)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_vector_image(item)
            if found:
                return found
    return None


def _date_range(node: Any) -> str | None:
    """Render a dateRange entity as the 'Mon YYYY - Mon YYYY' string the UI shows."""
    if not isinstance(node, dict):
        return None
    months = (
        "", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    )

    def one(part: Any) -> str | None:
        if not isinstance(part, dict):
            return None
        year = part.get("year")
        month = part.get("month")
        if not year:
            return None
        if month and 1 <= int(month) <= 12:
            return f"{months[int(month)]} {year}"
        return str(year)

    start = one(node.get("start"))
    end = one(node.get("end"))
    if start and end:
        return f"{start} - {end}"
    if start:
        return f"{start} - Present"
    return end


def entities_from_api(payload: Any) -> list[dict[str, Any]]:
    """
    Flatten a Voyager REST response into the same entity list a page carries.

    The API returns the identical normalised shape as the embedded model store —
    an `included` array of `$type`-tagged entities — which is why one parser
    serves both sources. Older endpoints answer with `elements` instead, and a
    single-entity response is its own entity.
    """
    if not isinstance(payload, dict):
        return []

    entities: list[dict[str, Any]] = []
    for key in ("included", "elements"):
        value = payload.get(key)
        if isinstance(value, list):
            entities.extend(item for item in value if isinstance(item, dict))

    data = payload.get("data")
    if isinstance(data, dict):
        if data.get("$type"):
            entities.append(data)
        for key in ("included", "elements"):
            value = data.get(key)
            if isinstance(value, list):
                entities.extend(item for item in value if isinstance(item, dict))

    if not entities and payload.get("$type"):
        entities.append(payload)

    return entities


def parse(soup: BeautifulSoup) -> dict[str, Any]:
    """
    Return whatever this page's embedded model store yields, as column keys.

    Absent keys mean "this page did not carry it", never "the field is empty" —
    the caller merges over a lower-precedence layer rather than overwriting with
    a null.
    """
    return parse_entities(collect_entities(soup))


def parse_entities(entities: list[dict[str, Any]]) -> dict[str, Any]:
    """Read a normalised entity list, whichever source produced it."""
    if not entities:
        return {}

    out: dict[str, Any] = {}
    _read_profile(entities, out)
    _read_positions(entities, out)
    _read_education(entities, out)
    _read_skills(entities, out)
    _read_company(entities, out)
    return {k: v for k, v in out.items() if v not in (None, "", [])}


def _read_profile(entities: list[dict[str, Any]], out: dict[str, Any]) -> None:
    profiles = by_type(entities, "Profile")
    subject = next(
        (p for p in profiles if p.get("publicIdentifier") and p.get("firstName")),
        next((p for p in profiles if p.get("publicIdentifier")), None),
    )
    if not subject:
        return

    urn = subject.get("entityUrn") or subject.get("objectUrn")
    out["linkedin_profile_urn"] = urn_id(urn) and urn
    out["linkedin_profile_id"] = urn_id(subject.get("objectUrn") or urn)
    out["linkedin_profile_slug"] = subject.get("publicIdentifier")
    out["first_name"] = subject.get("firstName")
    out["last_name"] = subject.get("lastName")
    out["linkedin_headline"] = subject.get("headline")
    out["location"] = (
        (subject.get("geoLocation") or {}).get("defaultLocalizedName")
        if isinstance(subject.get("geoLocation"), dict)
        else subject.get("locationName")
    )
    if isinstance(subject.get("location"), dict):
        out["location"] = out["location"] or subject["location"].get("defaultLocalizedName")

    slug = subject.get("publicIdentifier")
    if slug:
        out["linkedin_profile_url"] = f"https://linkedin.com/in/{slug}"

    picture = subject.get("profilePicture") or subject.get("picture")
    vector = _find_vector_image(picture)
    out["linkedin_profile_image_url"] = image_url(vector)
    out["linkedin_profile_image_urn"] = image_urn(picture)

    memberships = json.dumps(subject)
    out["linkedin_is_open_to_work_badge"] = (
        "OPEN_TO_WORK" in memberships or bool(subject.get("openToWork"))
    )
    out["linkedin_is_hiring_badge"] = (
        "HIRING" in memberships or bool(subject.get("hiring"))
    )

    for card in by_type(entities, "ProfileTopCard", "TopCard"):
        followers = card.get("followerCount") or card.get("followersCount")
        if followers:
            out["linkedin_followers_count"] = followers
        connections = card.get("connectionsCount") or card.get("connections")
        if isinstance(connections, int):
            out["linkedin_connections_count"] = connections

    for net in by_type(entities, "ProfileNetworkInfo", "NetworkInfo"):
        if isinstance(net.get("followersCount"), int):
            out["linkedin_followers_count"] = net["followersCount"]
        if isinstance(net.get("connectionsCount"), int):
            out["linkedin_connections_count"] = net["connectionsCount"]
        degree = net.get("distance")
        if isinstance(degree, dict):
            degree = degree.get("value")
        if isinstance(degree, str):
            out["connection_degree"] = _degree_label(degree)


def _degree_label(raw: str) -> str:
    return {
        "SELF": "Self",
        "DISTANCE_1": "1st",
        "DISTANCE_2": "2nd",
        "DISTANCE_3": "3rd",
        "OUT_OF_NETWORK": "Out of Network",
    }.get(raw, raw)


def _read_positions(entities: list[dict[str, Any]], out: dict[str, Any]) -> None:
    positions = by_type(entities, "Position")
    if not positions:
        return
    def sort_key(p: dict[str, Any]):
        rng = p.get("dateRange") or {}
        end = (rng.get("end") or {}) if isinstance(rng, dict) else {}
        start = (rng.get("start") or {}) if isinstance(rng, dict) else {}
        return (bool(end.get("year")), -(start.get("year") or 0), -(start.get("month") or 0))

    current = sorted(positions, key=sort_key)[0]
    out["linkedin_job_title"] = current.get("title")
    out["company_name"] = current.get("companyName")
    out["linkedin_job_location"] = current.get("locationName")
    out["linkedin_job_description"] = current.get("description")
    out["linkedin_job_date_range"] = _date_range(current.get("dateRange"))

    company_urn = current.get("companyUrn") or current.get("company")
    company_id = urn_id(company_urn if isinstance(company_urn, str) else None)
    if company_id:
        out["linkedin_company_id"] = company_id


def _read_education(entities: list[dict[str, Any]], out: dict[str, Any]) -> None:
    schools = by_type(entities, "Education")
    if not schools:
        return

    def sort_key(s: dict[str, Any]):
        rng = s.get("dateRange") or {}
        end = (rng.get("end") or {}) if isinstance(rng, dict) else {}
        return -(end.get("year") or 0)

    latest = sorted(schools, key=sort_key)[0]
    out["linkedin_school_name"] = latest.get("schoolName")
    out["linkedin_school_degree"] = latest.get("degreeName")
    out["linkedin_school_field_of_study"] = latest.get("fieldOfStudy")
    out["linkedin_school_date_range"] = _date_range(latest.get("dateRange"))
    school_urn = latest.get("schoolUrn") or latest.get("school")
    school_id = urn_id(school_urn if isinstance(school_urn, str) else None)
    if school_id:
        out["linkedin_school_url"] = f"https://linkedin.com/school/{school_id}"
        out["linkedin_school_company_slug"] = school_id


def _read_skills(entities: list[dict[str, Any]], out: dict[str, Any]) -> None:
    names = []
    for skill in by_type(entities, "Skill"):
        name = skill.get("name")
        if name and name not in names:
            names.append(name)
    if names:
        out["linkedin_skills_label"] = ", ".join(names)


def _read_company(entities: list[dict[str, Any]], out: dict[str, Any]) -> None:
    companies = by_type(entities, "Company", "Organization")
    for company in companies:
        slug = company.get("universalName")
        if not slug:
            continue
        out.setdefault("linkedin_company_slug", slug)
        out.setdefault("linkedin_company_url", f"https://linkedin.com/company/{slug}")
        industry = company.get("industry") or company.get("industryName")
        if isinstance(industry, dict):
            industry = industry.get("localizedName") or industry.get("name")
        if isinstance(industry, str):
            out.setdefault("company_industry", industry)
        description = company.get("description") or company.get("tagline")
        if isinstance(description, str):
            out.setdefault("linkedin_description", description)
        break
