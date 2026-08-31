#!/usr/bin/env python3
"""
linkedin_public_profile.py
==========================

Extracts structured data from a *public* LinkedIn profile URL.

Usage
-----
    pip install httpx beautifulsoup4 lxml
    # optional, for the browser escalation path:
    pip install playwright && playwright install chromium

    python linkedin_public_profile.py https://www.linkedin.com/in/<slug>
    python linkedin_public_profile.py <url> --browser          # skip straight to Playwright
    python linkedin_public_profile.py <url> --out profile.json
    python linkedin_public_profile.py <url> --no-cache -v


Design
------
FETCH — cheapest transport first, escalate only on failure:

    1. Plain HTTP GET with a realistic browser header set. Costs ~200ms.
       Succeeds more often than people expect for public profiles.
    2. Playwright + Chromium. Costs ~5s and a browser download, but executes
       JS and presents a real TLS fingerprint.

    Escalation is automatic and one-way. There is no point paying for a
    browser on a request that a plain GET already answered.

PARSE — most stable extractor first, each one a fallback for the last:

    1. JSON-LD (`<script type="application/ld+json">`, schema.org Person).
       LinkedIn emits this so search engines can index public profiles.
       It is a documented, stable contract and it is what this scraper
       is built around.
    2. OpenGraph / `profile:*` meta tags. Also SEO surface, also stable,
       but coarser — mostly name and a headline blob that needs splitting.
    3. DOM selectors. LinkedIn's class names are obfuscated and rotate,
       so this layer is expected to rot. It exists to catch fields the
       first two miss, never as the primary path.

    Results merge with layer 1 winning ties, so a stale DOM selector can
    never overwrite good structured data.

Known limits — see README_NOTES.md. Read it before running this in anger.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional

try:
    import httpx
except ImportError:
    sys.exit("Missing dependency: pip install httpx beautifulsoup4 lxml")

from bs4 import BeautifulSoup

log = logging.getLogger("linkedin")


UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

BROWSER_HEADERS = {
    "User-Agent": UA,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Ch-Ua": '"Chromium";v="126", "Not(A:Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

BLOCK_STATUSES = {403, 429, 999}

AUTHWALL_MARKERS = (
    "/authwall",
    "authwall-join-form",
    "join-form__form-body",
    "Sign in to view",
    "Join LinkedIn to see",
)

PROFILE_URL_RE = re.compile(
    r"^https?://([a-z]{2,3}\.)?linkedin\.com/in/[^/?#]+", re.IGNORECASE
)




@dataclass
class Profile:
    url: Optional[str] = None
    slug: Optional[str] = None
    name: Optional[str] = None
    headline: Optional[str] = None
    location: Optional[str] = None
    about: Optional[str] = None
    current_company: Optional[str] = None
    job_title: Optional[str] = None
    experience: list[dict[str, Any]] = field(default_factory=list)
    education: list[dict[str, Any]] = field(default_factory=list)
    image_url: Optional[str] = None
    external_links: list[str] = field(default_factory=list)
    follower_count: Optional[int] = None

    _sources: dict[str, str] = field(default_factory=dict, repr=False)

    def merge(self, other: "Profile", source: str) -> None:
        """Fill only fields we don't already have. First writer wins."""
        for key, value in asdict(other).items():
            if key.startswith("_"):
                continue
            if not value:
                continue
            if not getattr(self, key):
                setattr(self, key, value)
                self._sources[key] = source

    def to_dict(self, with_provenance: bool = False) -> dict[str, Any]:
        d = {k: v for k, v in asdict(self).items() if not k.startswith("_")}
        if with_provenance:
            d["_sources"] = self._sources
        return d

    @property
    def is_usable(self) -> bool:
        return bool(self.name)


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    html: str
    transport: str

    @property
    def blocked(self) -> bool:
        if self.status in BLOCK_STATUSES:
            return True
        head = self.html[:60_000]
        return any(m in head for m in AUTHWALL_MARKERS)




def _sleep_backoff(attempt: int, base: float = 2.0, cap: float = 30.0) -> None:
    """Exponential backoff with full jitter — avoids retry thundering."""
    delay = min(cap, base * (2 ** attempt))
    delay = random.uniform(0, delay)
    log.debug("backing off %.1fs before retry %d", delay, attempt + 1)
    time.sleep(delay)


def fetch_http(url: str, timeout: float = 20.0, retries: int = 2) -> FetchResult:
    """Plain HTTP. Cheap. Try this first, always."""
    last: Optional[FetchResult] = None
    with httpx.Client(
        headers=BROWSER_HEADERS,
        follow_redirects=True,
        timeout=timeout,
        http2=True,
    ) as client:
        for attempt in range(retries + 1):
            if attempt:
                _sleep_backoff(attempt - 1)
            try:
                r = client.get(url)
            except httpx.HTTPError as exc:
                log.warning("http transport error: %s", exc)
                continue
            last = FetchResult(
                url=url,
                final_url=str(r.url),
                status=r.status_code,
                html=r.text,
                transport="http",
            )
            log.info("http GET -> %s (%d bytes)", r.status_code, len(r.text))
            if not last.blocked:
                return last
            log.info("http response looks blocked/authwalled")
    if last is None:
        raise RuntimeError(f"all HTTP attempts failed for {url}")
    return last


