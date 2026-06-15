"""Offline entry points for the pattern miner.

Run from the backend root so the `config.*` / `modules.*` imports resolve and
the shared `.env` is read:

    python -m modules.pattern_miner.jobs.classify_all --dry-run
    python -m modules.pattern_miner.jobs.periodic_dedupe --apply
    python -m modules.pattern_miner.jobs.export_report --out report.json
"""

from __future__ import annotations

import logging


def configure_job_logging(*, run_id: str, level: int = logging.INFO) -> None:
    """Plain stdlib logging, same format as the API server. The run_id is logged
    into each job's start/end lines so a run is grep-able across the output."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
