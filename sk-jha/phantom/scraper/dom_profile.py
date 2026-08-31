"""
Extractor for the rendered authenticated profile.

Raw DOM scraping, no API calls.

**Anchor on heading text.** This was written twice. The first version anchored on
the in-page navigation ids (`div#experience`, `div#about`), on the reasoning that
they are part of the page's URL contract while class names are build-generated
and rotate. The reasoning was right; the fact was not. LinkedIn's current build
has moved to hashed CSS modules (`_5b216717 c85c4b08 …`) and dropped those
anchors entirely, so an id-based selector matches nothing at all.

What survived the redesign is the visible structure: a `<section>` whose first
heading reads "About", "Experience", "Education", "Skills". Heading text is the
most stable handle left, because it is the thing the page exists to show. It is
locale-dependent, which is why the browser context pins `en-US`.

The id anchors are still tried first. They cost one lookup and still work on the
older shape, which some accounts continue to be served.

**There is no `<h1>`.** The person's name is an `<h2>`, and the page has no `h1`
whatsoever. Any selector, render check, or wait condition written against `main
h1` silently matches nothing — which looks exactly like "the page never
rendered", and was diagnosed as that for a while.

**Read `span[aria-hidden="true"]`, not the whole node.** Visible strings are
emitted twice: once for sighted users in an `aria-hidden` span, once as
visually-hidden text for screen readers. Taking the parent's text returns the
string doubled — "Sourabh JhaSourabh Jha" — the most common way a naive LinkedIn
scraper produces subtly wrong data.

Every reader is total. A missing section returns None and the merge layer falls
through to whatever a lower-precedence extractor found.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from bs4 import BeautifulSoup, Tag

log = logging.getLogger("phantom.dom")

_WS_RE = re.compile(r"\s+")
_COUNT_RE = re.compile(r"([\d,\.]+)\s*\+?\s*(K|M)?", re.IGNORECASE)
_DEGREE_RE = re.compile(r"\b(1st|2nd|3rd)\+?\b", re.IGNORECASE)
_DATE_RE = re.compile(r"\b(19|20)\d{2}\b|\bPresent\b", re.IGNORECASE)
_COUNT_LINE_RE = re.compile(r"\b(connection|follower)s?\b", re.IGNORECASE)

_BARE_COUNT_RE = re.compile(r"^[\d,\.]+\+?\s*[KM]?$", re.IGNORECASE)

_PRONOUN_WORD = (
    r"(?:he|him|his|she|her|hers|they|them|their|theirs|ze|zie|zir|hir|"
    r"xe|xem|xyr|ey|em|eir|per|pers|ve|ver|vis|it|its)"
)
_SCHOOL_WORD_RE = re.compile(
    r"\b(universit(?:y|e|ies)|college|school|institute|instituto|academy|"
    r"polytechnic|iit|nit|iiit)\b",
    re.IGNORECASE,
)

_PRONOUN_RE = re.compile(
    rf"^{_PRONOUN_WORD}(?:\s*/\s*{_PRONOUN_WORD}){{1,2}}$", re.IGNORECASE
)

_PROSE_TESTID = "expandable-text-box"

_SEE_MORE_RE = re.compile(r"\s*…?\s*see (?:more|less)\s*", re.IGNORECASE)


def _prose_text(element: Tag) -> str:
    """A prose box read whole, with the expand/collapse affordance removed."""
    from copy import copy

    node = copy(element)
    for button in node.find_all("button"):
        button.decompose()
    text = node.get_text(" ", strip=True)
    return _SEE_MORE_RE.sub(" ", text).strip()


_CHROME_HEADINGS = {
    "ad options",
    "explore premium profiles",
    "more profiles for you",
    "people you may know",
    "promoted",
    "you might like",
}
_NOTIFICATION_RE = re.compile(r"^\d+\s+notifications?$", re.IGNORECASE)

_PLAYER_CHROME = {
    "video player is loading.",
    "current time",
    "duration",
    "loaded",
    "stream type",
    "remaining time",
    "playback rate",
    "chapters",
    "descriptions",
    "captions",
    "audio track",
    "fullscreen",
    "play",
    "pause",
    "mute",
    "unmute",
    "live",
    "this is a modal window.",
    "beginning of dialog window.",
    "end of dialog window.",
    "text",
    "background",
    "window",
    "font size",
    "text edge style",
    "font family",
}
_PLAYER_VALUE_RE = re.compile(r"^(?:\d{1,2}:\d{2}(?::\d{2})?|\d{1,3}(?:\.\d+)?%|/)$")


def _is_player_chrome(line: str) -> bool:
    value = line.strip()
    return value.lower() in _PLAYER_CHROME or bool(_PLAYER_VALUE_RE.match(value))

_ABOUT = "about"
_EXPERIENCE = "experience"
_EDUCATION = "education"
_SKILLS = "skills"
_CONTENT_HEADINGS = {_ABOUT, _EXPERIENCE, _EDUCATION, _SKILLS, "activity"}


def _clean(text: str | None) -> str | None:
    if not text:
        return None
    collapsed = _WS_RE.sub(" ", text).strip()
    return collapsed or None


def visible_text(node: Tag | None) -> str | None:
    """
    The string a sighted reader sees, de-duplicated.

    Prefers the `aria-hidden` span LinkedIn wraps visible text in; falls back to
    the node's own text when the markup does not use that pattern.
    """
    if node is None:
        return None
    span = node.select_one('span[aria-hidden="true"]')
    if span is not None:
        return _clean(span.get_text(" ", strip=True))
    return _clean(node.get_text(" ", strip=True))


def name_from_title(title: str | None) -> tuple[str | None, str | None]:
    """
    Split the document title into a name and, when present, a company.

    `<title>` is the one identity signal the shell sets server-side, so it is
    correct even on a page whose body is still hydrating. Two observed shapes:

        "Sourabh Jha | LinkedIn"                -> name only
        "Sourabh Jha - Accenture | LinkedIn"    -> name and current company
    """
    cleaned = _clean(title)
    if not cleaned:
        return None, None

    head = cleaned.rsplit("|", 1)[0].strip() if "|" in cleaned else cleaned
    if not head or head.lower() in {"linkedin", "sign up", "join linkedin"}:
        return None, None

    if " - " in head:
        name, company = head.split(" - ", 1)
        return _clean(name), _clean(company)
    return _clean(head), None




_HEADING_COUNT_RE = re.compile(r"\s*\(\s*[\d,]+\s*\)\s*$")


def normalise_heading(text: str | None) -> str | None:
    """
    Reduce a heading to its stable name.

    LinkedIn appends entry counts to some headings — "Skills (44)" — so an exact
    lookup for "skills" misses the section entirely while the census cheerfully
    lists it under "other headings". The count is data about the section, not
    part of its name.
    """
    cleaned = _clean(text)
    if not cleaned:
        return None
    return _HEADING_COUNT_RE.sub("", cleaned).strip().lower() or None


def heading_count(text: str | None) -> int | None:
    """The "(44)" in "Skills (44)", when present — LinkedIn's own entry count."""
    cleaned = _clean(text)
    if not cleaned:
        return None
    match = _HEADING_COUNT_RE.search(cleaned)
    if not match:
        return None
    digits = re.sub(r"[^\d]", "", match.group(0))
    return int(digits) if digits else None


