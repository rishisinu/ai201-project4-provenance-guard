"""In-memory storage for submissions and the structured audit log.

Everything here lives in process memory only. That's a deliberate choice for
this project (see planning.md) -- no auth/session model is required, and a
server restart clearing state is acceptable for a grading/demo system.
"""

import uuid
from datetime import datetime, timezone

# content_id -> submission dict
SUBMISSIONS: dict[str, dict] = {}

# append-only list of structured audit log entries
AUDIT_LOG: list[dict] = []


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_content_id() -> str:
    return str(uuid.uuid4())


def save_submission(entry: dict) -> None:
    SUBMISSIONS[entry["content_id"]] = entry


def get_submission(content_id: str) -> dict | None:
    return SUBMISSIONS.get(content_id)


def submissions_under_review() -> list[dict]:
    return [s for s in SUBMISSIONS.values() if s["status"] == "under_review"]


def log_event(entry: dict) -> None:
    entry.setdefault("timestamp", now_iso())
    AUDIT_LOG.append(entry)


def get_log(limit: int = 100) -> list[dict]:
    return AUDIT_LOG[-limit:][::-1]
