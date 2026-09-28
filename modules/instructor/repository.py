"""Stable facade for AI Instructor persistence operations.

Schema, profile, and run lifecycle queries are implemented in focused
modules while existing imports continue to work unchanged.
"""

from .repository_profiles import (
    get_instructor_profile,
    list_enabled_profiles,
    upsert_instructor_profile,
)
from .repository_run_lifecycle import (
    fail_instructor_run,
    finalize_instructor_run,
    recover_stale_instructor_runs,
)
from .repository_run_queries import (
    count_runs_between,
    list_instructor_runs,
    list_recent_agent_lecture_titles,
)
from .repository_run_reservations import (
    renew_instructor_run_lease,
    reserve_instructor_run,
    update_instructor_run,
)
from .repository_schema import ensure_instructor_schema

__all__ = [
    "count_runs_between",
    "ensure_instructor_schema",
    "fail_instructor_run",
    "finalize_instructor_run",
    "get_instructor_profile",
    "list_enabled_profiles",
    "list_instructor_runs",
    "list_recent_agent_lecture_titles",
    "recover_stale_instructor_runs",
    "renew_instructor_run_lease",
    "reserve_instructor_run",
    "update_instructor_run",
    "upsert_instructor_profile",
]
