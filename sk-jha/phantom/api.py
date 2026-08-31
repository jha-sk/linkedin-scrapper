"""HTTP API. Thin: validate, delegate, serialise. No scraping logic lives here."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .columns import COLUMNS, COLUMN_KEYS
from .config import settings
from .crypto import encrypt
from .db import get_session
from .models import (
    Agent,
    BrowserIdentity,
    DailyQuota,
    InputSource,
    Launch,
    LaunchStatus,
    Lead,
    LogLine,
    Result,
    utcnow,
)
from . import cookies as cookie_tools
from . import session as browser_session
from .runner import _next_occurrence, runner
from .schemas import (
    AgentCreate,
    AgentOut,
    AgentUpdate,
    ColumnOut,
    CookieUpload,
    EmailKeyIn,
    LaunchOut,
    LogOut,
    Page,
    ResultOut,
)

router = APIRouter(prefix="/api")




def _agent_out(session: Session, agent: Agent) -> AgentOut:
    last = session.scalars(
        select(Launch).where(Launch.agent_id == agent.id).order_by(Launch.id.desc()).limit(1)
    ).first()
    result_count = session.scalar(
        select(func.count(Result.id)).where(Result.agent_id == agent.id, Result.ok.is_(True))
    )
    lead_count = session.scalar(select(func.count(Lead.id)).where(Lead.agent_id == agent.id))

    data = AgentOut.model_validate(agent)
    data.session_connected = browser_session.can_authenticate()
    data.email_key_set = bool(agent.email_api_key_enc)
    data.is_configured = agent.is_configured
    data.result_count = result_count or 0
    data.lead_count = lead_count or 0
    data.last_launch = _launch_out(last) if last else None
    return data


def _launch_out(launch: Launch) -> LaunchOut:
    out = LaunchOut.model_validate(launch)
    out.progress = launch.progress
    return out


def _get_agent(session: Session, agent_id: int) -> Agent:
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agent {agent_id} not found")
    return agent




@router.get("/columns", response_model=list[ColumnOut])
def list_columns() -> list[ColumnOut]:
    return [ColumnOut(key=c.key, label=c.label, kind=c.kind) for c in COLUMNS]


@router.get("/session")
def session_status() -> dict[str, object]:
    """
    State of the machine-wide signed-in browser profile.

    There is deliberately no endpoint to *set* a session. A session is created by
    signing in by hand — `python -m phantom.session login` — because that is the
    only way LinkedIn issues cookies to the browser that will use them. Accepting
    a pasted cookie over HTTP would rebuild the exact failure this replaced.
    """
    state = browser_session.status()
    return {
        "exists": state.exists,
        "logged_in": state.logged_in,
        "summary": state.summary,
        "cookie_count": len(state.cookie_names),
        "cookie_names": state.cookie_names,
        "source": state.source,
        "grade": state.grade,
        "profile_dir": str(browser_session.PROFILE_DIR),
    }


@router.put("/session/cookies")
def upload_cookies(
    body: CookieUpload, session: Session = Depends(get_session)
) -> dict[str, object]:
    """
    Store a cookie set pasted from a signed-in browser.

    This exists because a headless server cannot complete an interactive
    sign-in. It is the second-best option: moving the browser profile itself
    (`session export` / `session import`) keeps the cookies with the localStorage
    and history that make them coherent, and a transplant does not.

    The response grades the paste rather than simply accepting it, because a set
    containing only `li_at` behaves very differently from a complete one and the
    difference is worth seeing before a run spends the session.
    """
    parsed = cookie_tools.parse(body.raw)
    if not parsed.has_session:
        raise HTTPException(
            status_code=422,
            detail=(
                "No li_at cookie found. Copy every linkedin.com cookie from a "
                "browser where you are signed in — not just one value."
            ),
        )

    payload = json.dumps(parsed.to_playwright())
    session.query(BrowserIdentity).delete()
    session.add(
        BrowserIdentity(
            cookies_enc=encrypt(payload),
            user_agent=body.user_agent,
            locale=body.locale,
            timezone=body.timezone,
            viewport_width=body.viewport_width,
            viewport_height=body.viewport_height,
            label=body.label,
            grade=parsed.grade,
            cookie_names=sorted(parsed.names),
        )
    )
    session.flush()

    summary = parsed.summary()
    if not body.user_agent:
        summary["warnings"] = list(summary["warnings"]) + [
            "no user agent supplied — cookies replayed under a different browser "
            "identity than the one that received them are more likely to be rejected"
        ]
    return summary


@router.post("/session/cookies/preview")
def preview_cookies(body: CookieUpload) -> dict[str, object]:
    """Grade a paste without storing it, so the UI can warn before committing."""
    return cookie_tools.parse(body.raw).summary()


@router.delete("/session/cookies", status_code=204)
def clear_cookies(session: Session = Depends(get_session)) -> Response:
    session.query(BrowserIdentity).delete()
    return Response(status_code=204)


@router.get("/quota")
def quota(session: Session = Depends(get_session)) -> dict[str, int]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = session.scalars(select(DailyQuota).where(DailyQuota.day == today)).first()
    used = row.profiles_scraped if row else 0
    return {
        "used": used,
        "cap": settings.daily_profile_cap,
        "remaining": max(0, settings.daily_profile_cap - used),
    }




@router.get("/agents", response_model=list[AgentOut])
def list_agents(session: Session = Depends(get_session)) -> list[AgentOut]:
    agents = session.scalars(select(Agent).order_by(Agent.id.desc())).all()
    return [_agent_out(session, a) for a in agents]


@router.post("/agents", response_model=AgentOut, status_code=201)
def create_agent(body: AgentCreate, session: Session = Depends(get_session)) -> AgentOut:
    agent = Agent(**body.model_dump(exclude_none=True))
    session.add(agent)
    session.flush()
    return _agent_out(session, agent)


@router.get("/agents/{agent_id}", response_model=AgentOut)
def get_agent(agent_id: int, session: Session = Depends(get_session)) -> AgentOut:
    return _agent_out(session, _get_agent(session, agent_id))


@router.patch("/agents/{agent_id}", response_model=AgentOut)
def update_agent(
    agent_id: int, body: AgentUpdate, session: Session = Depends(get_session)
) -> AgentOut:
    agent = _get_agent(session, agent_id)
    payload = body.model_dump(exclude_unset=True, exclude_none=True)
    payload.pop("session_cookie", None)

    for key, value in payload.items():
        setattr(agent, key, value)

    if agent.schedule_enabled and agent.schedule_cron:
        agent.next_run_at = _next_occurrence(agent.schedule_cron, utcnow())
    elif not agent.schedule_enabled:
        agent.next_run_at = None

    session.flush()
    runner.nudge()
    return _agent_out(session, agent)


@router.delete("/agents/{agent_id}", status_code=204)
def delete_agent(agent_id: int, session: Session = Depends(get_session)) -> Response:
    session.delete(_get_agent(session, agent_id))
    return Response(status_code=204)


@router.put("/agents/{agent_id}/email-provider", response_model=AgentOut)
def set_email_provider(
    agent_id: int, body: EmailKeyIn, session: Session = Depends(get_session)
) -> AgentOut:
    agent = _get_agent(session, agent_id)
    if body.provider == "none":
        agent.email_provider = None
        agent.email_api_key_enc = None
    else:
        if not body.api_key:
            raise HTTPException(status_code=422, detail="an API key is required for this provider")
        agent.email_provider = body.provider
        agent.email_api_key_enc = encrypt(body.api_key.strip())
    session.flush()
    return _agent_out(session, agent)




@router.post("/agents/{agent_id}/launch", response_model=LaunchOut, status_code=202)
def launch_agent(agent_id: int, session: Session = Depends(get_session)) -> LaunchOut:
    agent = _get_agent(session, agent_id)
    if not agent.is_configured:
        raise HTTPException(status_code=409, detail="agent has no input configured")

    active = session.scalars(
        select(Launch).where(
            Launch.agent_id == agent_id,
            Launch.status.in_([LaunchStatus.QUEUED, LaunchStatus.RUNNING]),
        )
    ).first()
    if active is not None:
        raise HTTPException(status_code=409, detail=f"launch {active.id} is already in flight")

    launch = Launch(agent_id=agent_id, trigger="manual")
    session.add(launch)
    session.flush()
    runner.nudge()
    return _launch_out(launch)


@router.get("/agents/{agent_id}/launches", response_model=list[LaunchOut])
def list_launches(
    agent_id: int, limit: int = Query(default=25, ge=1, le=200),
    session: Session = Depends(get_session),
) -> list[LaunchOut]:
    _get_agent(session, agent_id)
    launches = session.scalars(
        select(Launch).where(Launch.agent_id == agent_id).order_by(Launch.id.desc()).limit(limit)
    ).all()
    return [_launch_out(item) for item in launches]


@router.get("/launches/{launch_id}", response_model=LaunchOut)
def get_launch(launch_id: int, session: Session = Depends(get_session)) -> LaunchOut:
    launch = session.get(Launch, launch_id)
    if launch is None:
        raise HTTPException(status_code=404, detail=f"launch {launch_id} not found")
    return _launch_out(launch)


@router.post("/launches/{launch_id}/cancel", response_model=LaunchOut)
def cancel_launch(launch_id: int, session: Session = Depends(get_session)) -> LaunchOut:
    launch = session.get(Launch, launch_id)
    if launch is None:
        raise HTTPException(status_code=404, detail=f"launch {launch_id} not found")
    if launch.is_terminal:
        raise HTTPException(status_code=409, detail=f"launch is already {launch.status.value}")
    launch.cancel_requested = True
    if launch.status is LaunchStatus.QUEUED:
        launch.status = LaunchStatus.CANCELLED
        launch.finished_at = utcnow()
    session.flush()
    return _launch_out(launch)


@router.get("/launches/{launch_id}/logs", response_model=list[LogOut])
def launch_logs(
    launch_id: int, after: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[LogOut]:
    rows = session.scalars(
        select(LogLine)
        .where(LogLine.launch_id == launch_id, LogLine.id > after)
        .order_by(LogLine.id)
        .limit(500)
    ).all()
    return [LogOut.model_validate(r) for r in rows]


@router.get("/agents/{agent_id}/stream")
async def stream_agent(agent_id: int) -> StreamingResponse:
    """
    Server-sent events: launch status plus new console lines.

    Polled server-side against the database rather than pushed from the runner.
    The runner writes from a worker thread and the API serves from an event
    loop; going through the database keeps that boundary a transaction instead
    of a shared queue, and it means a reconnecting client resumes from a log id
    rather than losing whatever was in flight.
    """

    async def events():
        last_log_id = 0
        last_signature: str | None = None
        last_sent = 0.0

        heartbeat_seconds = 15.0

        yield ": connected\n\n"
        last_sent = time.monotonic()

        while True:
            from .db import session_scope

            sent_this_tick = False
            with session_scope() as session:
                launch = session.scalars(
                    select(Launch)
                    .where(Launch.agent_id == agent_id)
                    .order_by(Launch.id.desc())
                    .limit(1)
                ).first()
                if launch is not None:
                    payload = _launch_out(launch).model_dump(mode="json")
                    signature = json.dumps(payload, sort_keys=True)
                    if signature != last_signature:
                        last_signature = signature
                        sent_this_tick = True
                        yield f"event: launch\ndata: {signature}\n\n"

                    lines = session.scalars(
                        select(LogLine)
                        .where(LogLine.launch_id == launch.id, LogLine.id > last_log_id)
                        .order_by(LogLine.id)
                        .limit(200)
                    ).all()
                    for line in lines:
                        last_log_id = line.id
                        sent_this_tick = True
                        body = json.dumps(LogOut.model_validate(line).model_dump(mode="json"))
                        yield f"event: log\ndata: {body}\n\n"

            now = time.monotonic()
            if sent_this_tick:
                last_sent = now
            elif now - last_sent >= heartbeat_seconds:
                last_sent = now
                yield ": heartbeat\n\n"

            await asyncio.sleep(1.0)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )




def _paginate(items: list[Any], page: int, per_page: int) -> Page:
    start = (page - 1) * per_page
    return Page(total=len(items), page=page, per_page=per_page, items=items[start : start + per_page])


@router.get("/agents/{agent_id}/results", response_model=Page)
def list_results(
    agent_id: int,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=10, ge=1, le=200),
    launch_id: int | None = None,
    only_ok: bool = True,
    session: Session = Depends(get_session),
) -> Page:
    _get_agent(session, agent_id)
    stmt = select(Result).where(Result.agent_id == agent_id)
    if launch_id:
        stmt = stmt.where(Result.launch_id == launch_id)
    if only_ok:
        stmt = stmt.where(Result.ok.is_(True))
    rows = session.scalars(stmt.order_by(Result.id.desc())).all()
    return _paginate([ResultOut.model_validate(r).model_dump(mode="json") for r in rows], page, per_page)


@router.get("/agents/{agent_id}/leads", response_model=Page)
def list_leads(
    agent_id: int,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=10, ge=1, le=200),
    session: Session = Depends(get_session),
) -> Page:
    _get_agent(session, agent_id)
    rows = session.scalars(
        select(Lead).where(Lead.agent_id == agent_id).order_by(Lead.last_seen_at.desc())
    ).all()
    items = [
        {
            "id": lead.id,
            "profile_slug": lead.profile_slug,
            "profile_url": lead.profile_url,
            "first_seen_at": lead.first_seen_at.isoformat(),
            "last_seen_at": lead.last_seen_at.isoformat(),
            "times_seen": lead.times_seen,
            "payload": lead.payload,
        }
        for lead in rows
    ]
    return _paginate(items, page, per_page)


def _csv_stream(rows: list[dict[str, Any]]) -> io.StringIO:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(COLUMN_KEYS), extrasaction="ignore")
    writer.writerow({c.key: c.label for c in COLUMNS})
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in COLUMN_KEYS})
    buffer.seek(0)
    return buffer


@router.get("/agents/{agent_id}/export.csv")
def export_csv(
    agent_id: int,
    scope: str = Query(default="results", pattern="^(results|leads)$"),
    session: Session = Depends(get_session),
) -> StreamingResponse:
    agent = _get_agent(session, agent_id)
    if scope == "leads":
        payloads = [
            lead.payload
            for lead in session.scalars(select(Lead).where(Lead.agent_id == agent_id)).all()
        ]
    else:
        payloads = [
            r.payload
            for r in session.scalars(
                select(Result)
                .where(Result.agent_id == agent_id, Result.ok.is_(True))
                .order_by(Result.id)
            ).all()
        ]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    filename = f"{agent.name.replace(' ', '-').lower()}-{scope}-{stamp}.csv"
    return StreamingResponse(
        _csv_stream(payloads),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/agents/{agent_id}/export.json")
def export_json(
    agent_id: int,
    scope: str = Query(default="results", pattern="^(results|leads)$"),
    session: Session = Depends(get_session),
) -> Response:
    _get_agent(session, agent_id)
    if scope == "leads":
        payloads = [
            lead.payload
            for lead in session.scalars(select(Lead).where(Lead.agent_id == agent_id)).all()
        ]
    else:
        payloads = [
            r.payload
            for r in session.scalars(
                select(Result).where(Result.agent_id == agent_id, Result.ok.is_(True))
            ).all()
        ]
    return Response(
        content=json.dumps(payloads, indent=2, default=str),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="results.json"'},
    )
