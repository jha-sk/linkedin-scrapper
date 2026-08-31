"""
Launch runner.

A single background worker thread owns execution. One thread, deliberately:
the binding constraint on this workload is not CPU, it is how many actions a
LinkedIn account can take before it is restricted. Concurrency here would buy
throughput the account cannot spend, and would make the pacing between requests
— the thing that keeps a session alive — unenforceable.

Each launch:

  1. resolves its target list from the agent's input source
  2. drops targets already processed, if the agent asks for that
  3. clamps the list to the per-launch limit and the remaining daily quota
  4. scrapes each target, pacing with a randomised delay between them
  5. appends a Result row, upserts a Lead, and streams a log line
  6. honours cancellation and the maximum execution time between targets

A failure on one target is recorded and the run continues. A failure that makes
the rest of the run pointless — an invalid session cookie — stops it.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx
from sqlalchemy import select

from .config import settings
from .crypto import decrypt
from .db import session_scope
from .models import (
    Agent,
    DailyQuota,
    InputSource,
    Launch,
    LaunchStatus,
    Lead,
    LogLine,
    Result,
    utcnow,
)
from . import session as browser_session
from .scraper import scrape_profile
from .scraper.enrich import build_provider, save_picture
from .scraper.enrich import enrich_company
from .scraper.engine import normalise_url

log = logging.getLogger("phantom.runner")

_FATAL_MARKERS = ("authwalled",)

DEFAULT_DETAIL_SECTIONS: tuple[str, ...] = (
    "skills",
    "experience",
    "education",
    "licenses & certifications",
    "projects",
    "languages",
)


class RunnerStopped(Exception):
    """Raised internally to unwind a launch that was cancelled or timed out."""


class Runner:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._current_launch_id: int | None = None
        self._lock = threading.Lock()


    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="phantom-runner", daemon=True)
        self._thread.start()
        log.info("runner started")

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        log.info("runner stopped")

    def nudge(self) -> None:
        """Wake the worker immediately instead of waiting out the poll interval."""
        self._wake.set()

    @property
    def current_launch_id(self) -> int | None:
        with self._lock:
            return self._current_launch_id


    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                launch_id = self._claim_next_launch()
                if launch_id is None:
                    self._promote_due_schedules()
                    self._wake.wait(timeout=settings.worker_poll_seconds)
                    self._wake.clear()
                    continue
                self._execute(launch_id)
            except Exception:
                log.exception("runner loop error")
                time.sleep(1.0)

    def _claim_next_launch(self) -> int | None:
        """Atomically move the oldest queued launch to RUNNING and return its id."""
        stmt = (
            select(Launch)
            .where(Launch.status == LaunchStatus.QUEUED)
            .order_by(Launch.id)
            .limit(1)
        )
        if _supports_row_locks():
            stmt = stmt.with_for_update(skip_locked=True)
        with session_scope() as session:
            launch = session.scalars(stmt).first()
            if launch is None:
                return None
            launch.status = LaunchStatus.RUNNING
            launch.started_at = utcnow()
            return launch.id

    def _promote_due_schedules(self) -> None:
        """Queue a launch for every scheduled agent whose next run has come due."""
        now = utcnow()
        with session_scope() as session:
            agents = session.scalars(
                select(Agent).where(
                    Agent.schedule_enabled.is_(True),
                    Agent.next_run_at.is_not(None),
                )
            ).all()
            for agent in agents:
                due = agent.next_run_at
                if due and due.tzinfo is None:
                    due = due.replace(tzinfo=timezone.utc)
                if not due or due > now:
                    continue
                already = session.scalars(
                    select(Launch).where(
                        Launch.agent_id == agent.id,
                        Launch.status.in_([LaunchStatus.QUEUED, LaunchStatus.RUNNING]),
                    )
                ).first()
                if already is None:
                    session.add(Launch(agent_id=agent.id, trigger="schedule"))
                agent.next_run_at = _next_occurrence(agent.schedule_cron, now)


    def _execute(self, launch_id: int) -> None:
        with self._lock:
            self._current_launch_id = launch_id

        deadline: float | None = None
        try:
            with session_scope() as session:
                launch = session.get(Launch, launch_id)
                agent = session.get(Agent, launch.agent_id)
                config = _snapshot(agent)
                targets = self._resolve_targets(session, agent)
                launch.targets_total = len(targets)
                self._log(session, launch_id, "info", f"Launch #{launch_id} starting")
                if not targets:
                    self._log(
                        session, launch_id, "warn",
                        "No targets to process — every input URL has already been "
                        "scraped by this agent. Turn off 'skip already processed' "
                        "in Behavior to re-scrape them.",
                    )

            limit_minutes = config["max_execution_minutes"] or settings.max_execution_minutes
            if limit_minutes:
                deadline = time.monotonic() + limit_minutes * 60

            processed = succeeded = failed = 0
            for index, url in enumerate(targets, start=1):
                self._assert_can_continue(launch_id, deadline)
                if index > 1:
                    self._pace(config)

                outcome = self._scrape_one(launch_id, url, config, index, len(targets))
                processed += 1
                if outcome.ok:
                    succeeded += 1
                else:
                    failed += 1

                with session_scope() as session:
                    launch = session.get(Launch, launch_id)
                    launch.processed = processed
                    launch.succeeded = succeeded
                    launch.failed = failed

                if not outcome.ok and _is_fatal(outcome.error):
                    raise RuntimeError(outcome.error or "fatal scrape error")

                self._bump_quota(1)

            if targets and succeeded == 0:
                raise RuntimeError(
                    f"all {failed} target(s) failed — check the session cookie and the input URLs"
                )

            self._finish(launch_id, LaunchStatus.FINISHED)

        except RunnerStopped as exc:
            self._finish(launch_id, LaunchStatus.CANCELLED, str(exc))
        except Exception as exc:
            log.exception("launch %s failed", launch_id)
            self._finish(launch_id, LaunchStatus.FAILED, str(exc))
        finally:
            with self._lock:
                self._current_launch_id = None
            self._after_launch(launch_id)

    def _scrape_one(self, launch_id: int, url: str, config: dict[str, Any], index: int, total: int):
        self._log(launch_id_msg := launch_id, "info", f"[{index}/{total}] Scraping {url}")
        outcome = scrape_profile(
            url,
            use_session=config["use_session"],
            headless=settings.headless,
            detail_sections=config["detail_sections"],
        )

        if outcome.ok and config["enrich_company_data"]:
            slug = outcome.row.get("linkedin_company_slug")
            if slug:
                extra = enrich_company(slug, headless=settings.headless)
                for key, value in extra.items():
                    if key in outcome.row and not outcome.row.get(key):
                        outcome.row[key] = value
                        outcome.provenance[key] = "company-page"

        if outcome.ok and config["save_profile_picture"]:
            saved = save_picture(
                outcome.row.get("linkedin_profile_image_url") or "",
                outcome.slug or f"profile-{index}",
                settings.screenshots_dir,
            )
            if saved:
                self._log(launch_id_msg, "info", f"Saved profile picture {saved}")

        if outcome.ok and config["email_provider"]:
            provider = build_provider(config["email_provider"], config["email_api_key"])
            email, status = provider.find(
                outcome.row.get("first_name") or "",
                outcome.row.get("last_name") or "",
                outcome.row.get("company_name") or "",
            )
            outcome.row["email"] = email
            outcome.row["email_status"] = status
            outcome.provenance["email"] = provider.name

        with session_scope() as session:
            session.add(
                Result(
                    launch_id=launch_id,
                    agent_id=config["agent_id"],
                    profile_url=outcome.url,
                    profile_slug=outcome.slug,
                    transport=outcome.transport,
                    duration_ms=outcome.duration_ms,
                    ok=outcome.ok,
                    error=outcome.error,
                    payload=outcome.row,
                    provenance=outcome.provenance,
                )
            )
            if outcome.ok and outcome.slug:
                _upsert_lead(session, config["agent_id"], outcome.slug, outcome.url, outcome.row)
            level = "info" if outcome.ok else "error"
            detail = (
                f"via {outcome.transport} in {outcome.duration_ms}ms"
                if outcome.ok
                else outcome.error
            )
            name = (
                (outcome.row.get("scraper_full_name") or outcome.slug or url)
                if outcome.ok
                else (outcome.slug or url)
            )
            self._log(session, launch_id, level, f"{'✓' if outcome.ok else '✗'} {name} — {detail}")

        return outcome


    def _resolve_targets(self, session, agent: Agent) -> list[str]:
        raw: list[str] = []
        if agent.input_source is InputSource.URL and agent.input_url:
            raw = [agent.input_url]
        elif agent.input_source is InputSource.LIST:
            raw = list(agent.input_urls or [])
        elif agent.input_source is InputSource.AGENT and agent.source_agent_id:
            rows = session.scalars(
                select(Result).where(
                    Result.agent_id == agent.source_agent_id, Result.ok.is_(True)
                )
            ).all()
            raw = [r.payload.get("linkedin_profile_url") or r.profile_url for r in rows]

        seen: set[str] = set()
        targets: list[str] = []
        for item in raw:
            try:
                url = normalise_url(item)
            except ValueError:
                log.warning("skipping unparseable target %r", item)
                continue
            if url not in seen:
                seen.add(url)
                targets.append(url)

        if agent.skip_already_processed:
            done = {
                slug
                for (slug,) in session.execute(
                    select(Result.profile_slug).where(
                        Result.agent_id == agent.id, Result.ok.is_(True)
                    )
                )
                if slug
            }
            targets = [t for t in targets if t.rstrip("/").rsplit("/", 1)[-1] not in done]

        limit = max(1, agent.profiles_per_launch or settings.default_profiles_per_launch)
        remaining = _quota_remaining()
        if remaining <= 0:
            raise RuntimeError(
                f"daily cap of {settings.daily_profile_cap} profiles already reached"
            )
        return targets[: min(limit, remaining)]

    def _pace(self, config: dict[str, Any]) -> None:
        low = config["min_delay"] or settings.min_delay_seconds
        high = config["max_delay"] or settings.max_delay_seconds
        if high < low:
            low, high = high, low
        time.sleep(random.uniform(low, high))

    def _assert_can_continue(self, launch_id: int, deadline: float | None) -> None:
        if self._stop.is_set():
            raise RunnerStopped("server shutting down")
        if deadline and time.monotonic() > deadline:
            raise RunnerStopped("maximum execution time reached")
        with session_scope() as session:
            launch = session.get(Launch, launch_id)
            if launch and launch.cancel_requested:
                raise RunnerStopped("cancelled by user")

    def _finish(self, launch_id: int, status: LaunchStatus, error: str | None = None) -> None:
        with session_scope() as session:
            launch = session.get(Launch, launch_id)
            if launch is None:
                return
            launch.status = status
            launch.finished_at = utcnow()
            launch.error = error
            summary = (
                f"Launch #{launch_id} {status.value}: "
                f"{launch.succeeded} succeeded, {launch.failed} failed, "
                f"{launch.processed}/{launch.targets_total} processed"
            )
            self._log(session, launch_id, "error" if error else "info", summary)
            if error:
                self._log(session, launch_id, "error", error)

    def _after_launch(self, launch_id: int) -> None:
        """Retry, chain, and webhook — everything that reacts to a finished launch."""
        with session_scope() as session:
            launch = session.get(Launch, launch_id)
            if launch is None:
                return
            agent = session.get(Agent, launch.agent_id)
            payload = {
                "launch_id": launch.id,
                "agent_id": agent.id if agent else None,
                "status": launch.status.value,
                "processed": launch.processed,
                "succeeded": launch.succeeded,
                "failed": launch.failed,
                "error": launch.error,
            }
            should_retry = (
                launch.status is LaunchStatus.FAILED
                and agent is not None
                and launch.attempt <= (agent.max_launch_retries or 0)
            )
            chain_id = agent.chain_to_agent_id if agent else None
            webhook = agent.webhook_url if agent else None

            if should_retry:
                session.add(
                    Launch(
                        agent_id=launch.agent_id,
                        trigger="retry",
                        attempt=launch.attempt + 1,
                    )
                )
                self._log(session, launch_id, "warn", "Retrying — a new launch has been queued")
            elif launch.status is LaunchStatus.FINISHED and chain_id:
                session.add(Launch(agent_id=chain_id, trigger="chain"))
                self._log(session, launch_id, "info", f"Chained launch queued for agent {chain_id}")

        if webhook:
            _post_webhook(webhook, payload)
        self.nudge()

    def _bump_quota(self, count: int) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with session_scope() as session:
            row = session.scalars(select(DailyQuota).where(DailyQuota.day == today)).first()
            if row is None:
                row = DailyQuota(day=today, profiles_scraped=0)
                session.add(row)
            row.profiles_scraped += count

    def _log(self, session_or_id, level_or_launch, message_or_level, message=None) -> None:
        """
        Append a console line.

        Two shapes, because half the call sites already hold an open session and
        half do not: `_log(session, launch_id, level, message)` reuses the caller's
        transaction, `_log(launch_id, level, message)` opens its own.
        """
        if message is None:
            launch_id, level, text = session_or_id, level_or_launch, message_or_level
            with session_scope() as session:
                session.add(LogLine(launch_id=launch_id, level=level, message=text))
            return
        session_or_id.add(
            LogLine(launch_id=level_or_launch, level=message_or_level, message=message)
        )


def _snapshot(agent: Agent) -> dict[str, Any]:
    """
    Freeze the agent config for the duration of a launch.

    Reading config off a live ORM object mid-run means an edit in the setup
    wizard changes behaviour halfway through, and the resulting data is not
    attributable to any one configuration. Snapshot once, then run.
    """
    use_session = browser_session.can_authenticate()

    email_key = None
    if agent.email_api_key_enc:
        try:
            email_key = decrypt(agent.email_api_key_enc)
        except ValueError:
            log.error("email API key for agent %s could not be decrypted", agent.id)

    return {
        "agent_id": agent.id,
        "use_session": use_session,
        "detail_sections": DEFAULT_DETAIL_SECTIONS if agent.fetch_all_sections else (),
        "email_provider": agent.email_provider,
        "email_api_key": email_key,
        "enrich_company_data": agent.enrich_company_data,
        "save_profile_picture": agent.save_profile_picture,
        "max_execution_minutes": agent.max_execution_minutes,
        "min_delay": agent.min_delay_seconds,
        "max_delay": agent.max_delay_seconds,
    }


def _upsert_lead(session, agent_id: int, slug: str, url: str, payload: dict[str, Any]) -> None:
    lead = session.scalars(
        select(Lead).where(Lead.agent_id == agent_id, Lead.profile_slug == slug)
    ).first()
    if lead is None:
        session.add(Lead(agent_id=agent_id, profile_slug=slug, profile_url=url, payload=payload))
        return
    lead.payload = payload
    lead.profile_url = url
    lead.times_seen += 1
    lead.last_seen_at = utcnow()


def _quota_remaining() -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with session_scope() as session:
        row = session.scalars(select(DailyQuota).where(DailyQuota.day == today)).first()
        used = row.profiles_scraped if row else 0
    return max(0, settings.daily_profile_cap - used)


def _is_fatal(error: str | None) -> bool:
    return bool(error) and any(marker in error for marker in _FATAL_MARKERS)


def _supports_row_locks() -> bool:
    return not settings.resolved_db_url.startswith("sqlite")


def _post_webhook(url: str, payload: dict[str, Any]) -> None:
    try:
        with httpx.Client(timeout=10.0) as client:
            client.post(url, json=payload)
    except Exception as exc:
        log.warning("webhook POST to %s failed: %s", url, exc)


def _next_occurrence(cron: str | None, now: datetime) -> datetime | None:
    """
    Next run time for the supported schedule vocabulary.

    Deliberately not a cron parser. The UI offers fixed intervals, so accepting
    `every:<n><unit>` covers the whole surface without a dependency, and an
    unrecognised value disables the schedule rather than firing at a time nobody
    asked for.
    """
    if not cron:
        return None
    if cron.startswith("every:"):
        raw = cron.removeprefix("every:").strip()
        unit = raw[-1]
        try:
            amount = int(raw[:-1])
        except ValueError:
            return None
        delta = {
            "m": timedelta(minutes=amount),
            "h": timedelta(hours=amount),
            "d": timedelta(days=amount),
        }.get(unit)
        return now + delta if delta else None
    return None


runner = Runner()
