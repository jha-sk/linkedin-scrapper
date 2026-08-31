"""Request and response shapes. The API contract lives here, not in the routes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

from .models import InputSource, LaunchFrequency, LaunchStatus
from .scraper.engine import normalise_url


def _as_utc(value: datetime) -> str:
    """
    Always serialise an instant as UTC with an explicit offset.

    SQLite has no timezone type, so a round-tripped column comes back naive even
    though it was written as UTC. Emitting that naive value would have the
    browser read it as local time and render every timestamp off by the local
    offset, so the tz is reattached on the way out rather than trusted on the
    way in.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


UtcDatetime = Annotated[datetime, PlainSerializer(_as_utc, return_type=str)]


class AgentBase(BaseModel):
    name: str = Field(default="Untitled LinkedIn Profile Scraper", max_length=200)

    input_source: InputSource = InputSource.URL
    input_url: str | None = None
    input_urls: list[str] = Field(default_factory=list)
    source_agent_id: int | None = None

    email_provider: Literal["none", "hunter", "dropcontact"] | None = None

    profiles_per_launch: int = Field(default=200, ge=1, le=1500)
    enrich_company_data: bool = False
    fetch_all_sections: bool = False
    save_profile_picture: bool = False
    skip_already_processed: bool = True

    frequency: LaunchFrequency = LaunchFrequency.ONCE
    schedule_cron: str | None = None
    schedule_enabled: bool = False
    chain_to_agent_id: int | None = None

    max_execution_minutes: int = Field(default=0, ge=0, le=300)
    max_launch_retries: int = Field(default=0, ge=0, le=10)
    webhook_url: str | None = None
    notify_on_failure: bool = True
    min_delay_seconds: float | None = Field(default=None, ge=0, le=600)
    max_delay_seconds: float | None = Field(default=None, ge=0, le=600)

    @field_validator("input_url")
    @classmethod
    def _check_url(cls, value: str | None) -> str | None:
        if not value:
            return None
        return normalise_url(value)

    @field_validator("input_urls")
    @classmethod
    def _check_urls(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in values:
            item = (item or "").strip()
            if not item:
                continue
            cleaned.append(normalise_url(item))
        return cleaned


class AgentCreate(AgentBase):
    pass


class AgentUpdate(AgentBase):
    """Same fields, all optional — a wizard step saves one section at a time."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    input_source: InputSource | None = None
    profiles_per_launch: int | None = Field(default=None, ge=1, le=1500)
    enrich_company_data: bool | None = None
    fetch_all_sections: bool | None = None
    save_profile_picture: bool | None = None
    skip_already_processed: bool | None = None
    frequency: LaunchFrequency | None = None
    schedule_enabled: bool | None = None
    max_execution_minutes: int | None = Field(default=None, ge=0, le=300)
    max_launch_retries: int | None = Field(default=None, ge=0, le=10)
    notify_on_failure: bool | None = None
    input_urls: list[str] | None = None

    session_cookie: str | None = None


class CookieUpload(BaseModel):
    """
    A cookie set copied from a browser that is already signed in.

    `user_agent` is not optional in spirit, only in the schema: cookies replayed
    under a different user agent than the browser that received them is the
    mismatch that gets sessions invalidated. The UI asks for it, and the response
    grades a paste that omits it.
    """

    raw: str = Field(min_length=10, max_length=200_000)
    user_agent: str | None = Field(default=None, max_length=500)
    locale: str | None = Field(default=None, max_length=20)
    timezone: str | None = Field(default=None, max_length=60)
    viewport_width: int | None = Field(default=None, ge=320, le=7680)
    viewport_height: int | None = Field(default=None, ge=320, le=4320)
    label: str | None = Field(default=None, max_length=200)


class EmailKeyIn(BaseModel):
    provider: Literal["none", "hunter", "dropcontact"]
    api_key: str | None = Field(default=None, max_length=512)


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    kind: str
    created_at: UtcDatetime
    updated_at: UtcDatetime

    input_source: InputSource
    input_url: str | None
    input_urls: list[str] | None
    source_agent_id: int | None

    session_connected: bool = False

    email_provider: str | None
    email_key_set: bool = False

    profiles_per_launch: int
    enrich_company_data: bool
    fetch_all_sections: bool = False
    save_profile_picture: bool
    skip_already_processed: bool

    frequency: LaunchFrequency
    schedule_cron: str | None
    schedule_enabled: bool
    next_run_at: UtcDatetime | None
    chain_to_agent_id: int | None

    max_execution_minutes: int
    max_launch_retries: int
    webhook_url: str | None
    notify_on_failure: bool
    min_delay_seconds: float | None
    max_delay_seconds: float | None

    is_configured: bool = False
    last_launch: "LaunchOut | None" = None
    result_count: int = 0
    lead_count: int = 0


class LaunchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent_id: int
    status: LaunchStatus
    trigger: str
    queued_at: UtcDatetime
    started_at: UtcDatetime | None
    finished_at: UtcDatetime | None
    targets_total: int
    processed: int
    succeeded: int
    failed: int
    skipped: int
    error: str | None
    attempt: int
    progress: float = 0.0


class LogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    at: UtcDatetime
    level: str
    message: str


class ResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    launch_id: int
    profile_url: str
    profile_slug: str | None
    scraped_at: UtcDatetime
    transport: str | None
    duration_ms: int | None
    ok: bool
    error: str | None
    payload: dict[str, Any]
    provenance: dict[str, str]


class Page(BaseModel):
    total: int
    page: int
    per_page: int
    items: list[Any]


class ColumnOut(BaseModel):
    key: str
    label: str
    kind: str


AgentOut.model_rebuild()
