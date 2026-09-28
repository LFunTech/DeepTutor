"""Built-in cron — scheduled tasks for chat and partners."""

from deeptutor.services.cron.repository import CronRepository, SQLiteCronRepository
from deeptutor.services.cron.service import (
    CronJob,
    CronOwner,
    CronSchedule,
    CronService,
    compute_next_run,
    get_cron_service,
    validate_schedule,
)


def __getattr__(name: str):
    if name == "PostgresCronService":
        from deeptutor.services.cron.postgres import PostgresCronService

        return PostgresCronService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "CronJob",
    "CronOwner",
    "CronRepository",
    "CronSchedule",
    "CronService",
    "PostgresCronService",
    "SQLiteCronRepository",
    "compute_next_run",
    "get_cron_service",
    "validate_schedule",
]
