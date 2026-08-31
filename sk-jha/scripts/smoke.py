#!/usr/bin/env python3
"""
End-to-end check against a running deployment.

Exercises every endpoint the UI depends on, in the order the UI uses them, and
reports what a browser would actually experience. Run it after a deploy, before
trusting the thing.

    python scripts/smoke.py http://127.0.0.1:8000
    PHANTOM_API_TOKEN=... python scripts/smoke.py https://scraper.example.com
    python scripts/smoke.py https://your-app.vercel.app      # through the proxy

The third form is the one that matters for a Vercel deployment: it goes through
the serverless proxy, so it proves the wiring rather than the backend alone. No
token is passed in that case — the proxy holds it, which is the point.

Nothing here launches a browser or scrapes a profile. It creates one temporary
agent, never launches it, and deletes it again.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

import httpx

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"

results: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))
    colour = {"PASS": "\033[32m", "FAIL": "\033[31m", "WARN": "\033[33m", "SKIP": "\033[90m"}
    reset = "\033[0m"
    mark = f"{colour.get(status, '')}{status:<4}{reset}"
    print(f"  {mark} {name}" + (f"  — {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


class Client:
    def __init__(self, base: str, token: str | None) -> None:
        self.base = base.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.http = httpx.Client(timeout=30.0, follow_redirects=False)

    def call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        return self.http.request(
            method, f"{self.base}{path}", headers=self.headers, **kwargs
        )

    def close(self) -> None:
        self.http.close()


def check(client: Client, method: str, path: str, name: str, expect: int = 200) -> Any:
    try:
        response = client.call(method, path)
    except httpx.HTTPError as exc:
        record(FAIL, name, f"unreachable: {exc}")
        return None

    if response.status_code != expect:
        record(FAIL, name, f"expected {expect}, got {response.status_code}")
        return None

    record(PASS, name, f"{response.status_code}")
    try:
        return response.json()
    except ValueError:
        return response.text


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2

    base = argv[1]
    token = os.environ.get("PHANTOM_API_TOKEN") or (argv[2] if len(argv) > 2 else None)
    through_proxy = "vercel.app" in base or os.environ.get("PHANTOM_VIA_PROXY")

    print(f"Target: {base}")
    print(f"Token:  {'supplied' if token else 'none (expected when going via the proxy)'}")

    client = Client(base, token)

    section("Health and metadata")
    health = check(client, "GET", "/healthz", "GET /healthz")
    if isinstance(health, dict):
        if health.get("worker_alive"):
            record(PASS, "worker thread alive")
        else:
            record(FAIL, "worker thread alive", "the runner is not running; launches will queue forever")

    columns = check(client, "GET", "/api/columns", "GET /api/columns")
    if isinstance(columns, list):
        if len(columns) >= 40 and columns[0]["key"] == "company_industry":
            record(PASS, "column contract intact", f"{len(columns)} columns")
        else:
            record(FAIL, "column contract intact", "first 40 columns must be stable")

    quota = check(client, "GET", "/api/quota", "GET /api/quota")
    if isinstance(quota, dict):
        remaining = quota.get("remaining", 0)
        if remaining > 0:
            record(PASS, "daily quota available", f"{remaining} of {quota.get('cap')}")
        else:
            record(WARN, "daily quota available", "exhausted; runs will refuse until UTC midnight")

    section("LinkedIn session")
    session = check(client, "GET", "/api/session", "GET /api/session")
    if isinstance(session, dict):
        if session.get("logged_in"):
            record(PASS, "signed in", f"source: {session.get('source')}, grade: {session.get('grade')}")
            if session.get("source") == "cookies" and session.get("grade") in {"minimal", "partial"}:
                record(WARN, "cookie set completeness", session.get("grade"))
        else:
            record(FAIL, "signed in", session.get("summary", "no session"))
        if "li_at" in json.dumps(session):
            names = session.get("cookie_names") or []
            if any(len(str(n)) > 60 for n in names):
                record(FAIL, "no cookie values leak", "a value appeared in the status payload")
            else:
                record(PASS, "no cookie values leak")

    preview = None
    try:
        response = client.call(
            "POST", "/api/session/cookies/preview", json={"raw": "li_at=xxxxxxxxxxxxxxxxxxxx"}
        )
        preview = response.json() if response.status_code == 200 else None
        record(
            PASS if preview else FAIL,
            "POST /api/session/cookies/preview",
            f"graded {preview.get('grade')}" if preview else f"{response.status_code}",
        )
    except httpx.HTTPError as exc:
        record(FAIL, "POST /api/session/cookies/preview", str(exc))

    section("Agents")
    agents = check(client, "GET", "/api/agents", "GET /api/agents")
    if isinstance(agents, list):
        record(PASS, "agent list", f"{len(agents)} existing")

    created = None
    try:
        response = client.call(
            "POST",
            "/api/agents",
            json={
                "name": "smoke-test (safe to delete)",
                "input_source": "url",
                "input_url": "https://www.linkedin.com/in/smoke-test/",
                "profiles_per_launch": 1,
            },
        )
        if response.status_code == 201:
            created = response.json()
            record(PASS, "POST /api/agents", f"id {created['id']}")
        else:
            record(FAIL, "POST /api/agents", f"{response.status_code}: {response.text[:120]}")
    except httpx.HTTPError as exc:
        record(FAIL, "POST /api/agents", str(exc))

    if created:
        agent_id = created["id"]
        check(client, "GET", f"/api/agents/{agent_id}", f"GET /api/agents/{agent_id}")

        response = client.call(
            "PATCH", f"/api/agents/{agent_id}", json={"profiles_per_launch": 5}
        )
        record(
            PASS if response.status_code == 200 else FAIL,
            "PATCH /api/agents/{id}",
            f"{response.status_code}",
        )

        response = client.call("POST", "/api/agents/999999/launch")
        record(
            PASS if response.status_code == 404 else FAIL,
            "unknown agent returns 404",
            f"{response.status_code}",
        )

        check(client, "GET", f"/api/agents/{agent_id}/launches", "GET /agents/{id}/launches")
        check(client, "GET", f"/api/agents/{agent_id}/results", "GET /agents/{id}/results")
        check(client, "GET", f"/api/agents/{agent_id}/leads", "GET /agents/{id}/leads")

        csv_body = check(
            client, "GET", f"/api/agents/{agent_id}/export.csv", "GET /agents/{id}/export.csv"
        )
        if isinstance(csv_body, str) and csv_body.startswith("Company Industry"):
            record(PASS, "CSV header correct")
        elif csv_body is not None:
            record(FAIL, "CSV header correct", "unexpected first column")

        check(
            client, "GET", f"/api/agents/{agent_id}/export.json", "GET /agents/{id}/export.json"
        )

        section("Event stream")
        try:
            with client.http.stream(
                "GET",
                f"{client.base}/api/agents/{agent_id}/stream",
                headers=client.headers,
                timeout=10.0,
            ) as stream:
                if stream.status_code != 200:
                    record(FAIL, "SSE connects", f"{stream.status_code}")
                elif "text/event-stream" not in stream.headers.get("content-type", ""):
                    record(FAIL, "SSE content type", stream.headers.get("content-type", "?"))
                else:
                    record(PASS, "SSE connects", "text/event-stream")
                    started = time.monotonic()
                    for _ in stream.iter_raw():
                        break
                    record(
                        PASS,
                        "SSE delivers without buffering",
                        f"first bytes in {time.monotonic() - started:.1f}s",
                    )
        except httpx.HTTPError as exc:
            record(WARN, "SSE connects", f"{exc} (a proxy may cap idle streams)")

        response = client.call("DELETE", f"/api/agents/{agent_id}")
        record(
            PASS if response.status_code == 204 else FAIL,
            "DELETE /api/agents/{id}",
            f"{response.status_code}",
        )

    section("Access control")
    unauth = httpx.Client(timeout=15.0)
    try:
        response = unauth.get(f"{client.base}/api/agents")
        if through_proxy:
            record(
                SKIP,
                "unauthenticated request refused",
                "the proxy holds the token; protect this URL with Vercel Deployment Protection",
            )
        elif response.status_code == 401:
            record(PASS, "unauthenticated request refused", "401")
        elif not token:
            record(WARN, "unauthenticated request refused", "no token configured on this server")
        else:
            record(FAIL, "unauthenticated request refused", f"got {response.status_code}")
    except httpx.HTTPError as exc:
        record(WARN, "unauthenticated request refused", str(exc))
    finally:
        unauth.close()

    section("Frontend")
    try:
        response = client.http.get(client.base + "/", timeout=15.0)
        body = response.text
        if response.status_code == 200 and "Profile Scraper" in body:
            record(PASS, "UI shell served", f"{len(body):,} bytes")
        else:
            record(FAIL, "UI shell served", f"{response.status_code}")

        for asset in ("/assets/styles.css", "/assets/js/app.js"):
            probe = client.http.get(client.base + asset, timeout=15.0)
            if probe.status_code == 200:
                record(PASS, f"asset {asset}")
            else:
                alt = client.http.get(client.base + asset.replace("/assets", ""), timeout=15.0)
                record(
                    PASS if alt.status_code == 200 else FAIL,
                    f"asset {asset}",
                    "served at root" if alt.status_code == 200 else f"{probe.status_code}",
                )
    except httpx.HTTPError as exc:
        record(FAIL, "UI shell served", str(exc))

    client.close()

    section("Summary")
    counts = {status: sum(1 for s, _, _ in results if s == status) for status in (PASS, FAIL, WARN, SKIP)}
    print(f"  {counts[PASS]} passed, {counts[FAIL]} failed, {counts[WARN]} warnings, {counts[SKIP]} skipped")

    if counts[FAIL]:
        print("\n  Failures:")
        for status, name, detail in results:
            if status == FAIL:
                print(f"    - {name}: {detail}")
        return 1

    print("\n  Ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