def heading_of(section: Tag) -> str | None:
    """The first heading inside a section, which is what labels it."""
    node = section.find(["h1", "h2", "h3"])
    return visible_text(node) if node else None


def sections_by_heading(soup: BeautifulSoup) -> dict[str, Tag]:
    """
    Map lowercased heading text to the smallest section carrying it.

    LinkedIn nests sections, so the same heading appears on an outer wrapper and
    an inner card. The inner one is kept: it contains the entries and not the
    neighbouring cards, and reading the outer would pull a following section's
    rows into this one's.
    """
    found: dict[str, Tag] = {}
    for section in soup.find_all("section"):
        key = normalise_heading(heading_of(section))
        if not key:
            continue
        previous = found.get(key)
        if previous is None or len(str(section)) < len(str(previous)):
            found[key] = section
    return found


def _content_section(soup: BeautifulSoup, name: str) -> Tag | None:
    """
    Locate a profile section, id anchor first, then heading text.

    Both shapes are in the wild — older accounts still get the anchored markup —
    and trying the cheap exact match before the textual one costs nothing.
    """
    anchor = soup.find(id=name)
    if anchor is not None:
        section = anchor.find_parent("section")
        if isinstance(section, Tag):
            return section
    return sections_by_heading(soup).get(name)


def _top_card(soup: BeautifulSoup, name: str | None) -> Tag | None:
    """
    The section headed by the person's own name.

    Anchoring on the name from `<title>` is what makes this unambiguous: the
    page contains several sections whose heading is a person's name — the
    profile owner's, and every "more profiles for you" card — and only one of
    them matches the title.
    """
    if name:
        section = sections_by_heading(soup).get(name.lower())
        if section is not None:
            return section

    for section in soup.find_all("section"):
        label = heading_of(section)
        if not label:
            continue
        key = label.lower()
        if key in _CHROME_HEADINGS or key in _CONTENT_HEADINGS:
            continue
        if _NOTIFICATION_RE.match(key):
            continue
        return section
    return None


def _text_lines(node: Tag, limit: int = 40) -> list[str]:
    """
    The visible strings inside a node, in document order, de-duplicated.

    Reads leaf elements — those with no element child of their own — because
    LinkedIn's hashed-class markup gives no way to ask for "the headline" by
    name. Position within the card is the only remaining structure, so the
    readers below take the first line as the title, the next as the subtitle,
    and so on.
    """
    lines: list[str] = []
    seen: set[str] = set()
    for element in node.find_all(["span", "div", "p", "h1", "h2", "h3", "a", "li"]):
        prose = element.get("data-testid") == _PROSE_TESTID
        if not prose:
            if element.find_parent(attrs={"data-testid": _PROSE_TESTID}) is not None:
                continue
            if element.find(["span", "div", "p", "h1", "h2", "h3"]) is not None:
                continue
        if _is_chrome(element):
            continue
        value = _prose_text(element) if prose else visible_text(element)
        if not value or value in seen or _is_chrome_text(value):
            continue
        seen.add(value)
        lines.append(value)
        if len(lines) >= limit:
            break
    return lines


