from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def safe_filename(filename: str) -> str:
    path = Path(filename)
    return path.name.replace(" ", "_")

