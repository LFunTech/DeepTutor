"""PostgreSQL-only compatible LLM usage ledger facade.

Upstream's account-local ledger uses a SQLite file. Enterprise/default runtime
must not create local database caches, so this module preserves the public API
used by transport metrics while making durable local ledger writes unavailable.
Per-turn usage is still captured by ``TurnUsage`` and persisted with turn events
by the configured PostgreSQL session store.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def ledger_path() -> Path:
    """Return a harmless sentinel path; callers pass it back to ``record_call``.

    The path is never opened by this module. Returning a Path instead of raising
    keeps optional metrics instrumentation from turning LLM calls into failures.
    """
    return Path("/dev/null")


def record_call(
    path: Path,
    call: dict[str, Any],
    *,
    started_at: float,
    session_id: str = "",
    turn_id: str = "",
    source: str = "",
) -> None:
    """Do not persist a local usage row in PostgreSQL-only runtimes."""
    return None


def usage_records(
    start_at: float, end_at: float, *, path: Path | None = None
) -> list[dict[str, Any]]:
    return []


def merge_records(
    history: list[dict[str, Any]],
    ledger: list[dict[str, Any]],
    *,
    persisted_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    if not ledger:
        return list(history)
    ids = (persisted_ids or set()) | {
        call["call_id"]
        for record in ledger
        for summary in record.get("summaries", [])
        for call in summary.get("call_details", [])
        if call.get("call_id")
    }
    from .metrics import TurnUsage

    merged = []
    for record in history:
        summaries = []
        for summary in record.get("summaries") or []:
            details = summary.get("call_details") or []
            if details and any(c.get("call_id") in ids for c in details):
                collector = TurnUsage()
                collector.calls = [c for c in details if c.get("call_id") not in ids]
                if rest := collector.summary():
                    summaries.append(rest)
            else:
                summaries.append(summary)
        merged.append({**record, "summaries": summaries})
    return merged + ledger


def combined_usage_records(
    history: list[dict[str, Any]], start_at: float, end_at: float
) -> list[dict[str, Any]]:
    return merge_records(history, usage_records(start_at, end_at))
