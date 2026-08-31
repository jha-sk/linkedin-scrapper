"""
Persistent browser profile.

The reason a transplanted cookie gets you logged out.

`li_at` is not a bearer token that stands on its own. LinkedIn binds it loosely
to the browser that obtained it — the `bcookie`/`bscookie` device pair, the
user agent, the TLS fingerprint, screen metrics, localStorage, and a history of
prior requests. Copying `li_at` alone into a freshly launched headless Chromium
presents a session whose every other signal disagrees with it. LinkedIn's own
bot vendor (PerimeterX, visible as the `_px3` / `_pxvid` / `pxcts` cookies)
reads that as a stolen session, and the safe response to a stolen session is to
invalidate it. Hence: log in, run the scraper, get logged out.

The fix is not a better cookie. It is to stop transplanting one.

This module keeps a real, persistent Chromium profile on disk. You sign in to it
once, by hand, in a visible window. LinkedIn issues cookies *to that browser*,
and the profile keeps them alongside the localStorage, device cookies, and
history that make them coherent. Every later run reuses the same profile, so the
account sees one consistent device instead of a new suspicious one each time.

That is also, in substance, what the commercial tools do — their browser
extension exists to borrow a session that a real browser already established,
rather than to reconstruct one from a string.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import settings

log = logging.getLogger("phantom.session")

PROFILE_DIR: Path = settings.data_dir / "browser-profile"

VIEWPORT = {"width": 1440, "height": 900}
LOCALE = "en-US"
TIMEZONE = "Asia/Kolkata"


_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
window.chrome = window.chrome || { runtime: {} };
"""


@dataclass
class ProfileStatus:
    exists: bool
    logged_in: bool
    cookie_names: list[str]
    member_id: str | None = None
    source: str = "profile"
    grade: str | None = None

    @property
    def summary(self) -> str:
        if self.source == "cookies":
            return f"signed in via pasted cookies ({self.grade} set)"
        if not self.exists:
            return (
                "not signed in — run `python -m phantom.session login`, "
                "or paste a cookie set in the UI"
            )
        if not self.logged_in:
            return "profile exists but is signed out — sign in again or paste cookies"
        return "signed in"


def profile_exists() -> bool:
    return PROFILE_DIR.exists() and any(PROFILE_DIR.iterdir())


def can_authenticate() -> bool:
    """
    True when a run has some way to be signed in.

    Two routes: a profile signed in by hand, or a cookie set pasted from a
    browser that already is. The second exists because a headless server has no
    way to complete an interactive sign-in.
    """
    return profile_exists() or stored_identity() is not None



CDP_URL: str | None = os.environ.get("PHANTOM_CDP_URL") or None


def open_cdp(playwright, endpoint: str | None = None):
    """
    Attach to an already-running Chrome over the DevTools protocol.

    Returns an existing browser context — never a fresh one — so the tab
    inherits the profile's cookies, storage, and history rather than starting
    empty inside a real browser, which would defeat the point.
    """
    target = endpoint or CDP_URL
    if not target:
        raise RuntimeError("PHANTOM_CDP_URL is not set")

    browser = playwright.chromium.connect_over_cdp(target)
    if not browser.contexts:
        raise RuntimeError(
            f"Connected to {target} but it has no open context. "
            "Open a normal window in that Chrome and try again."
        )
    return browser.contexts[0]


def stored_identity():
    """The pasted cookie set, or None. Decrypted only at launch time."""
    import json

    from sqlalchemy import select

    from .crypto import decrypt
    from .db import session_scope
    from .models import BrowserIdentity

    try:
        with session_scope() as db:
            row = db.scalars(select(BrowserIdentity).order_by(BrowserIdentity.id.desc())).first()
            if row is None:
                return None
            return {
                "cookies": json.loads(decrypt(row.cookies_enc)),
                "user_agent": row.user_agent,
                "locale": row.locale,
                "timezone": row.timezone,
                "viewport": (
                    {"width": row.viewport_width, "height": row.viewport_height}
                    if row.viewport_width and row.viewport_height
                    else None
                ),
                "grade": row.grade,
                "label": row.label,
            }
    except Exception as exc:
        log.debug("no stored browser identity: %s", exc)
        return None


def apply_identity(context, identity: dict | None) -> int:
    """
    Replay a pasted cookie set into a context.

    Returns how many cookies were applied. The user agent and locale are set at
    context creation rather than here, because they cannot be changed afterwards
    and replaying cookies under a different user agent than the browser that
    received them is the mismatch this whole feature has to avoid.
    """
    if not identity or not identity.get("cookies"):
        return 0
    cookies = identity["cookies"]
    try:
        context.add_cookies(cookies)
    except Exception as exc:
        log.error("could not apply stored cookies: %s", exc)
        return 0
    log.info(
        "applied %d stored cookies (%s set)", len(cookies), identity.get("grade", "unknown")
    )
    return len(cookies)


