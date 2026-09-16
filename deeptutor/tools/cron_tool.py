"""Implementation behind the built-in ``cron`` tool."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import inspect
from typing import Any

from deeptutor.services.cron import (
    CronJob,
    CronOwner,
    CronSchedule,
    get_cron_service,
)


@dataclass
class CronActionOutcome:
    ok: bool
    text: str
    meta: dict[str, Any] = field(default_factory=dict)


def _fmt_ms(ms: int | None) -> str:
    if not ms:
        return "—"
    return datetime.fromtimestamp(ms / 1000).astimezone().strftime("%Y-%m-%d %H:%M %Z")


def _describe_schedule(schedule: CronSchedule) -> str:
    if schedule.kind == "at":
        return f"once at {_fmt_ms(schedule.at_ms)}"
    if schedule.kind == "every":
        return f"every {schedule.every_seconds}s"
    tz_part = f" ({schedule.tz})" if schedule.tz else ""
    return f"cron `{schedule.expr}`{tz_part}"


def _render_job(job: CronJob) -> str:
    status = job.state.last_status or "pending"
    return (
        f"- `{job.id}` **{job.name}** — {_describe_schedule(job.schedule)}; "
        f"next run {_fmt_ms(job.state.next_run_at_ms)}; last: {status}"
    )


def _parse_at(value: str) -> int:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(
            f"could not parse time {value!r} — use ISO 8601, e.g. 2026-06-12T09:00"
        ) from None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()  # interpret naive times as server-local
    return int(parsed.timestamp() * 1000)


def _build_schedule(kwargs: dict[str, Any]) -> CronSchedule:
    at_raw = str(kwargs.get("at") or "").strip()
    every_raw = kwargs.get("every_seconds")
    expr = str(kwargs.get("cron_expr") or "").strip()
    chosen = [bool(at_raw), every_raw is not None, bool(expr)]
    if sum(chosen) != 1:
        raise ValueError(
            "provide exactly one of: at (one-shot), every_seconds (interval), "
            "or cron_expr (cron expression)"
        )
    if at_raw:
        return CronSchedule(kind="at", at_ms=_parse_at(at_raw))
    if every_raw is not None:
        return CronSchedule(kind="every", every_seconds=int(every_raw))
    return CronSchedule(kind="cron", expr=expr, tz=str(kwargs.get("tz") or "").strip() or None)


def run_cron_action(kwargs: dict[str, Any]) -> CronActionOutcome:
    def call(value):
        if inspect.isawaitable(value):
            if inspect.iscoroutine(value):
                value.close()
            raise RuntimeError("cron service requires async execution")
        return value

    return _run_cron_action_sync(kwargs, call=call)


async def run_cron_action_async(kwargs: dict[str, Any]) -> CronActionOutcome:
    async def call(value):
        if inspect.isawaitable(value):
            return await value
        return value

    return await _run_cron_action_async(kwargs, call=call)


def _owner_from_kwargs(kwargs: dict[str, Any]) -> CronActionOutcome | CronOwner:
    owner_raw = kwargs.get("_cron_owner")
    if not isinstance(owner_raw, dict) or not owner_raw.get("kind"):
        return CronActionOutcome(
            ok=False,
            text="Scheduling is not available in this context.",
        )
    return CronOwner(**owner_raw)


def _normalize_action(value: Any) -> str:
    action = str(value or "").strip().lower()
    if action == "add":
        return "schedule"
    if action == "remove":
        return "cancel"
    return action


def _run_cron_action_sync(kwargs: dict[str, Any], *, call) -> CronActionOutcome:
    owner = _owner_from_kwargs(kwargs)
    if isinstance(owner, CronActionOutcome):
        return owner
    service = get_cron_service()
    action = _normalize_action(kwargs.get("action"))

    if action == "list":
        jobs = call(service.list_jobs(owner_key=owner.key))
        if not jobs:
            return CronActionOutcome(ok=True, text="No scheduled tasks for this conversation.")
        lines = [f"{len(jobs)} scheduled task(s):"] + [_render_job(job) for job in jobs]
        return CronActionOutcome(ok=True, text="\n".join(lines), meta={"count": len(jobs)})

    if action == "cancel":
        job_id = str(kwargs.get("job_id") or "").strip()
        if not job_id:
            return CronActionOutcome(ok=False, text="cancel needs a job_id (see action='list').")
        if call(service.cancel_job(job_id, owner_key=owner.key)):
            return CronActionOutcome(ok=True, text=f"Task `{job_id}` cancelled.")
        return CronActionOutcome(ok=False, text=f"No task `{job_id}` found for this conversation.")

    if action in {"pause", "resume"}:
        job_id = str(kwargs.get("job_id") or "").strip()
        if not job_id:
            return CronActionOutcome(ok=False, text=f"{action} needs a job_id (see action='list').")
        mutator = getattr(service, "set_job_enabled", None)
        if mutator is None:
            return CronActionOutcome(ok=False, text="Pause/resume is not available.")
        enabled = action == "resume"
        if call(mutator(job_id, enabled, owner_key=owner.key)):
            verb = "resumed" if enabled else "paused"
            return CronActionOutcome(ok=True, text=f"Task `{job_id}` {verb}.")
        return CronActionOutcome(ok=False, text=f"No task `{job_id}` found for this conversation.")

    if action == "schedule":
        if bool(kwargs.get("_cron_in_context")):
            return CronActionOutcome(
                ok=False,
                text="Cannot schedule new tasks from inside a running scheduled task.",
            )
        message = str(kwargs.get("message") or "").strip()
        if not message:
            return CronActionOutcome(
                ok=False, text="schedule needs a message — the instruction to run when due."
            )
        try:
            schedule = _build_schedule(kwargs)
            delete_after_run = kwargs.get("delete_after_run")
            job = call(
                service.add_job(
                    name=str(kwargs.get("name") or "").strip(),
                    message=message,
                    schedule=schedule,
                    owner=owner,
                    delete_after_run=(
                        bool(delete_after_run) if delete_after_run is not None else None
                    ),
                )
            )
        except (ValueError, TypeError) as exc:
            return CronActionOutcome(ok=False, text=f"Could not schedule: {exc}")
        return CronActionOutcome(
            ok=True,
            text=(
                f"Scheduled **{job.name}** (`{job.id}`) — {_describe_schedule(job.schedule)}; "
                f"first run {_fmt_ms(job.state.next_run_at_ms)}. The result will be "
                "delivered to this conversation."
            ),
            meta={"job_id": job.id},
        )

    return CronActionOutcome(ok=False, text=f"Unknown action {action!r}.")


async def _run_cron_action_async(kwargs: dict[str, Any], *, call) -> CronActionOutcome:
    owner = _owner_from_kwargs(kwargs)
    if isinstance(owner, CronActionOutcome):
        return owner
    service = get_cron_service()
    action = _normalize_action(kwargs.get("action"))

    if action == "list":
        jobs = await call(service.list_jobs(owner_key=owner.key))
        if not jobs:
            return CronActionOutcome(ok=True, text="No scheduled tasks for this conversation.")
        lines = [f"{len(jobs)} scheduled task(s):"] + [_render_job(job) for job in jobs]
        return CronActionOutcome(ok=True, text="\n".join(lines), meta={"count": len(jobs)})

    if action == "cancel":
        job_id = str(kwargs.get("job_id") or "").strip()
        if not job_id:
            return CronActionOutcome(ok=False, text="cancel needs a job_id (see action='list').")
        if await call(service.cancel_job(job_id, owner_key=owner.key)):
            return CronActionOutcome(ok=True, text=f"Task `{job_id}` cancelled.")
        return CronActionOutcome(ok=False, text=f"No task `{job_id}` found for this conversation.")

    if action in {"pause", "resume"}:
        job_id = str(kwargs.get("job_id") or "").strip()
        if not job_id:
            return CronActionOutcome(ok=False, text=f"{action} needs a job_id (see action='list').")
        mutator = getattr(service, "set_job_enabled", None)
        if mutator is None:
            return CronActionOutcome(ok=False, text="Pause/resume is not available.")
        enabled = action == "resume"
        if await call(mutator(job_id, enabled, owner_key=owner.key)):
            verb = "resumed" if enabled else "paused"
            return CronActionOutcome(ok=True, text=f"Task `{job_id}` {verb}.")
        return CronActionOutcome(ok=False, text=f"No task `{job_id}` found for this conversation.")

    if action == "schedule":
        if bool(kwargs.get("_cron_in_context")):
            return CronActionOutcome(
                ok=False,
                text="Cannot schedule new tasks from inside a running scheduled task.",
            )
        message = str(kwargs.get("message") or "").strip()
        if not message:
            return CronActionOutcome(
                ok=False, text="schedule needs a message — the instruction to run when due."
            )
        try:
            schedule = _build_schedule(kwargs)
            delete_after_run = kwargs.get("delete_after_run")
            job = await call(
                service.add_job(
                    name=str(kwargs.get("name") or "").strip(),
                    message=message,
                    schedule=schedule,
                    owner=owner,
                    delete_after_run=(
                        bool(delete_after_run) if delete_after_run is not None else None
                    ),
                )
            )
        except (ValueError, TypeError, PermissionError) as exc:
            return CronActionOutcome(ok=False, text=f"Could not schedule: {exc}")
        return CronActionOutcome(
            ok=True,
            text=(
                f"Scheduled **{job.name}** (`{job.id}`) — {_describe_schedule(job.schedule)}; "
                f"first run {_fmt_ms(job.state.next_run_at_ms)}. The result will be "
                "delivered to this conversation."
            ),
            meta={"job_id": job.id},
        )

    return CronActionOutcome(ok=False, text=f"Unknown action {action!r}.")


__all__ = ["CronActionOutcome", "run_cron_action", "run_cron_action_async"]
