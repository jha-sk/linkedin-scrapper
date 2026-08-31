"""
One profile in, one result row out.

The engine owns the order of operations for a single target and nothing else:
fetch, parse in precedence order, map onto the column contract, optionally
enrich. It has no knowledge of queues, quotas, or persistence — that is the
runner's job — which is what lets it be called directly from a test with a
saved HTML fixture and no network.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from linkedin_public_profile import (
    PROFILE_URL_RE,
    FetchResult,
    Profile,
    parse_dom,
    parse_jsonld,
    parse_meta,
    slug_from_url,
)

from . import voyager
from . import dom_profile
from .fetcher import PageFetch, authwall_reason, fetch
from .mapper import build_row
from ..config import settings

log = logging.getLogger("phantom.engine")


@dataclass
class ScrapeOutcome:
    url: str
    ok: bool
    row: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, str] = field(default_factory=dict)
    transport: str | None = None
    status: int | None = None
    duration_ms: int = 0
    error: str | None = None
    html: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def slug(self) -> str | None:
        return self.row.get("linkedin_profile_slug") or slug_from_url(self.url)


_LINKEDIN_HOST_RE = re.compile(r"^([a-z0-9-]+\.)*linkedin\.com$", re.IGNORECASE)


def normalise_url(raw: str) -> str:
    """
    Canonical form: https://www.linkedin.com/in/<slug>/ — no query, no tracking.

    The host is checked, not just the path. Matching `/in/<slug>` alone would
    quietly rewrite `https://example.com/in/nope` into a real LinkedIn URL and
    scrape a stranger, which is a worse outcome than rejecting the input.
    """
    url = raw.strip()
    if not url:
        raise ValueError("empty URL")

    if "/" not in url and " " not in url:
        return f"https://www.linkedin.com/in/{url.strip('/')}/"

    if not url.lower().startswith(("http://", "https://")):
        url = f"https://{url}"

    parsed = urlparse(url)
    if not _LINKEDIN_HOST_RE.match(parsed.netloc.split(":")[0]):
        raise ValueError(f"not a linkedin.com URL: {raw}")

    slug = slug_from_url(parsed.path)
    if not slug:
        raise ValueError(f"not a LinkedIn /in/ profile URL: {raw}")
    return f"https://www.linkedin.com/in/{slug}/"


def parse_html(
    url: str, html: str, slug: str | None = None
) -> tuple[Profile, dict[str, Any]]:
    """
    Run every extractor over one document. A failing layer never kills the run.

    The rendered DOM outranks the embedded model store. LinkedIn no longer
    server-renders that store into the page, so on a current build it is empty
    and the DOM is the only place the data exists; keeping the store as a
    fallback costs nothing and still works on the older shape.
    """
    soup = BeautifulSoup(html, "lxml")

    rich: dict[str, Any] = {}
    try:
        rich = dom_profile.parse(soup, slug)
    except Exception as exc:
        log.warning("dom extractor failed: %s", exc)

    if not rich:
        try:
            rich = voyager.parse(soup)
        except Exception as exc:
            log.warning("voyager extractor failed: %s", exc)

    profile = Profile(url=url, slug=slug_from_url(url))
    for extractor, label in ((parse_jsonld, "jsonld"), (parse_meta, "meta"), (parse_dom, "dom")):
        try:
            profile.merge(extractor(soup), label)
        except Exception as exc:
            log.warning("%s extractor failed: %s", label, exc)

    return profile, rich


_AUTHWALL_NAMES = {
    "sign up",
    "join linkedin",
    "linkedin",
    "log in or sign up",
    "sign in",
    "linkedin login, sign in",
}


def _rejection_reason(
    result: FetchResult,
    row: dict[str, Any],
    rendered: bool | None = None,
) -> str | None:
    """Why this row is not a usable profile, or None if it is."""
    wall = authwall_reason(result, row.get("linkedin_profile_slug"), rendered)
    if wall:
        return f"blocked — {wall}"

    name = (row.get("scraper_full_name") or "").strip().lower()
    if name in _AUTHWALL_NAMES:
        return (
            f"rejected: the page identified itself as {name!r}, which is the "
            "sign-in wall rather than a profile"
        )

    if not (row.get("scraper_full_name") or row.get("first_name")):
        return "page fetched but no identity fields were extracted"

    if not row.get("linkedin_profile_slug"):
        return "page fetched but carried no profile slug — likely a redirect"

    return None


def _persist_html(slug: str | None, html: str | None) -> None:
    """Write the fetched page to the HTML cache when diagnostics are enabled."""
    if not settings.keep_html or not html:
        return
    try:
        directory = settings.html_cache_dir
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = directory / f"{slug or 'unknown'}-{stamp}.html"
        path.write_text(html, encoding="utf-8")
        path.chmod(0o600)
        log.info("saved page HTML to %s", path)
    except OSError as exc:
        log.warning("could not save page HTML: %s", exc)


def scrape_profile(
    raw_url: str,
    *,
    use_session: bool = True,
    headless: bool = False,
    keep_html: bool = False,
    detail_sections: tuple[str, ...] = (),
) -> ScrapeOutcome:
    started = time.monotonic()
    try:
        url = normalise_url(raw_url)
    except ValueError as exc:
        return ScrapeOutcome(url=raw_url, ok=False, error=str(exc))

    if not PROFILE_URL_RE.match(url):
        return ScrapeOutcome(url=url, ok=False, error="URL failed profile pattern check")

    try:
        page: PageFetch = fetch(
            url,
            use_session=use_session,
            headless=headless,
            detail_sections=detail_sections,
        )
        result = page.result
    except Exception as exc:
        return ScrapeOutcome(
            url=url,
            ok=False,
            error=f"fetch failed: {exc}",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    slug = slug_from_url(url)
    _persist_html(slug, result.html)
    profile, voyager_fields = parse_html(url, result.html, slug)

    for section, detail_html in page.details.items():
        try:
            voyager_fields.update(dom_profile.parse_detail(detail_html, section))
        except Exception as exc:
            log.warning("detail parse failed for %s: %s", section, exc)
    row, provenance = build_row(
        input_url=url,
        profile=profile,
        voyager=voyager_fields,
        scraped_at=datetime.now(timezone.utc),
    )

    duration_ms = int((time.monotonic() - started) * 1000)
    reason = _rejection_reason(result, row, page.diagnostics.get("rendered"))

    if reason:
        return ScrapeOutcome(
            url=url,
            ok=False,
            row=row,
            provenance=provenance,
            transport=result.transport,
            status=result.status,
            duration_ms=duration_ms,
            error=reason,
            html=result.html if keep_html else None,
            diagnostics=page.diagnostics,
        )

    return ScrapeOutcome(
        url=url,
        ok=True,
        row=row,
        provenance=provenance,
        transport=result.transport,
        status=result.status,
        duration_ms=duration_ms,
        html=result.html if keep_html else None,
        diagnostics=page.diagnostics,
    )