def open_context(playwright, *, headless: bool = False):
    """
    Open the persistent profile.

    Headed by default and that is deliberate. A headless Chromium differs from a
    headed one in ways a fingerprinter can see for free — missing renderer
    behaviour, different `Sec-Ch-Ua` handling, no window chrome. Running visibly
    costs a window on screen and buys a session that survives.
    """
    from . import browser as browser_config

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    choice = browser_config.choose(headless=headless)
    log.info("launching browser: %s", choice.summary)

    identity = stored_identity()
    context = playwright.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        viewport=(identity or {}).get("viewport") or VIEWPORT,
        locale=(identity or {}).get("locale") or LOCALE,
        timezone_id=(identity or {}).get("timezone") or TIMEZONE,
        user_agent=(identity or {}).get("user_agent") or None,
        ignore_default_args=["--enable-automation"],
        **choice.launch_kwargs(),
    )
    context.add_init_script(_STEALTH_JS)

    apply_identity(context, identity)
    return context


def status(headless: bool = True) -> ProfileStatus:
    """Report whether the stored profile is signed in, without navigating anywhere."""
    if not profile_exists():
        identity = stored_identity()
        if identity:
            return ProfileStatus(
                exists=True,
                logged_in=True,
                cookie_names=sorted(c["name"] for c in identity["cookies"]),
                source="cookies",
                grade=identity.get("grade"),
            )
        return ProfileStatus(exists=False, logged_in=False, cookie_names=[], source="none")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        context = open_context(p, headless=headless)
        try:
            cookies = context.cookies("https://www.linkedin.com")
            names = sorted({cookie["name"] for cookie in cookies})
            member = next((c["value"] for c in cookies if c["name"] == "li_at"), None)
        finally:
            context.close()

    return ProfileStatus(
        exists=True,
        logged_in="li_at" in names,
        cookie_names=names,
        member_id="present" if member else None,
    )


def login(timeout_minutes: int = 10) -> int:
    """
    Open a visible browser and wait for the user to sign in by hand.

    Credentials are typed by the person, into LinkedIn's own form, in a real
    window. Nothing in this project reads, stores, or transmits them — the only
    thing that persists is the browser profile LinkedIn writes its cookies into.
    """
    from playwright.sync_api import sync_playwright

    print("Opening a browser window. Sign in to LinkedIn there, by hand.")
    print("Complete any 2FA or verification prompts. This window is your real")
    print("session from now on — the scraper reuses it and never copies cookies.\n")

    deadline = time.monotonic() + timeout_minutes * 60
    with sync_playwright() as p:
        context = open_context(p, headless=False)
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")

            while time.monotonic() < deadline:
                cookies = {c["name"] for c in context.cookies("https://www.linkedin.com")}
                if "li_at" in cookies:
                    page.wait_for_timeout(4000)
                    print("\nSigned in. Profile saved to:")
                    print(f"  {PROFILE_DIR}")
                    print("\nKeep this directory. Deleting it means signing in again.")
                    return 0
                page.wait_for_timeout(2000)

            print("\nTimed out waiting for sign-in.")
            return 1
        finally:
            context.close()


def collect_local_identity(headless: bool = True) -> dict | None:
    """
    Read the signed-in identity out of the local profile.

    Cookies and the user agent together, never cookies alone: replaying a
    session under a different browser identity than the one that received it is
    the mismatch that gets it invalidated. The user agent is read from the
    browser itself rather than assumed, so what the server replays is what this
    machine actually sends.
    """
    if not profile_exists():
        return None

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        try:
            context = open_context(p, headless=headless)
        except Exception as exc:
            raise RuntimeError(
                f"Could not open the local profile: {exc}\n"
                "Close any browser this project has open and try again — Chromium "
                "locks its user data directory."
            ) from exc
        try:
            page = context.pages[0] if context.pages else context.new_page()

            try:
                page.goto(
                    "https://www.linkedin.com/feed/",
                    wait_until="domcontentloaded",
                    timeout=30_000,
                )
                page.wait_for_timeout(1500)
            except Exception as exc:
                log.warning("could not refresh session cookies: %s", exc)

            cookies = [
                cookie
                for cookie in context.cookies("https://www.linkedin.com")
                if "linkedin.com" in (cookie.get("domain") or "")
            ]
            try:
                user_agent = page.evaluate("navigator.userAgent")
                locale = page.evaluate("navigator.language")
                timezone = page.evaluate(
                    "Intl.DateTimeFormat().resolvedOptions().timeZone"
                )
            except Exception:
                user_agent = locale = timezone = None
        finally:
            context.close()

    if not any(cookie["name"] == "li_at" for cookie in cookies):
        return None

    return {
        "cookies": cookies,
        "user_agent": user_agent,
        "locale": locale,
        "timezone": timezone,
        "viewport_width": VIEWPORT["width"],
        "viewport_height": VIEWPORT["height"],
    }