def fetch_browser(url: str, timeout: float = 40.0, headless: bool = True) -> FetchResult:
    """Real Chromium. Slower, but executes JS and presents a genuine TLS fingerprint."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "Playwright not installed. "
            "Run: pip install playwright && playwright install chromium"
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            user_agent=UA,
            locale="en-US",
            timezone_id="Asia/Kolkata",
            viewport={"width": 1440, "height": 900},
        )
        ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        page = ctx.new_page()
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            page.wait_for_timeout(random.randint(1200, 2600))
            html = page.content()
            status = resp.status if resp else 0
            final_url = page.url
        finally:
            browser.close()

    log.info("browser GET -> %s (%d bytes)", status, len(html))
    return FetchResult(
        url=url, final_url=final_url, status=status, html=html, transport="browser"
    )


def fetch(url: str, force_browser: bool = False, headless: bool = True) -> FetchResult:
    """Escalating fetch: HTTP, then browser only if HTTP came back unusable."""
    if force_browser:
        return fetch_browser(url, headless=headless)

    result = fetch_http(url)
    if not result.blocked and _has_jsonld(result.html):
        return result

    log.info("escalating to browser transport")
    try:
        return fetch_browser(url, headless=headless)
    except RuntimeError as exc:
        log.warning("browser escalation unavailable: %s", exc)
        return result


def _has_jsonld(html: str) -> bool:
    return "application/ld+json" in html




def _walk_jsonld(soup: BeautifulSoup) -> Iterator[dict[str, Any]]:
    """Yield every dict node inside every ld+json block, @graph included."""
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            log.debug("skipping malformed ld+json block")
            continue
        stack: list[Any] = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                yield node
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)


def _types(node: dict[str, Any]) -> set[str]:
    t = node.get("@type")
    if isinstance(t, str):
        return {t}
    if isinstance(t, list):
        return {x for x in t if isinstance(x, str)}
    return set()


def _name_of(value: Any) -> Optional[str]:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("name") or value.get("legalName")
    if isinstance(value, list) and value:
        return _name_of(value[0])
    return None


def parse_jsonld(soup: BeautifulSoup) -> Profile:
    p = Profile()
    person: Optional[dict[str, Any]] = None

    for node in _walk_jsonld(soup):
        if "Person" in _types(node) and node.get("name"):
            person = node
            break

    if person is None:
        log.info("jsonld: no Person node found")
        return p

    log.info("jsonld: Person node found")

    p.name = person.get("name")
    p.about = person.get("description")
    p.job_title = _name_of(person.get("jobTitle"))
    p.image_url = _name_of(person.get("image")) or (
        person.get("image", {}).get("contentUrl")
        if isinstance(person.get("image"), dict)
        else None
    )

    addr = person.get("address")
    if isinstance(addr, dict):
        parts = [
            addr.get("addressLocality"),
            addr.get("addressRegion"),
            addr.get("addressCountry"),
        ]
        p.location = ", ".join(x for x in parts if isinstance(x, str) and x)
    elif isinstance(addr, str):
        p.location = addr

    works_for = person.get("worksFor")
    if isinstance(works_for, list):
        for org in works_for:
            if not isinstance(org, dict):
                continue
            entry = {
                "company": org.get("name"),
                "url": org.get("url"),
                "location": _name_of(org.get("location")),
            }
            p.experience.append({k: v for k, v in entry.items() if v})
        if p.experience:
            p.current_company = p.experience[0].get("company")
    elif works_for:
        p.current_company = _name_of(works_for)

    alumni = person.get("alumniOf")
    if isinstance(alumni, list):
        for school in alumni:
            if not isinstance(school, dict):
                continue
            entry = {
                "school": school.get("name"),
                "url": school.get("url"),
                "start": (school.get("startDate") or None),
                "end": (school.get("endDate") or None),
            }
            p.education.append({k: v for k, v in entry.items() if v})
    elif alumni:
        name = _name_of(alumni)
        if name:
            p.education.append({"school": name})

    same_as = person.get("sameAs")
    if isinstance(same_as, list):
        p.external_links = [x for x in same_as if isinstance(x, str)]
    elif isinstance(same_as, str):
        p.external_links = [same_as]

    inter = person.get("interactionStatistic")
    if isinstance(inter, dict):
        count = inter.get("userInteractionCount")
        if isinstance(count, (int, float)):
            p.follower_count = int(count)

    return p




def parse_meta(soup: BeautifulSoup) -> Profile:
    p = Profile()

    def meta(prop: str) -> Optional[str]:
        tag = soup.find("meta", attrs={"property": prop}) or soup.find(
            "meta", attrs={"name": prop}
        )
        if tag:
            content = tag.get("content")
            return content.strip() if content else None
        return None

    first = meta("profile:first_name")
    last = meta("profile:last_name")
    if first or last:
        p.name = " ".join(x for x in (first, last) if x)

    og_title = meta("og:title")
    if og_title and not p.name:
        p.name = re.split(r"\s+[-|]\s+", og_title)[0].strip() or None

    if og_title and " - " in og_title:
        segments = [s.strip() for s in og_title.split(" - ")]
        if len(segments) >= 2:
            p.headline = segments[1].removesuffix(" | LinkedIn").strip() or None

    desc = meta("og:description")
    if desc:
        p.about = desc

    img = meta("og:image")
    if img:
        p.image_url = img

    if p.name or p.headline:
        log.info("meta: recovered name/headline")
    return p




def parse_dom(soup: BeautifulSoup) -> Profile:
    """
    LinkedIn's public-profile markup uses generated class names that rotate.
    Every selector here is expected to break eventually. This layer only ever
    fills gaps the structured layers left, and it is silent on failure.
    """
    p = Profile()

    h1 = soup.find("h1")
    if h1:
        text = h1.get_text(strip=True)
        if text and len(text) < 120:
            p.name = text

    for selector in (
        "div.text-body-medium",
        "h2.top-card-layout__headline",
        "div.top-card-layout__headline",
    ):
        node = soup.select_one(selector)
        if node:
            text = node.get_text(strip=True)
            if text:
                p.headline = text
                break

    for selector in (
        "span.text-body-small.inline",
        "div.top-card__subline-item",
        "span.top-card-layout__first-subline",
    ):
        node = soup.select_one(selector)
        if node:
            text = node.get_text(strip=True)
            if text and "follower" not in text.lower():
                p.location = text
                break

    for node in soup.select("span, div"):
        text = node.get_text(strip=True)
        m = re.fullmatch(r"([\d,]+)\s+followers?", text or "", re.IGNORECASE)
        if m:
            p.follower_count = int(m.group(1).replace(",", ""))
            break

    return p




def slug_from_url(url: str) -> Optional[str]:
    m = re.search(r"/in/([^/?#]+)", url)
    return m.group(1) if m else None


def scrape(
    url: str,
    force_browser: bool = False,
    headless: bool = True,
    cache_dir: Optional[Path] = None,
) -> tuple[Profile, FetchResult]:
    if not PROFILE_URL_RE.match(url):
        raise ValueError(f"not a LinkedIn /in/ profile URL: {url}")

    html: Optional[str] = None
    cache_path: Optional[Path] = None

    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(url.encode()).hexdigest()[:16]
        cache_path = cache_dir / f"{key}.html"
        if cache_path.exists():
            log.info("cache hit: %s", cache_path)
            html = cache_path.read_text(encoding="utf-8")

    if html is None:
        result = fetch(url, force_browser=force_browser, headless=headless)
        html = result.html
        if cache_path:
            cache_path.write_text(html, encoding="utf-8")
    else:
        result = FetchResult(
            url=url, final_url=url, status=200, html=html, transport="cache"
        )

    soup = BeautifulSoup(html, "lxml")

    profile = Profile(url=result.final_url, slug=slug_from_url(url))
    profile._sources["url"] = "input"

    for extractor, label in (
        (parse_jsonld, "jsonld"),
        (parse_meta, "meta"),
        (parse_dom, "dom"),
    ):
        try:
            profile.merge(extractor(soup), label)
        except Exception as exc:
            log.warning("%s extractor failed: %s", label, exc)

    return profile, result




def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Extract structured data from a public LinkedIn profile URL."
    )
    ap.add_argument("url", help="https://www.linkedin.com/in/<slug>")
    ap.add_argument("--browser", action="store_true", help="force the Playwright path")
    ap.add_argument("--headful", action="store_true", help="show the browser window")
    ap.add_argument("--out", type=Path, help="write JSON here instead of stdout")
    ap.add_argument("--no-cache", action="store_true", help="bypass the HTML cache")
    ap.add_argument("--provenance", action="store_true", help="include _sources map")
    ap.add_argument("--save-html", type=Path, help="dump raw HTML for debugging")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s %(message)s",
        stream=sys.stderr,
    )

    try:
        profile, result = scrape(
            args.url,
            force_browser=args.browser,
            headless=not args.headful,
            cache_dir=None if args.no_cache else Path(".cache"),
        )
    except Exception as exc:
        log.error("%s", exc)
        return 2

    if args.save_html:
        args.save_html.write_text(result.html, encoding="utf-8")
        log.info("wrote raw HTML to %s", args.save_html)

    payload = profile.to_dict(with_provenance=args.provenance)
    text = json.dumps(payload, indent=2, ensure_ascii=False)

    if args.out:
        args.out.write_text(text, encoding="utf-8")
        log.info("wrote %s", args.out)
    else:
        print(text)

    if not profile.is_usable:
        log.error(
            "no name extracted — transport=%s status=%s blocked=%s. "
            "Retry with --browser, or --save-html to inspect what came back.",
            result.transport,
            result.status,
            result.blocked,
        )
        return 1

    log.info("extracted via %s transport", result.transport)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
