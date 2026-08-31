"""
Transport layer.

Three ways to get a profile, cheapest first:

  http       plain GET with a browser header set. ~200ms. Answers for many
             public profiles and costs nothing.
  browser    Chromium via Playwright, logged out. Executes JS and presents a
             real TLS fingerprint, which the Python client cannot.
  session    the persistent, hand-signed-in Chromium profile. The only transport
             that sees the authenticated render.

There is no API transport and no cookie injection. Both were removed for the
same reason: presenting a transplanted `li_at` from a freshly launched browser
is what makes LinkedIn invalidate the session. See `phantom/session.py` for the
reasoning — the short version is that a session cookie is only coherent
alongside the device cookies, localStorage, and fingerprint of the browser that
obtained it, and a clean instance has none of those.

Escalation is one-way and logged. Nothing here parses.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from linkedin_public_profile import BLOCK_STATUSES, UA, FetchResult, fetch_http

from .. import session as browser_session
from .dom_profile import looks_rendered

log = logging.getLogger("phantom.fetch")


@dataclass
class PageFetch:
    """What one fetch produced: the document, any detail pages, and how it went."""

    result: FetchResult
    diagnostics: dict[str, Any] = field(default_factory=dict)
    details: dict[str, str] = field(default_factory=dict)

    @property
    def html(self) -> str:
        return self.result.html


@dataclass(frozen=True)
class BrowserOptions:
    headless: bool = True
    timeout_seconds: float = 45.0
    use_session: bool = False


_PROBES = {
    "has_authwall": "authwall",
    "has_challenge": "checkpoint/challenge",
    "has_captcha": "captcha",
    "has_json_ld": "application/ld+json",
}

_PERIMETERX_COOKIES = {"_px3", "_pxvid", "pxcts"}

_RENDER_SELECTORS = "main section h2, main section h1, div#experience, div#about"

_LAZY_HEADINGS = ("Experience", "Education", "Skills")

_CARD_SELECTOR = "[componentkey*='profileCards']"

_HYDRATE_JS = """
() => {
  const cards = Array.from(document.querySelectorAll("[componentkey*='profileCards']"));
  const empty = cards.filter(el => !(el.innerText || '').trim());
  if (empty.length) empty[0].scrollIntoView({block: 'center'});
  return {total: cards.length, filled: cards.length - empty.length};
}
"""

_LOGGED_OUT_MARKERS = ("authwall", "uas/login", "/signup")


def _slug_of(url: str) -> str:
    return urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]


def fetch_logged_out(url: str, opts: BrowserOptions) -> PageFetch:
    """A throwaway Chromium with no stored identity. Public view only."""
    from playwright.sync_api import sync_playwright

    from .. import browser as browser_config

    choice = browser_config.choose(headless=opts.headless)
    diagnostics: dict[str, Any] = {"transport": "browser", "browser": choice.summary}
    with sync_playwright() as p:
        browser = p.chromium.launch(**choice.launch_kwargs())
        ctx = browser.new_context(
            user_agent=UA,
            locale=browser_session.LOCALE,
            timezone_id=browser_session.TIMEZONE,
            viewport=browser_session.VIEWPORT,
        )
        ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        page = ctx.new_page()
        try:
            resp = page.goto(
                url, wait_until="domcontentloaded", timeout=opts.timeout_seconds * 1000
            )
            page.wait_for_timeout(random.randint(1400, 2800))
            html = page.content()
            status = resp.status if resp else 0
            final_url = page.url
            diagnostics["title"] = (page.title() or "")[:120]
        finally:
            ctx.close()
            browser.close()

    return _finish(url, final_url, status, html, "browser", diagnostics)


def fetch_with_session(
    url: str, opts: BrowserOptions, detail_sections: tuple[str, ...] = ()
) -> PageFetch:
    """
    Load the profile in an already-signed-in browser, plus any detail pages.

    Two ways to get a signed-in browser, and no cookie is set in either.
    Attaching to a Chrome the user started themselves is preferred when it is
    configured: it is a real browser with real history and extensions, and some
    of what distinguishes a launched Chromium from a used one cannot be patched
    from inside the page. Otherwise the persistent profile is used, which carries
    the cookies LinkedIn issued it during the manual sign-in.

    `detail_sections` names the "Show all" pages to visit afterwards. They are
    fetched in the same browser session rather than by re-launching per page:
    one launch, one navigation each, paced like a person clicking through. Each
    is an extra page view against the account, which is why the caller has to
    ask for them by name rather than getting them by default.
    """
    from playwright.sync_api import sync_playwright

    attached = bool(browser_session.CDP_URL)
    diagnostics: dict[str, Any] = {
        "transport": "session",
        "browser": "attached (CDP)" if attached else "persistent profile",
    }

    if not attached and not browser_session.can_authenticate():
        raise RuntimeError(
            "No signed-in session. Either sign in locally with "
            "`python -m phantom.session login`, or paste a cookie set from a "
            "browser that is already signed in (Connect to LinkedIn in the UI)."
        )

    details: dict[str, str] = {}

    with sync_playwright() as p:
        if attached:
            ctx = browser_session.open_cdp(p)
            page = ctx.new_page()
        else:
            ctx = browser_session.open_context(p, headless=opts.headless)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            resp = page.goto(
                url, wait_until="domcontentloaded", timeout=opts.timeout_seconds * 1000
            )
            status = resp.status if resp else 0

            try:
                page.wait_for_selector(_RENDER_SELECTORS, timeout=20_000)
                diagnostics["render"] = "selector matched"
            except Exception:
                diagnostics["render"] = "no profile content within 20s"

            diagnostics["lazy_sections"] = _scroll_until_loaded(page)

            html = page.content()
            final_url = page.url
            diagnostics["title"] = (page.title() or "")[:120]
            diagnostics["h1"] = _first_text(page, "main h1")
            diagnostics["cookies"] = sorted({c["name"] for c in ctx.cookies()})
            diagnostics["signed_in"] = "li_at" in diagnostics["cookies"]
            diagnostics["has_perimeterx"] = bool(
                _PERIMETERX_COOKIES & set(diagnostics["cookies"])
            )

            if detail_sections:
                details, notes = _fetch_details(page, url, detail_sections, opts)
                diagnostics["details"] = notes
        finally:
            if attached:
                page.close()
            else:
                ctx.close()

    fetched = _finish(url, final_url, status, html, "session", diagnostics)
    fetched.details = details
    return fetched


def _fetch_details(
    page, profile_url: str, sections: tuple[str, ...], opts: BrowserOptions
) -> tuple[dict[str, str], dict[str, str]]:
    """
    Visit each section's "Show all" page and keep its HTML.

    A failure on one section is recorded and the rest continue: a profile with
    no Projects page should not cost the Skills page, and "this section does not
    exist" is a normal answer rather than an error.
    """
    from .dom_profile import detail_url

    slug = profile_url.rstrip("/").rsplit("/", 1)[-1]
    captured: dict[str, str] = {}
    notes: dict[str, str] = {}

    for section in sections:
        target = detail_url(slug, section)
        try:
            page.wait_for_timeout(random.randint(1800, 4200))
            response = page.goto(
                target, wait_until="domcontentloaded", timeout=opts.timeout_seconds * 1000
            )
            status = response.status if response else 0
            if redirected_to_auth(page.url):
                notes[section] = "redirected to sign-in — stopping detail pass"
                break
            try:
                page.wait_for_selector("main section, main ul", timeout=12_000)
            except Exception:
                pass
            _scroll_to_bottom(page)
            captured[section] = page.content()
            notes[section] = f"{status}, {len(captured[section]):,} bytes"
        except Exception as exc:
            notes[section] = f"failed: {type(exc).__name__}"
    return captured, notes


def _scroll_to_bottom(page, rounds: int = 12) -> None:
    """
    Page through a detail list until it stops growing.

    These lists paginate on scroll, so stopping at a fixed count returns a
    prefix — which is indistinguishable from a profile that simply has fewer
    entries, and is exactly the failure "all skills" has to avoid.
    """
    previous = 0
    for _ in range(rounds):
        page.mouse.wheel(0, random.randint(900, 1600))
        page.wait_for_timeout(random.randint(500, 1100))
        try:
            height = page.evaluate("document.body.scrollHeight")
        except Exception:
            break
        if height == previous:
            break
        previous = height


def _finish(
    url: str,
    final_url: str,
    status: int,
    html: str,
    transport: str,
    diagnostics: dict[str, Any],
) -> PageFetch:
    for name, needle in _PROBES.items():
        diagnostics[name] = needle in html
    diagnostics["rendered"] = looks_rendered(BeautifulSoup(html, "lxml"))
    log.info(
        "%s GET -> %s (%d bytes, rendered=%s)",
        transport,
        status,
        len(html),
        diagnostics["rendered"],
    )
    return PageFetch(
        result=FetchResult(
            url=url, final_url=final_url, status=status, html=html, transport=transport
        ),
        diagnostics=diagnostics,
    )


def _first_text(page, selector: str) -> str:
    try:
        node = page.query_selector(selector)
        return (node.inner_text() if node else "").strip()[:120]
    except Exception:
        return ""


def _scroll_until_loaded(page, budget_seconds: float = 45.0) -> str:
    """
    Scroll down until the lazy sections arrive, or the budget runs out.

    The previous version scrolled a fixed number of times and snapshotted. That
    is a race it usually lost: Experience, Education, and Skills hydrate on
    scroll, and a page captured mid-hydration looks identical to a profile that
    genuinely has none of them.

    Scrolling remains uneven and paced, because a constant interval is itself a
    fingerprint. Returns which sections were seen, for the diagnostics.
    """
    import time as _time

    deadline = _time.monotonic() + budget_seconds
    seen: set[str] = set()
    filled = 0
    stalled = 0

    while _time.monotonic() < deadline:
        for heading in _LAZY_HEADINGS:
            if heading in seen:
                continue
            try:
                if page.query_selector(f"main section h2:text-is('{heading}')") is not None:
                    seen.add(heading)
            except Exception:
                pass

        if len(seen) == len(_LAZY_HEADINGS):
            break

        try:
            state = page.evaluate(_HYDRATE_JS)
        except Exception:
            state = None

        if state:
            if state["filled"] > filled:
                filled = state["filled"]
                stalled = 0
            else:
                stalled += 1
            if state["total"] and state["filled"] >= state["total"]:
                break
            if stalled >= 4 and filled:
                break

        page.mouse.wheel(0, random.randint(500, 1000))
        page.wait_for_timeout(random.randint(400, 1100))

    page.wait_for_timeout(random.randint(900, 1800))
    page.mouse.wheel(0, -random.randint(200, 600))
    page.wait_for_timeout(random.randint(250, 600))

    try:
        final = page.evaluate(_HYDRATE_JS)
        cards = f"{final['filled']}/{final['total']} cards hydrated"
    except Exception:
        cards = "card state unknown"
    if not seen:
        return f"no headings appeared ({cards})"
    return f"{', '.join(sorted(seen))} ({cards})"


def fetch(
    url: str,
    use_session: bool = True,
    headless: bool = False,
    detail_sections: tuple[str, ...] = (),
) -> PageFetch:
    """
    Escalating fetch. Returns the best response obtained, never raises on block.

    Headed by default for session runs: a headless Chromium differs from a
    headed one in ways a fingerprinter reads for free, and this transport's
    whole purpose is to look like the browser that signed in.
    """
    if use_session:
        return fetch_with_session(
            url,
            BrowserOptions(headless=headless, use_session=True),
            detail_sections=detail_sections,
        )

    result = fetch_http(url)
    if not authwall_reason(result) and "application/ld+json" in result.html:
        return PageFetch(result=result, diagnostics={"transport": "http"})

    log.info("escalating to browser transport (%s)", authwall_reason(result) or "no JSON-LD")
    try:
        return fetch_logged_out(url, BrowserOptions(headless=True))
    except Exception as exc:
        log.warning("browser escalation unavailable: %s", exc)
        return PageFetch(result=result, diagnostics={"transport": "http"})



_AUTH_PATHS = (
    "/authwall",
    "/login",
    "/uas/login",
    "/checkpoint/",
    "/signup",
    "/m/login",
)


def redirected_to_auth(final_url: str) -> bool:
    """True when LinkedIn navigated us away from the profile to a sign-in path."""
    path = urlparse(final_url).path.lower()
    return any(path.startswith(marker) or marker in path for marker in _AUTH_PATHS)


def authwall_reason(
    result: FetchResult,
    expect_slug: str | None = None,
    rendered: bool | None = None,
) -> str | None:
    """
    Why this response is a wall rather than a profile, or None if it is fine.

    Order matters: unambiguous signals first, and the ambiguous marker sniffing
    is only consulted for the transport where it is reliable.
    """
    if result.status in BLOCK_STATUSES:
        return f"LinkedIn returned HTTP {result.status}"

    if redirected_to_auth(result.final_url):
        return f"redirected to {urlparse(result.final_url).path} instead of the profile"

    if result.transport == "session":
        if rendered:
            return None
        if any(marker in result.final_url.lower() for marker in _LOGGED_OUT_MARKERS):
            return "the browser profile is signed out — run: python -m phantom.session login"
        return (
            "signed in, but no profile content was found in the page. Either "
            "LinkedIn did not hydrate for this client, or its markup changed. "
            "Run: python -m phantom.doctor <url> --outline"
        )

    return "LinkedIn served the sign-in wall" if result.blocked else None