def _grade(identity: dict) -> tuple[str, list[str]]:
    import json as _json

    from .cookies import parse

    parsed = parse(_json.dumps(identity["cookies"]))
    return parsed.grade, parsed.missing_important


def export_cookies(destination: Path, headless: bool = True) -> int:
    """Write the local session as a JSON cookie file, for pasting or uploading."""
    import json as _json

    identity = collect_local_identity(headless=headless)
    if identity is None:
        print("No signed-in local profile. Run: python -m phantom.session login")
        return 1

    destination.write_text(_json.dumps(identity, indent=2), encoding="utf-8")
    os.chmod(destination, 0o600)

    grade, missing = _grade(identity)
    print(f"Wrote {destination} (mode 0600)")
    print(f"  {len(identity['cookies'])} LinkedIn cookies, graded {grade}")
    if missing:
        print(f"  missing: {', '.join(missing)}")
    print("\nThis file is a live LinkedIn session — treat it as a password.")
    return 0


def push(base_url: str, token: str | None, headless: bool = True) -> int:
    """
    Send the local session to a running backend.

    Closes the loop for a server deployment: you are already signed in here, so
    the server does not need its own sign-in and does not need you to copy
    cookies out of DevTools by hand.
    """
    import httpx

    identity = collect_local_identity(headless=headless)
    if identity is None:
        print("No signed-in local profile. Run: python -m phantom.session login")
        return 1

    grade, missing = _grade(identity)
    print(f"Collected {len(identity['cookies'])} LinkedIn cookies, graded {grade}")
    if missing:
        print(f"  missing: {', '.join(missing)}")
    if identity["user_agent"]:
        print(f"  user agent: {identity['user_agent'][:70]}…")

    import json as _json

    payload = {
        "raw": _json.dumps(identity["cookies"]),
        "user_agent": identity["user_agent"],
        "locale": identity["locale"],
        "timezone": identity["timezone"],
        "viewport_width": identity["viewport_width"],
        "viewport_height": identity["viewport_height"],
        "label": f"pushed from {os.uname().nodename}" if hasattr(os, "uname") else "pushed",
    }

    target = f"{base_url.rstrip('/')}/api/session/cookies"
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    if target.startswith("http://") and "localhost" not in target and "127.0.0.1" not in target:
        print(
            f"\nRefusing to send a session over plain HTTP to {base_url}.\n"
            "Use https:// — these cookies are a credential and would cross the "
            "network in clear text."
        )
        return 2

    try:
        response = httpx.put(target, json=payload, headers=headers, timeout=30.0)
    except httpx.HTTPError as exc:
        print(f"\nCould not reach {target}: {exc}")
        return 2

    if response.status_code == 401:
        print("\nRejected: the backend requires an API token. Pass --token or set "
              "PHANTOM_REMOTE_TOKEN.")
        return 2
    if response.status_code >= 400:
        print(f"\nBackend returned {response.status_code}: {response.text[:300]}")
        return 2

    body = response.json()
    print(f"\nPushed to {base_url}")
    print(f"  backend graded it: {body.get('grade')}")
    for warning in body.get("warnings") or []:
        print(f"  warning: {warning}")
    return 0


def export_profile(destination: Path) -> int:
    """
    Package the signed-in profile so it can be moved to a server.

    A headless VPS has no way to complete a sign-in: the flow is interactive,
    involves 2FA, and LinkedIn must issue its cookies to a real browser session.
    The workable order is to sign in on a machine with a screen and move the
    resulting profile.

    The archive contains a live LinkedIn session. Anyone who obtains it is signed
    in as you, without a password and without triggering 2FA. Move it over scp,
    keep it out of version control and object storage, and delete it from both
    ends once it is in place.
    """
    import tarfile

    if not profile_exists():
        print("No profile to export. Run: python -m phantom.session login")
        return 1

    destination = destination.with_suffix(".tar.gz") if not destination.suffixes else destination
    with tarfile.open(destination, "w:gz") as archive:
        archive.add(PROFILE_DIR, arcname="browser-profile")
    os.chmod(destination, 0o600)

    size = destination.stat().st_size
    print(f"Wrote {destination} ({size:,} bytes, mode 0600)")
    print("\nThis archive is a live LinkedIn session — treat it as a password:")
    print("  scp it directly to the server, do not commit or upload it,")
    print("  and delete it from both machines once imported.")
    return 0


