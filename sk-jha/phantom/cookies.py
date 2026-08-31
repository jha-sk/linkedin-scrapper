"""
Parsing and grading a pasted LinkedIn cookie set.

An earlier version of this project accepted a bare `li_at` and injected it into
a freshly launched browser. That reliably got the account signed out, because a
session cookie is only coherent alongside the rest of the state the browser that
obtained it holds: the `bcookie`/`bscookie` device pair, `JSESSIONID`, the user
agent, the locale. Presented alone, every other signal contradicts it and the
safe reading is that the session was stolen.

The difference here is completeness. A full cookie set, captured from a browser
that is already signed in and replayed together with that browser's user agent,
is close to what the extension-based tools send. It is still a transplant and
still worse than moving the browser profile itself, so this module's job is to
be explicit about how complete a given paste is rather than to accept anything
that contains `li_at` and call it a session.

Three input shapes are accepted, because people arrive with whichever their
tooling produced:

  1. a JSON array from a cookie-export extension
  2. a `document.cookie` / request-header string: `a=1; b=2`
  3. a bare `li_at` value — accepted, and graded as the weak case it is
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("phantom.cookies")

LINKEDIN_DOMAIN = ".linkedin.com"

ESSENTIAL = {
    "li_at": "the session itself — nothing works without it",
}
IMPORTANT = {
    "JSESSIONID": "CSRF token; some requests are rejected without it",
    "bcookie": "browser device id — its absence is the loudest mismatch",
    "bscookie": "signed device id, checked alongside bcookie",
}
USEFUL = {
    "liap": "marks the session as authenticated on www; not always set",
    "lidc": "datacenter routing hint",
    "li_sugr": "device continuity signal",
    "lang": "interface language",
    "li_theme": "theme preference, part of a consistent profile",
    "timezone": "client timezone, cross-checked against behaviour",
}

_BARE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-]{20,}$")


@dataclass
class CookieSet:
    cookies: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def names(self) -> set[str]:
        return {cookie["name"] for cookie in self.cookies}

    @property
    def has_session(self) -> bool:
        return "li_at" in self.names

    @property
    def missing_important(self) -> list[str]:
        return sorted(name for name in IMPORTANT if name not in self.names)

    @property
    def grade(self) -> str:
        """
        How likely this set is to survive being replayed.

        Deliberately blunt. "complete" and "minimal" behave very differently and
        a user who pasted only `li_at` should be told that before a run burns
        their session, not after.
        """
        if not self.has_session:
            return "unusable"
        missing = self.missing_important
        if not missing:
            return "complete"
        if len(missing) <= 2:
            return "partial"
        return "minimal"

    @property
    def advice(self) -> str:
        return {
            "unusable": "No li_at cookie — this is not a session.",
            "complete": (
                "All device cookies present. This is as close to the source browser "
                "as a cookie transplant gets."
            ),
            "partial": (
                "Missing "
                + ", ".join(self.missing_important)
                + ". Workable, but re-export the full set if the session drops."
            ),
            "minimal": (
                "Only the session cookie and little else. This is the configuration "
                "that gets accounts signed out — export every linkedin.com cookie, "
                "not just li_at."
            ),
        }[self.grade]

    def to_playwright(self) -> list[dict[str, Any]]:
        """Normalised for `context.add_cookies`."""
        prepared: list[dict[str, Any]] = []
        for cookie in self.cookies:
            entry: dict[str, Any] = {
                "name": cookie["name"],
                "value": cookie["value"],
                "domain": cookie.get("domain") or LINKEDIN_DOMAIN,
                "path": cookie.get("path") or "/",
            }
            if isinstance(cookie.get("expires"), (int, float)) and cookie["expires"] > 0:
                entry["expires"] = float(cookie["expires"])
            if isinstance(cookie.get("httpOnly"), bool):
                entry["httpOnly"] = cookie["httpOnly"]
            if isinstance(cookie.get("secure"), bool):
                entry["secure"] = cookie["secure"]
            same_site = (cookie.get("sameSite") or "").capitalize()
            if same_site in {"Strict", "Lax", "None"}:
                entry["sameSite"] = same_site
            prepared.append(entry)
        return prepared

    def summary(self) -> dict[str, Any]:
        """Safe to show in the UI: names and grade, never values."""
        return {
            "count": len(self.cookies),
            "names": sorted(self.names),
            "grade": self.grade,
            "advice": self.advice,
            "missing_important": self.missing_important,
            "warnings": self.warnings,
        }


def parse(raw: str) -> CookieSet:
    """Accept whichever shape the user's tooling produced."""
    text = (raw or "").strip()
    if not text:
        return CookieSet(warnings=["empty input"])

    if text.startswith("[") or text.startswith("{"):
        return _from_json(text)
    if "=" in text:
        return _from_header(text)
    if _BARE_TOKEN_RE.match(text):
        return CookieSet(
            cookies=[_cookie("li_at", text)],
            warnings=[
                "a bare li_at was pasted; export the full cookie set for a session "
                "that survives"
            ],
        )
    return CookieSet(warnings=["could not recognise this as cookies"])


def _cookie(name: str, value: str, **extra: Any) -> dict[str, Any]:
    entry = {"name": name, "value": value, "domain": LINKEDIN_DOMAIN, "path": "/"}
    entry.update(extra)
    return entry


def _from_json(text: str) -> CookieSet:
    try:
        payload = json.loads(text)
    except ValueError as exc:
        return CookieSet(warnings=[f"invalid JSON: {exc}"])

    if isinstance(payload, dict):
        for key in ("cookies", "data", "value"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
        else:
            if all(isinstance(v, str) for v in payload.values()):
                return CookieSet(
                    cookies=[_cookie(name, value) for name, value in payload.items()]
                )
            return CookieSet(warnings=["JSON object did not contain a cookie array"])

    if not isinstance(payload, list):
        return CookieSet(warnings=["expected a JSON array of cookies"])

    cookies: list[dict[str, Any]] = []
    warnings: list[str] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        value = item.get("value")
        if not name or value is None:
            continue
        domain = item.get("domain") or LINKEDIN_DOMAIN
        if "linkedin.com" not in domain:
            warnings.append(f"dropped non-LinkedIn cookie {name} from {domain}")
            continue
        cookies.append(
            _cookie(
                str(name),
                str(value),
                domain=domain,
                path=item.get("path") or "/",
                expires=item.get("expirationDate") or item.get("expires"),
                httpOnly=item.get("httpOnly"),
                secure=item.get("secure"),
                sameSite=item.get("sameSite"),
            )
        )

    if warnings:
        dropped = len(warnings)
        warnings = warnings[:3]
        if dropped > 3:
            warnings.append(f"... and {dropped - 3} more non-LinkedIn cookies dropped")
    return CookieSet(cookies=cookies, warnings=warnings)


def _from_header(text: str) -> CookieSet:
    """Parse `a=1; b=2`, as copied from DevTools or `document.cookie`."""
    cookies: list[dict[str, Any]] = []
    for part in re.split(r";\s*", text.strip()):
        if not part or "=" not in part:
            continue
        name, _, value = part.partition("=")
        name = name.strip()
        value = value.strip().strip('"')
        if name and value:
            cookies.append(_cookie(name, value))
    if not cookies:
        return CookieSet(warnings=["no name=value pairs found"])
    return CookieSet(cookies=cookies)