_CHROME_PARENTS = {"nav", "header", "footer", "aside", "button", "form", "select"}

_CHROME_TEXT = {
    "all",
    "show all",
    "show more",
    "show less",
    "see more",
    "see less",
    "more",
    "sort by",
    "recently added",
    "skip to search",
    "skip to main content",
    "skip to primary content",
    "skip to aside",
    "skip to footer",
    "home",
    "my network",
    "jobs",
    "messaging",
    "notifications",
    "me",
    "follow",
    "following",
    "message",
    "connect",
    "save",
    "next",
    "previous",
    "loading",
}


def _is_chrome(element: Tag) -> bool:
    for parent in element.parents:
        name = getattr(parent, "name", None)
        if name in _CHROME_PARENTS:
            return True
        if name == "section":
            break
    return False


def _is_chrome_text(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in _CHROME_TEXT:
        return True
    return bool(re.fullmatch(r"[·•\s]*\d(?:st|nd|rd|th)\+?", lowered))


def _parse_count(text: str | None) -> int | None:
    """'1,234 followers' -> 1234; '2K followers' -> 2000; '500+' -> 500."""
    if not text:
        return None
    match = _COUNT_RE.search(text)
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    suffix = (match.group(2) or "").upper()
    if suffix == "K":
        value *= 1_000
    elif suffix == "M":
        value *= 1_000_000
    return int(value)




def _read_identity(soup: BeautifulSoup, out: dict[str, Any], title: str | None) -> None:
    name, company = name_from_title(title)

    card = _top_card(soup, name)
    if name is None and card is not None:
        name = heading_of(card)

    if name:
        out["scraper_full_name"] = name
        parts = name.split()
        if parts:
            out["first_name"] = parts[0]
            if len(parts) > 1:
                out["last_name"] = " ".join(parts[1:])
    if company:
        out["company_name"] = company

    if card is None:
        return

    company_link = card.select_one('a[href*="/company/"]')
    school_link = card.select_one('a[href*="/school/"]')
    company_text = visible_text(company_link)
    school_text = visible_text(school_link)

    if company_text:
        out.setdefault("company_name", company_text)
    if company_link is not None:
        slug = re.search(r"/company/([^/?#]+)", company_link.get("href") or "")
        if slug:
            out.setdefault("linkedin_company_slug", slug.group(1))
            out.setdefault("linkedin_company_url", f"https://linkedin.com/company/{slug.group(1)}")
    if school_text:
        out.setdefault("linkedin_school_name", school_text)

    lines = _text_lines(card)
    remainder = [
        line
        for line in lines
        if line != name
        and line.lower() not in {
            "follow",
            "message",
            "connect",
            "more",
            "open to",
            "pending",
            "contact info",
        }
        and not _PRONOUN_RE.match(line)
    ]
    if remainder:
        out["linkedin_headline"] = remainder[0]

    org_line = next(
        (
            line
            for line in remainder[1:]
            if ("·" in line or "•" in line) and not _COUNT_LINE_RE.search(line)
        ),
        None,
    )
    if org_line:
        parts = [part.strip() for part in re.split(r"[·•]", org_line) if part.strip()]
        if parts:
            out.setdefault("company_name", parts[0])
        if len(parts) > 1:
            out.setdefault("linkedin_school_name", parts[1])

    def is_org_line(line: str) -> bool:
        if org_line and line == org_line:
            return True
        if company_text and company_text in line:
            return True
        if school_text and school_text in line:
            return True
        return False

    def is_substantive(line: str) -> bool:
        return len(line) > 2 and any(character.isalnum() for character in line)

    candidates = [
        line
        for line in remainder[1:]
        if is_substantive(line)
        and not is_org_line(line)
        and not _COUNT_LINE_RE.search(line)
        and not _BARE_COUNT_RE.match(line)
        and not _DEGREE_RE.fullmatch(line)
    ]
    location = candidates[-1] if candidates else None

    if not out.get("linkedin_school_name"):
        for line in candidates[:-1]:
            if _SCHOOL_WORD_RE.search(line):
                out["linkedin_school_name"] = line
                break
    if location:
        out["location"] = location

    text = card.get_text(" ", strip=True)
    for label, key in (
        ("connection", "linkedin_connections_count"),
        ("follower", "linkedin_followers_count"),
    ):
        match = re.search(rf"([\d,\.]+\+?\s*[KM]?)\s+{label}", text, re.IGNORECASE)
        if match:
            out.setdefault(key, _parse_count(match.group(1)))

    image = card.select_one("img[src*='licdn.com']")
    if image is not None:
        out["linkedin_profile_image_url"] = image.get("src")


def _read_degree(soup: BeautifulSoup, out: dict[str, Any]) -> None:
    """
    Connection degree, anchored to the profile owner's name.

    A bare search for "2nd" or "3rd+" finds the degree of whoever appears in the
    "More profiles for you" rail as readily as the person being scraped, so the
    name has to be part of the pattern.
    """
    if out.get("connection_degree") or not out.get("scraper_full_name"):
        return
    main = soup.find("main") or soup
    text = main.get_text(" ", strip=True)
    match = re.search(
        rf"{re.escape(out['scraper_full_name'])}\s*[•·\-]?\s*(1st|2nd|3rd)(\+?)",
        text,
        re.IGNORECASE,
    )
    if match:
        out["connection_degree"] = f"{match.group(1).lower()}{match.group(2)}"


def _read_counts_from_page(soup: BeautifulSoup, out: dict[str, Any]) -> None:
    """
    Follower and connection counts, wherever they ended up.

    On the current build these sit in the Activity section rather than the top
    card, so a card-only read misses them.
    """
    main = soup.find("main") or soup
    text = main.get_text(" ", strip=True)
    for label, key in (
        ("connection", "linkedin_connections_count"),
        ("follower", "linkedin_followers_count"),
    ):
        if out.get(key):
            continue
        match = re.search(rf"([\d,\.]+\+?\s*[KM]?)\s+{label}", text, re.IGNORECASE)
        if match:
            out[key] = _parse_count(match.group(1))


def _read_about(soup: BeautifulSoup, out: dict[str, Any]) -> None:
    section = _content_section(soup, _ABOUT)
    if section is None:
        return
    lines = [line for line in _text_lines(section, limit=60) if line.lower() != _ABOUT]
    for index, line in enumerate(lines):
        if line.strip().lower() == "top skills":
            lines = lines[:index]
            break
    text = max(lines, key=len, default=None) if lines else None
    if text and len(text) > 40:
        out["linkedin_description"] = text
        out["linkedin_about"] = text


def _entry_rows(section: Tag | None) -> list[Tag]:
    """
    The entry rows of a section.

    Three strategies, because the entry container is not stable across builds.
    The first version assumed `<li>` and returned nothing on a page whose
    sections were plainly populated — "found, 0 rows" — which reads as "this
    person has no experience" rather than "the scraper cannot see it".

      1. list items, when the section uses them
      2. the ancestors of the organisation links: every experience row links to
         a company, every education row to a school, so the smallest ancestor
         holding exactly one such link is one row
      3. repeated siblings: the parent whose children most look like a list of
         similar, text-bearing blocks

    Each is a fallback for the last, so a markup change costs a strategy rather
    than the section.
    """
    if section is None:
        return []

    rows = [li for li in section.select("li") if li.find_parent("li") is None]
    if not rows:
        rows = _rows_from_org_links(section)
    if not rows:
        rows = _rows_from_repeated_siblings(section)

    return [row for row in rows if row.get_text(strip=True)]


def _rows_from_org_links(section: Tag) -> list[Tag]:
    """Group a section by its organisation links, one row per link."""
    anchors = section.select('a[href*="/company/"], a[href*="/school/"]')
    if len(anchors) < 1:
        return []

    others = list(anchors)
    rows: list[Tag] = []
    for anchor in anchors:
        node: Tag = anchor
        while node.parent is not None and node.parent is not section:
            parent = node.parent
            shares = any(
                other is not anchor and parent in list(other.parents) for other in others
            )
            if shares:
                break
            node = parent
        if node is not section and node not in rows:
            rows.append(node)
    return rows


def _rows_from_repeated_siblings(section: Tag) -> list[Tag]:
    """The most list-like group of children anywhere inside the section."""
    best: list[Tag] = []
    for parent in section.find_all(True):
        children = [
            child
            for child in parent.find_all(recursive=False)
            if child.name not in {"h1", "h2", "h3", "script", "style"}
            and len(_text_lines(child, limit=3)) >= 2
        ]
        if len(children) > len(best):
            best = children
    return best


def _entry_fields(item: Tag) -> dict[str, str | None]:
    """
    Read one experience or education row.

    An explicit bold element is used when the markup still has one. Otherwise
    position decides — but position alone is not enough, because a row opens
    with the company or school *logo link*, whose text is the organisation. Read
    naively, that becomes the title and every field shifts by one. So a first
    line matching the row's organisation link is treated as the organisation,
    and the title is taken from the next line.
    """
    empty = {"title": None, "organisation": None, "date_range": None, "location": None}
    lines = _text_lines(item, limit=12)
    if not lines:
        return empty

    bold = item.select_one('div[class*="t-bold"], span[class*="t-bold"]')
    title = visible_text(bold)

    link = item.select_one('a[href*="/company/"], a[href*="/school/"]')
    link_text = visible_text(link)

    if title:
        rest = [line for line in lines if line != title]
    elif link_text and lines[0] == link_text and len(lines) > 1:
        title = lines[1]
        rest = [line for line in lines if line != title]
    else:
        title = lines[0]
        rest = lines[1:]

    if link_text:
        rest = [line for line in rest if line != link_text]
    date_range = next((line for line in rest if _DATE_RE.search(line)), None)
    organisation = next((line for line in rest if line != date_range), None)
    location = next(
        (
            line
            for line in rest
            if line not in {organisation, date_range} and not _DATE_RE.search(line)
        ),
        None,
    )
    return {
        "title": title,
        "organisation": organisation,
        "date_range": date_range,
        "location": location,
    }


def _read_experience(soup: BeautifulSoup, out: dict[str, Any]) -> None:
    section = _content_section(soup, _EXPERIENCE)
    rows = _entry_rows(section)
    if not rows:
        return
    top = _entry_fields(rows[0])
    out["linkedin_job_title"] = top["title"]
    out["linkedin_job_date_range"] = top["date_range"]
    out["linkedin_job_location"] = top["location"]

    prose = rows[0].select_one(f'[data-testid="{_PROSE_TESTID}"]')
    if prose is not None:
        out["linkedin_job_description"] = _prose_text(prose) or None

    company = top["organisation"]
    if company:
        out["company_name"] = _clean(company.split("·")[0])

    link = rows[0].select_one('a[href*="/company/"]')
    if link is not None:
        slug = re.search(r"/company/([^/?#]+)", link.get("href") or "")
        if slug:
            out["linkedin_company_slug"] = slug.group(1)
            out["linkedin_company_url"] = f"https://linkedin.com/company/{slug.group(1)}"


def _read_education(soup: BeautifulSoup, out: dict[str, Any]) -> None:
    section = _content_section(soup, _EDUCATION)
    rows = _entry_rows(section)
    if not rows:
        return
    top = _entry_fields(rows[0])
    out["linkedin_school_name"] = top["title"]
    out["linkedin_school_date_range"] = top["date_range"]

    detail = top["organisation"]
    if detail:
        parts = [part.strip() for part in detail.split(",")]
        out["linkedin_school_degree"] = parts[0] or None
        if len(parts) > 1:
            out["linkedin_school_field_of_study"] = ", ".join(parts[1:]).strip() or None

    link = rows[0].select_one('a[href*="/school/"], a[href*="/company/"]')
    if link is not None:
        slug = re.search(r"/(?:school|company)/([^/?#]+)", link.get("href") or "")
        if slug:
            out["linkedin_school_company_slug"] = slug.group(1)
            out["linkedin_school_url"] = f"https://linkedin.com/school/{slug.group(1)}"


def _read_skills(soup: BeautifulSoup, out: dict[str, Any]) -> None:
    section = _content_section(soup, _SKILLS)
    names: list[str] = []
    for row in _entry_rows(section):
        lines = _text_lines(row, limit=3)
        if lines and lines[0].lower() != _SKILLS:
            name = lines[0]
            if name not in names:
                names.append(name)
    if names:
        out["linkedin_skills_label"] = ", ".join(names)


SECTION_PATHS: dict[str, str] = {
    "experience": "experience",
    "education": "education",
    "skills": "skills",
    "licenses & certifications": "certifications",
    "projects": "projects",
    "languages": "languages",
    "interests": "interests",
    "honors & awards": "honors",
    "volunteering": "volunteering",
    "publications": "publications",
    "courses": "courses",
    "organizations": "organizations",
    "recommendations": "recommendations",
}


def detail_url(slug: str, section: str) -> str:
    """
    The "Show all" page for one section.

    The profile itself renders only the first two or three entries of each
    section; the rest sit behind a link to `/details/<section>/`. Anything that
    claims to return "all skills" has to visit that page, because the remainder
    is not in the profile document at all.
    """
    path = SECTION_PATHS.get(section, section)
    return f"https://www.linkedin.com/in/{slug}/details/{path}/"




def _row_link(row: Tag, *patterns: str) -> str | None:
    for pattern in patterns:
        anchor = row.select_one(f'a[href*="{pattern}"]')
        if anchor is not None:
            href = anchor.get("href") or ""
            return href if href.startswith("http") else f"https://www.linkedin.com{href}"
    return None


def _longest(lines: list[str], minimum: int = 60) -> str | None:
    candidate = max(lines, key=len, default=None)
    return candidate if candidate and len(candidate) >= minimum else None


def experience_entries(section: Tag | None) -> list[dict[str, Any]]:
    """Every role: title, company, dates, location, description."""
    entries: list[dict[str, Any]] = []
    for row in _entry_rows(section):
        fields = _entry_fields(row)
        lines = _text_lines(row, limit=20)
        organisation = fields["organisation"] or ""
        company = _clean(organisation.split("·")[0]) if organisation else None
        employment = None
        if "·" in organisation:
            employment = _clean(organisation.split("·", 1)[1])

        described = [
            line
            for line in lines
            if line not in {fields["title"], organisation, fields["date_range"], fields["location"]}
        ]
        entries.append(
            {
                "title": fields["title"],
                "company": company,
                "employment_type": employment,
                "date_range": fields["date_range"],
                "location": fields["location"],
                "description": _longest(described),
                "company_url": _row_link(row, "/company/"),
                "lines": lines,
            }
        )
    return entries


def education_entries(section: Tag | None) -> list[dict[str, Any]]:
    """Every school: name, degree, field of study, dates."""
    entries: list[dict[str, Any]] = []
    for row in _entry_rows(section):
        fields = _entry_fields(row)
        detail = fields["organisation"] or ""
        parts = [part.strip() for part in detail.split(",")] if detail else []
        entries.append(
            {
                "school": fields["title"],
                "degree": parts[0] if parts else None,
                "field_of_study": ", ".join(parts[1:]).strip() or None if len(parts) > 1 else None,
                "date_range": fields["date_range"],
                "school_url": _row_link(row, "/school/", "/company/"),
                "lines": _text_lines(row, limit=20),
            }
        )
    return entries


def certification_entries(section: Tag | None) -> list[dict[str, Any]]:
    """Every licence or certificate: name, issuer, dates, credential id."""
    entries: list[dict[str, Any]] = []
    for row in _entry_rows(section):
        lines = _text_lines(row, limit=20)
        if not lines:
            continue
        fields = _entry_fields(row)
        credential = next(
            (line for line in lines if re.search(r"credential id", line, re.IGNORECASE)), None
        )
        issued = next(
            (line for line in lines if re.search(r"issued|expires", line, re.IGNORECASE)),
            fields["date_range"],
        )
        entries.append(
            {
                "name": fields["title"] or lines[0],
                "issuer": fields["organisation"],
                "issued": issued,
                "credential_id": credential,
                "url": _row_link(row, "/company/", "http"),
                "lines": lines,
            }
        )
    return entries


def project_entries(section: Tag | None) -> list[dict[str, Any]]:
    """Every project: name, dates, description."""
    entries: list[dict[str, Any]] = []
    for row in _entry_rows(section):
        lines = _text_lines(row, limit=20)
        if not lines:
            continue
        fields = _entry_fields(row)
        name = fields["title"] or lines[0]
        entries.append(
            {
                "name": name,
                "date_range": fields["date_range"],
                "description": _longest([line for line in lines if line != name], minimum=40),
                "lines": lines,
            }
        )
    return entries


def language_entries(section: Tag | None) -> list[dict[str, Any]]:
    """Every language, with its proficiency line when shown."""
    entries: list[dict[str, Any]] = []
    for row in _entry_rows(section):
        lines = _text_lines(row, limit=6)
        if not lines:
            continue
        entries.append(
            {
                "language": lines[0],
                "proficiency": lines[1] if len(lines) > 1 else None,
            }
        )
    return entries


def skill_names(section: Tag | None) -> list[str]:
    """
    Every skill name in a section.

    The endorsement counts and "Endorsed by …" lines are dropped: they are about
    other people, and they are what a naive first-line read would collect
    instead of the skill.
    """
    names: list[str] = []
    for row in _entry_rows(section):
        for line in _text_lines(row, limit=6):
            if not line or line.lower() == _SKILLS:
                continue
            if re.search(r"endorse|experience|passed|assessment", line, re.IGNORECASE):
                continue
            if line not in names:
                names.append(line)
            break
    return names


def top_skills(soup: BeautifulSoup) -> list[str]:
    """
    The "Top skills" strip LinkedIn shows under the top card.

    A separate thing from the Skills section — it is the three the profile owner
    chose to feature, and it appears nowhere in `/details/skills/`.
    """
    for section in soup.find_all("section"):
        label = normalise_heading(heading_of(section))
        if label != "top skills":
            continue
        lines = [line for line in _text_lines(section, limit=12) if line.lower() != "top skills"]
        names: list[str] = []
        for line in lines:
            for part in re.split(r"[·•]", line):
                value = _clean(part)
                if value and value not in names:
                    names.append(value)
        return names

    main = soup.find("main") or soup
    text = main.get_text(" ", strip=True)
    match = re.search(r"Top skills\s*[:\-]?\s*(.{3,300})", text)
    if not match:
        return []

    tail = match.group(1)
    boundary = re.search(
        r"\b(Activity|About|Experience|Education|Skills|Interests|Projects|Languages)\b", tail
    )
    if boundary:
        tail = tail[: boundary.start()]

    return [
        value
        for value in (_clean(part) for part in re.split(r"[·•]", tail))
        if value and not _is_chrome_text(value)
    ][:6]


def image_urls(soup: BeautifulSoup, name: str | None = None) -> dict[str, str]:
    """
    Profile and background images, as LinkedIn CDN URLs.

    Both are served from `media.licdn.com` and the URL is the whole deliverable —
    nothing is downloaded here. They are told apart by the path segment LinkedIn
    puts in every asset URL (`profile-displayphoto`, `profile-backgroundimage`),
    which is stabler than position in the document: the first `licdn.com` image
    on the page is as likely to be the banner as the person.
    """
    found: dict[str, str] = {}
    for image in soup.select("img[src*='licdn.com'], img[data-delayed-url*='licdn.com']"):
        src = image.get("src") or image.get("data-delayed-url") or ""
        if not src:
            continue
        if "profile-displayphoto" in src:
            found.setdefault("profile", src)
        elif "profile-backgroundimage" in src or "background_image" in src:
            found.setdefault("background", src)
        elif "company-logo" in src or "school-logo" in src:
            continue
        elif name and name.lower() in (image.get("alt") or "").lower():
            found.setdefault("profile", src)

    if "profile" not in found:
        for image in soup.select("img[src*='licdn.com']"):
            src = image.get("src") or ""
            if src and "logo" not in src:
                found["profile"] = src
                break
    return found


_LIST_SECTIONS: tuple[tuple[str, str], ...] = (
    ("licenses & certifications", "linkedin_certifications"),
    ("projects", "linkedin_projects"),
    ("interests", "linkedin_interests"),
    ("languages", "linkedin_languages"),
    ("honors & awards", "linkedin_honors"),
    ("volunteering", "linkedin_volunteering"),
    ("publications", "linkedin_publications"),
    ("courses", "linkedin_courses"),
    ("organizations", "linkedin_organizations"),
    ("recommendations", "linkedin_recommendations"),
)


def _read_list_sections(soup: BeautifulSoup, out: dict[str, Any]) -> None:
    """Read every simple list section into a joined string column."""
    sections = sections_by_heading(soup)
    for heading, column in _LIST_SECTIONS:
        section = sections.get(heading)
        if section is None:
            continue
        names: list[str] = []
        for row in _entry_rows(section):
            lines = _text_lines(row, limit=4)
            if not lines:
                continue
            name = lines[0]
            if name and name.lower() != heading and name not in names:
                names.append(name)
        if names:
            out[column] = ", ".join(names)


def collect_sections(soup: BeautifulSoup, name: str | None = None) -> dict[str, Any]:
    """
    Every section on the page, with its rows, as text.

    The flat columns carry the top entry of the sections this module understands.
    That is what a CSV can hold, and it is lossy by construction: a person with
    six roles gets one, and a section nobody anticipated gets nothing.

    This is the escape hatch. It records what LinkedIn actually showed —
    heading, its own entry count, and the text lines of every row — so a
    question the column contract cannot answer is still answerable from stored
    data rather than requiring another scrape.
    """
    captured: dict[str, Any] = {}
    for section in soup.find_all("section"):
        raw_heading = heading_of(section)
        key = normalise_heading(raw_heading)
        if not key or key in _CHROME_HEADINGS or _NOTIFICATION_RE.match(key):
            continue
        if name and key == normalise_heading(name):
            continue
        rows = [
            [line for line in _text_lines(row, limit=12) if not _is_player_chrome(line)]
            for row in _entry_rows(section)
        ]
        rows = [row for row in rows if row]
        entry = {"heading": raw_heading, "rows": rows}
        count = heading_count(raw_heading)
        if count is not None:
            entry["count"] = count
        if not rows:
            entry["lines"] = _text_lines(section, limit=30)
        previous = captured.get(key)
        if previous is None or len(entry.get("rows") or []) > len(previous.get("rows") or []):
            captured[key] = entry
    return captured


def parse(soup: BeautifulSoup, slug: str | None = None) -> dict[str, Any]:
    """
    Read a rendered authenticated profile into column keys.

    Absent keys mean "this page did not show it". Every reader is wrapped: a
    section LinkedIn restructured must not take the other five down with it.
    """
    out: dict[str, Any] = {}
    title = _clean(soup.title.get_text()) if soup.title else None

    try:
        _read_identity(soup, out, title)
    except Exception as exc:
        log.warning("dom reader identity failed: %s", exc)

    for reader in (
        _read_counts_from_page,
        _read_degree,
        _read_about,
        _read_experience,
        _read_education,
        _read_skills,
        _read_list_sections,
        _read_structured,
    ):
        try:
            reader(soup, out)
        except Exception as exc:
            log.warning("dom reader %s failed: %s", reader.__name__, exc)

    try:
        _read_section_counts(soup, out)
    except Exception as exc:
        log.warning("dom reader section counts failed: %s", exc)

    if slug:
        out.setdefault("linkedin_profile_slug", slug)
        out.setdefault("linkedin_profile_url", f"https://linkedin.com/in/{slug}")

    return {k: v for k, v in out.items() if v not in (None, "", [], {})}


def parse_detail(html: str, section: str) -> dict[str, Any]:
    """
    Read one "Show all" page.

    A detail page is the section, rather than containing it: there is no sibling
    card to disambiguate from, so the whole `<main>` is treated as the
    container. What comes back is the complete list — which is the entire reason
    for visiting, since the profile itself renders only the first few entries.
    """
    import json

    soup = BeautifulSoup(html, "lxml")
    container = soup.find("main") or soup.body or soup

    if section == "skills":
        names = skill_names(container)
        if not names:
            return {}
        return {
            "linkedin_skills_json": json.dumps(names, ensure_ascii=False),
            "linkedin_skills_label": ", ".join(names),
            "linkedin_skills_count": len(names),
        }

    readers: dict[str, tuple[Any, str]] = {
        "experience": (experience_entries, "linkedin_experience_json"),
        "education": (education_entries, "linkedin_education_json"),
        "licenses & certifications": (certification_entries, "linkedin_certifications_json"),
        "projects": (project_entries, "linkedin_projects_json"),
        "languages": (language_entries, "linkedin_languages_json"),
    }
    if section not in readers:
        return {}

    reader, column = readers[section]
    entries = reader(container)
    if not entries:
        return {}

    out: dict[str, Any] = {column: json.dumps(entries, ensure_ascii=False)}

    first = entries[0]
    if section == "experience":
        out["linkedin_job_title"] = first.get("title")
        out["company_name"] = first.get("company")
        out["linkedin_job_date_range"] = first.get("date_range")
        out["linkedin_job_location"] = first.get("location")
        out["linkedin_job_description"] = first.get("description")
        out["linkedin_experience_count"] = len(entries)
    elif section == "education":
        out["linkedin_school_name"] = first.get("school")
        out["linkedin_school_degree"] = first.get("degree")
        out["linkedin_school_field_of_study"] = first.get("field_of_study")
        out["linkedin_school_date_range"] = first.get("date_range")
        out["linkedin_education_count"] = len(entries)
    elif section == "licenses & certifications":
        out["linkedin_certifications"] = ", ".join(
            entry["name"] for entry in entries if entry.get("name")
        )
    elif section == "projects":
        out["linkedin_projects"] = ", ".join(
            entry["name"] for entry in entries if entry.get("name")
        )
    elif section == "languages":
        out["linkedin_languages"] = ", ".join(
            entry["language"] for entry in entries if entry.get("language")
        )

    return {key: value for key, value in out.items() if value not in (None, "", [], {})}


def _read_structured(soup: BeautifulSoup, out: dict[str, Any]) -> None:
    """Every entry of every rich section, as JSON columns."""
    import json

    sections = sections_by_heading(soup)

    def store(column: str, value: Any) -> None:
        if value:
            out[column] = json.dumps(value, ensure_ascii=False)

    store("linkedin_experience_json", experience_entries(sections.get(_EXPERIENCE)))
    store("linkedin_education_json", education_entries(sections.get(_EDUCATION)))
    store(
        "linkedin_certifications_json",
        certification_entries(sections.get("licenses & certifications")),
    )
    store("linkedin_projects_json", project_entries(sections.get("projects")))
    store("linkedin_languages_json", language_entries(sections.get("languages")))

    skills = skill_names(sections.get(_SKILLS))
    if skills:
        store("linkedin_skills_json", skills)
        out["linkedin_skills_label"] = ", ".join(skills)

    featured = top_skills(soup)
    if featured:
        out["linkedin_top_skills"] = ", ".join(featured)

    images = image_urls(soup, out.get("scraper_full_name"))
    if images.get("profile"):
        out["linkedin_profile_image_url"] = images["profile"]
    if images.get("background"):
        out["linkedin_background_image_url"] = images["background"]


def _read_section_counts(soup: BeautifulSoup, out: dict[str, Any]) -> None:
    """
    Entry counts, and the lossless section capture.

    LinkedIn's own "(44)" beside a heading is authoritative for how many entries
    exist; the number of rows we managed to read is not the same thing, and
    storing the page's figure is what makes an under-read visible later.
    """
    import json

    sections = collect_sections(soup, out.get("scraper_full_name"))
    if not sections:
        return

    for heading, column in (
        (_SKILLS, "linkedin_skills_count"),
        (_EXPERIENCE, "linkedin_experience_count"),
        (_EDUCATION, "linkedin_education_count"),
    ):
        entry = sections.get(heading)
        if not entry:
            continue
        count = entry.get("count")
        if count is None:
            count = len(entry.get("rows") or []) or None
        if count:
            out[column] = count

    out["linkedin_sections_json"] = json.dumps(sections, ensure_ascii=False, sort_keys=True)


_JUNK_HEADINGS = {
    "join linkedin",
    "sign up",
    "sign in",
    "linkedin",
    "welcome back",
    "security verification",
}


def looks_rendered(soup: BeautifulSoup) -> bool:
    """
    True when the page actually painted a profile.

    Three things this must not treat as evidence, each of which it did at some
    point: an `<h1>` (the authwall has one, the profile has none), a correct
    `<title>` (the shell sets it before the body arrives), and page chrome (the
    signed-in nav renders whether or not the profile does).

    What counts is a named person plus at least one of their content sections.
    """
    headings = {
        key
        for key in sections_by_heading(soup)
        if key not in _JUNK_HEADINGS and not _NOTIFICATION_RE.match(key)
    }
    if not headings:
        return False

    if any(key in headings for key in _CONTENT_HEADINGS):
        name, _ = name_from_title(_clean(soup.title.get_text()) if soup.title else None)
        if name or _top_card(soup, None) is not None:
            return True

    return any(soup.find(id=anchor) is not None for anchor in (_ABOUT, _EXPERIENCE, _SKILLS))