def import_profile(archive_path: Path, force: bool = False) -> int:
    """Restore a profile exported elsewhere. Refuses to clobber without --force."""
    import tarfile

    if not archive_path.exists():
        print(f"No such archive: {archive_path}")
        return 1

    if profile_exists() and not force:
        print(f"A profile already exists at {PROFILE_DIR}.")
        print("Re-run with --force to replace it.")
        return 1

    if profile_exists():
        import shutil

        shutil.rmtree(PROFILE_DIR)

    PROFILE_DIR.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as archive:
        members = [m for m in archive.getmembers() if _is_safe_member(m)]
        archive.extractall(PROFILE_DIR.parent, members=members)

    extracted = PROFILE_DIR.parent / "browser-profile"
    if extracted != PROFILE_DIR and extracted.exists():
        extracted.rename(PROFILE_DIR)

    state = status()
    print(f"Imported to {PROFILE_DIR}")
    print(f"State: {state.summary}")
    return 0 if state.logged_in else 1


def _is_safe_member(member) -> bool:
    """
    Reject archive entries that would write outside the target directory.

    A tar member may carry an absolute path or `..` segments and land anywhere
    the process can write. The archive is normally one this project wrote, but
    "normally" is not a security property.
    """
    name = member.name
    if name.startswith("/") or ".." in Path(name).parts:
        log.warning("skipping unsafe archive member: %s", name)
        return False
    if member.issym() or member.islnk():
        log.warning("skipping link member: %s", name)
        return False
    return True


def logout() -> int:
    """Forget the stored profile. The account session itself is untouched."""
    import shutil

    if not profile_exists():
        print("No stored profile.")
        return 0
    shutil.rmtree(PROFILE_DIR)
    print(f"Removed {PROFILE_DIR}")
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m phantom.session",
        description="Manage the persistent LinkedIn browser profile.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("login", help="open a visible browser and sign in by hand")
    sub.add_parser("status", help="report whether the stored profile is signed in")
    sub.add_parser("logout", help="delete the stored profile")

    exporter = sub.add_parser("export", help="package the profile for another machine")
    exporter.add_argument("path", type=Path, help="archive to write, e.g. session.tar.gz")

    importer = sub.add_parser("import", help="restore a profile exported elsewhere")
    importer.add_argument("path", type=Path, help="archive to read")
    importer.add_argument("--force", action="store_true", help="replace an existing profile")

    dumper = sub.add_parser(
        "export-cookies", help="write this machine's session as a JSON cookie file"
    )
    dumper.add_argument("path", type=Path, help="file to write, e.g. cookies.json")

    pusher = sub.add_parser(
        "push", help="send this machine's session to a running backend"
    )
    pusher.add_argument("url", help="backend base URL, e.g. https://scraper.example.com")
    pusher.add_argument(
        "--token",
        default=None,
        help=(
            "API token. Prefer PHANTOM_REMOTE_TOKEN: command-line arguments are "
            "visible to other users in the process list and land in shell history"
        ),
    )

    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)-5s %(message)s")

    if args.command == "login":
        return login()
    if args.command == "logout":
        return logout()
    if args.command == "export":
        return export_profile(args.path)
    if args.command == "import":
        return import_profile(args.path, force=args.force)
    if args.command == "export-cookies":
        return export_cookies(args.path)
    if args.command == "push":
        token = os.environ.get("PHANTOM_REMOTE_TOKEN") or args.token
        if args.token and not os.environ.get("PHANTOM_REMOTE_TOKEN"):
            log.warning(
                "token passed as an argument; prefer PHANTOM_REMOTE_TOKEN so it "
                "stays out of the process list and shell history"
            )
        return push(args.url, token)

    from . import browser as browser_config

    state = status()
    report = browser_config.environment_report()
    print(f"profile dir   {PROFILE_DIR}")
    print(f"state         {state.summary}")
    print(f"browser       {report['summary']}")
    print(f"xvfb          {'available' if report['xvfb_available'] else 'not installed'}")
    if state.cookie_names:
        print(f"cookies       {', '.join(state.cookie_names)}")
    return 0 if state.logged_in else 1


if __name__ == "__main__":
    raise SystemExit(main())
