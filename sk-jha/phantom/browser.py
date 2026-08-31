"""
Browser selection and launch options.

One place decides which binary runs and how, because the answer differs between
a laptop and a server and the difference is easy to get subtly wrong.

**Headless is not the problem on a VPS.** A server with no display runs headless
Chrome normally, and runs *headed* Chrome too under Xvfb — a virtual framebuffer
that gives a real windowed browser somewhere to draw. Neither needs a monitor.

**The headless mode matters more than the binary.** Playwright's default
headless is a separate, smaller build (`chromium-headless-shell`) whose
behaviour differs from real Chrome in ways a fingerprinter reads immediately:
missing codecs, no GPU stack, a different user-agent lineage. Selecting the
`chromium` channel runs the full browser in its modern headless mode instead —
the same binary a headed run uses, without the window. That single choice is
worth more than any launch flag.

Order of preference, most convincing to least:

  1. headed real Chrome (`channel=chrome`), under Xvfb on a server
  2. headed Chromium
  3. headless full Chromium (`channel=chromium`)
  4. headless shell — Playwright's default, and the most detectable

`PHANTOM_BROWSER_EXECUTABLE` overrides everything, which is how a specific build
such as ungoogled-chromium is used. Worth knowing before choosing one: removing
Google integration is a privacy improvement and a fingerprint *change*, and the
target here compares against the population of real Chrome users. A de-Googled
build is further from that population, not closer.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("phantom.browser")

_BASE_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-features=IsolateOrigins,site-per-process",
]

_NO_SANDBOX_ARGS = ["--no-sandbox", "--disable-setuid-sandbox"]


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class BrowserChoice:
    channel: str | None
    executable_path: str | None
    headless: bool
    args: list[str]
    display: str | None

    @property
    def summary(self) -> str:
        if self.executable_path:
            what = f"executable {self.executable_path}"
        elif self.channel:
            what = f"channel {self.channel}"
        else:
            what = "playwright default"
        mode = "headless" if self.headless else "headed"
        screen = f", DISPLAY={self.display}" if self.display and not self.headless else ""
        return f"{what}, {mode}{screen}"

    def launch_kwargs(self) -> dict[str, Any]:
        """The subset Playwright accepts, with empty values omitted."""
        kwargs: dict[str, Any] = {"headless": self.headless, "args": list(self.args)}
        if self.executable_path:
            kwargs["executable_path"] = self.executable_path
        elif self.channel:
            kwargs["channel"] = self.channel
        return kwargs


def choose(headless: bool | None = None) -> BrowserChoice:
    """
    Resolve what to launch from the environment.

    `PHANTOM_BROWSER_EXECUTABLE`  absolute path to a binary; wins over channel
    `PHANTOM_BROWSER_CHANNEL`     chrome | chromium | msedge (default chromium)
    `PHANTOM_HEADLESS`            true on a server without Xvfb
    `PHANTOM_NO_SANDBOX`          required in most containers
    `DISPLAY`                     set by Xvfb; headed needs it on a server
    """
    executable = os.environ.get("PHANTOM_BROWSER_EXECUTABLE") or None
    if executable and not os.path.exists(executable):
        log.warning("PHANTOM_BROWSER_EXECUTABLE=%s does not exist; ignoring", executable)
        executable = None

    channel = os.environ.get("PHANTOM_BROWSER_CHANNEL", "chromium").strip() or None
    if channel and channel.lower() in {"none", "default"}:
        channel = None

    display = os.environ.get("DISPLAY") or None
    resolved_headless = _flag("PHANTOM_HEADLESS", False) if headless is None else headless

    if not resolved_headless and not display and os.name != "nt" and _is_linux():
        log.warning(
            "headed requested but DISPLAY is unset — falling back to headless. "
            "Run under Xvfb (xvfb-run -a ...) to keep a headed browser on a server."
        )
        resolved_headless = True

    args = list(_BASE_ARGS)
    if _flag("PHANTOM_NO_SANDBOX", False):
        args += _NO_SANDBOX_ARGS
    if resolved_headless:
        args.append("--disable-gpu")

    return BrowserChoice(
        channel=channel,
        executable_path=executable,
        headless=resolved_headless,
        args=args,
        display=display,
    )


def _is_linux() -> bool:
    import sys

    return sys.platform.startswith("linux")


def xvfb_available() -> bool:
    return shutil.which("Xvfb") is not None or shutil.which("xvfb-run") is not None


def environment_report() -> dict[str, Any]:
    """What the diagnostics print, and what a deployment check looks at."""
    choice = choose()
    return {
        "channel": choice.channel or "playwright default",
        "executable": choice.executable_path or "—",
        "headless": choice.headless,
        "display": choice.display or "—",
        "xvfb_available": xvfb_available(),
        "no_sandbox": _flag("PHANTOM_NO_SANDBOX", False),
        "summary": choice.summary,
    }
