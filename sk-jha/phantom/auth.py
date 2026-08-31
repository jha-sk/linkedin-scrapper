"""
Access control for the HTTP API.

The API was written for loopback. It has no user model, no sessions, and every
endpoint is fully privileged: queue a run, read every scraped profile, delete an
agent. That was a reasonable design for something reachable only from the
machine it runs on.

The moment the port is reachable from elsewhere, the same design means anyone
who finds the URL can drive your LinkedIn session and download the personal data
of everyone you have scraped. So there are two rules here:

  1. A bearer token is required on `/api/*` whenever one is configured.
  2. Binding to anything other than loopback *without* a token refuses to start.

The second is the important one. An unauthenticated public port is not a
configuration a person chooses deliberately — it is one they arrive at by
forgetting a variable, and the failure is silent until it is not. Refusing to
start converts that into an error message at deploy time.

Tokens are compared with `secrets.compare_digest`, so a wrong guess takes the
same time as any other and the comparison leaks nothing about the prefix.
"""

from __future__ import annotations

import logging
import secrets

from fastapi import HTTPException, Request

from .config import settings

log = logging.getLogger("phantom.auth")

_OPEN_PATHS = {"/healthz"}


class InsecureConfiguration(RuntimeError):
    """Raised at startup for a configuration that would expose the API."""


def verify_startup() -> None:
    """Refuse to serve an unauthenticated API on a reachable address."""
    if settings.is_loopback:
        if settings.api_token:
            log.info("API token set; required on /api/* even on loopback")
        return

    if not settings.api_token:
        raise InsecureConfiguration(
            f"PHANTOM_HOST is {settings.host!r}, which is reachable from other machines, "
            "but PHANTOM_API_TOKEN is not set.\n\n"
            "Every endpoint is fully privileged: an open port lets anyone queue runs "
            "against your LinkedIn session and download every profile you have scraped.\n\n"
            "Set a token:\n"
            "    export PHANTOM_API_TOKEN=$(python -c 'import secrets;print(secrets.token_urlsafe(32))')\n\n"
            "Or bind to loopback and reach it over an SSH tunnel:\n"
            "    export PHANTOM_HOST=127.0.0.1"
        )

    if len(settings.api_token) < 24:
        raise InsecureConfiguration(
            "PHANTOM_API_TOKEN is shorter than 24 characters. A public endpoint can be "
            "guessed at indefinitely; generate one with "
            "`python -c 'import secrets;print(secrets.token_urlsafe(32))'`."
        )

    log.info("API bound to %s with token auth enabled", settings.host)


def _presented_token(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.query_params.get("token") or request.headers.get("x-api-token")


async def require_token(request: Request) -> None:
    """FastAPI dependency guarding the API router."""
    if not settings.api_token:
        return
    if request.url.path in _OPEN_PATHS:
        return
    if request.method == "OPTIONS":
        return

    presented = _presented_token(request)
    if not presented or not secrets.compare_digest(presented, settings.api_token):
        raise HTTPException(
            status_code=401,
            detail="missing or invalid API token",
            headers={"WWW-Authenticate": "Bearer"},
        )
