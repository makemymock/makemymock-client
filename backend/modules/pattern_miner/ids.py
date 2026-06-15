"""ID + slug helpers."""

from __future__ import annotations

import datetime as dt
import uuid

from slugify import slugify


def safe_slug(name: str) -> str:
    """Kebab-case, ASCII-only, capped at 40 chars."""
    slug = slugify(name or "", max_length=40)
    return slug or f"pattern-{uuid.uuid4().hex[:8]}"


def generate_run_id() -> str:
    """Short run id with embedded timestamp for grep-ability in logs."""
    return dt.datetime.now(dt.timezone.utc).strftime("run-%Y%m%d-%H%M%S")
