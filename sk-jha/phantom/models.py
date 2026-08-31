"""
Persistence model.

Four entities, and the boundaries between them are the whole design:

  Agent    configuration a user edits in the setup wizard. Mutable.
  Launch   one execution of an agent. Immutable once terminal. Owns its logs.
  Result   one scraped profile as produced by one launch. Append-only history.
  Lead     the deduplicated, latest-known state of a profile across launches.

Results are never updated — a re-scrape appends a new row, so a run can always
be reproduced from what it actually saw. Leads are upserted, which is what the
UI shows when the question is "who do we know about" rather than "what did
this run do".
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class LaunchStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    FINISHED = "finished"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InputSource(str, enum.Enum):
    URL = "url"
    LIST = "list"
    AGENT = "agent"
    HUBSPOT = "hubspot"


class LaunchFrequency(str, enum.Enum):
    ONCE = "once"
    REPEATEDLY = "repeatedly"
    AFTER_AGENT = "after_agent"


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="Untitled LinkedIn Profile Scraper")
    kind: Mapped[str] = mapped_column(String(60), default="linkedin-profile-scraper")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    input_source: Mapped[InputSource] = mapped_column(
        Enum(InputSource, native_enum=False), default=InputSource.URL
    )
    input_url: Mapped[str | None] = mapped_column(Text, default=None)
    input_urls: Mapped[list | None] = mapped_column(JSON, default=list)
    source_agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), default=None
    )


    email_provider: Mapped[str | None] = mapped_column(String(40), default=None)
    email_api_key_enc: Mapped[str | None] = mapped_column(Text, default=None)

    profiles_per_launch: Mapped[int] = mapped_column(Integer, default=200)
    enrich_company_data: Mapped[bool] = mapped_column(Boolean, default=False)
    fetch_all_sections: Mapped[bool] = mapped_column(Boolean, default=False)
    save_profile_picture: Mapped[bool] = mapped_column(Boolean, default=False)
    skip_already_processed: Mapped[bool] = mapped_column(Boolean, default=True)

    frequency: Mapped[LaunchFrequency] = mapped_column(
        Enum(LaunchFrequency, native_enum=False), default=LaunchFrequency.ONCE
    )
    schedule_cron: Mapped[str | None] = mapped_column(String(120), default=None)
    schedule_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    chain_to_agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), default=None
    )

    max_execution_minutes: Mapped[int] = mapped_column(Integer, default=0)
    max_launch_retries: Mapped[int] = mapped_column(Integer, default=0)
    webhook_url: Mapped[str | None] = mapped_column(Text, default=None)
    notify_on_failure: Mapped[bool] = mapped_column(Boolean, default=True)
    min_delay_seconds: Mapped[float | None] = mapped_column(Float, default=None)
    max_delay_seconds: Mapped[float | None] = mapped_column(Float, default=None)

    launches: Mapped[list["Launch"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan", order_by="Launch.id.desc()"
    )

    @property
    def is_configured(self) -> bool:
        if self.input_source is InputSource.URL:
            return bool(self.input_url)
        if self.input_source is InputSource.LIST:
            return bool(self.input_urls)
        if self.input_source is InputSource.AGENT:
            return self.source_agent_id is not None
        return False


class Launch(Base):
    __tablename__ = "launches"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    status: Mapped[LaunchStatus] = mapped_column(
        Enum(LaunchStatus, native_enum=False), default=LaunchStatus.QUEUED, index=True
    )
    trigger: Mapped[str] = mapped_column(String(30), default="manual")

    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    targets_total: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    succeeded: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)

    error: Mapped[str | None] = mapped_column(Text, default=None)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)

    agent: Mapped[Agent] = relationship(back_populates="launches")
    logs: Mapped[list["LogLine"]] = relationship(
        back_populates="launch", cascade="all, delete-orphan", order_by="LogLine.id"
    )
    results: Mapped[list["Result"]] = relationship(
        back_populates="launch", cascade="all, delete-orphan"
    )

    @property
    def is_terminal(self) -> bool:
        return self.status in {LaunchStatus.FINISHED, LaunchStatus.FAILED, LaunchStatus.CANCELLED}

    @property
    def progress(self) -> float:
        if not self.targets_total:
            return 0.0
        return min(1.0, self.processed / self.targets_total)


class LogLine(Base):
    __tablename__ = "log_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    launch_id: Mapped[int] = mapped_column(
        ForeignKey("launches.id", ondelete="CASCADE"), index=True
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    level: Mapped[str] = mapped_column(String(10), default="info")
    message: Mapped[str] = mapped_column(Text)

    launch: Mapped[Launch] = relationship(back_populates="logs")


class Result(Base):
    __tablename__ = "results"

    id: Mapped[int] = mapped_column(primary_key=True)
    launch_id: Mapped[int] = mapped_column(
        ForeignKey("launches.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    profile_url: Mapped[str] = mapped_column(Text)
    profile_slug: Mapped[str | None] = mapped_column(String(200), index=True)
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    transport: Mapped[str | None] = mapped_column(String(20), default=None)
    duration_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text, default=None)

    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)

    launch: Mapped[Launch] = relationship(back_populates="results")

    __table_args__ = (Index("ix_results_agent_slug", "agent_id", "profile_slug"),)


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    profile_slug: Mapped[str] = mapped_column(String(200))
    profile_url: Mapped[str] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    times_seen: Mapped[int] = mapped_column(Integer, default=1)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)

    __table_args__ = (
        UniqueConstraint("agent_id", "profile_slug", name="uq_lead_agent_slug"),
    )


class BrowserIdentity(Base):
    """
    A cookie set pasted from a browser that is already signed in.

    One row, replaced on each upload — there is one LinkedIn account behind this
    deployment, and keeping several would invite presenting the same account from
    inconsistent identities, which is the pattern that gets sessions invalidated.

    The user agent is stored with the cookies deliberately. Cookies replayed
    under a different user agent than the browser that received them is exactly
    the mismatch that made the first version of this feature sign people out.
    """

    __tablename__ = "browser_identity"

    id: Mapped[int] = mapped_column(primary_key=True)
    cookies_enc: Mapped[str] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text, default=None)
    locale: Mapped[str | None] = mapped_column(String(20), default=None)
    timezone: Mapped[str | None] = mapped_column(String(60), default=None)
    viewport_width: Mapped[int | None] = mapped_column(Integer, default=None)
    viewport_height: Mapped[int | None] = mapped_column(Integer, default=None)

    label: Mapped[str | None] = mapped_column(String(200), default=None)
    grade: Mapped[str] = mapped_column(String(20), default="unknown")
    cookie_names: Mapped[list | None] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class DailyQuota(Base):
    """One row per UTC day. The account-safety limit that actually matters."""

    __tablename__ = "daily_quota"

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[str] = mapped_column(String(10), unique=True)
    profiles_scraped: Mapped[int] = mapped_column(Integer, default=0)
