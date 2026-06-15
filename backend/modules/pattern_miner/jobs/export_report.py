"""Export a pattern → questions report.

The sales-facing artifact: "here are N distinct reasoning patterns, here are
which JEE questions use each, students who've practised X have not seen Y."

Usage (from the backend root):
    python -m modules.pattern_miner.jobs.export_report --out report.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections import defaultdict

from modules.pattern_miner.constants import (
    ASSIGNMENTS_COLLECTION,
    PATTERNS_COLLECTION,
)
from modules.pattern_miner.db import close_client, get_pattern_miner_db
from modules.pattern_miner.ids import generate_run_id
from modules.pattern_miner.jobs import configure_job_logging

logger = logging.getLogger(__name__)


async def _amain(out_path: str) -> None:
    configure_job_logging(run_id=generate_run_id())
    db = get_pattern_miner_db()
    try:
        patterns_by_id: dict[str, dict] = {}
        async for p in db[PATTERNS_COLLECTION].find({}):
            patterns_by_id[p["pattern_id"]] = {
                "pattern_id": p["pattern_id"],
                "chapter": p["chapter"],
                "name": p["name"],
                "description": p["description"],
                "signature": p.get("signature", {}),
                "member_count": p.get("member_count", 0),
                "question_ids": [],
            }

        grouped: dict[str, list[str]] = defaultdict(list)
        async for a in db[ASSIGNMENTS_COLLECTION].find(
            {}, {"question_id": 1, "pattern_id": 1, "_id": 0}
        ):
            grouped[a["pattern_id"]].append(a["question_id"])

        for pid, qids in grouped.items():
            if pid in patterns_by_id:
                patterns_by_id[pid]["question_ids"] = qids

        out = sorted(
            patterns_by_id.values(), key=lambda x: (x["chapter"], -x["member_count"])
        )
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"patterns": out}, f, ensure_ascii=False, indent=2)
        print(f"Wrote {len(out)} patterns to {out_path}")
    finally:
        await close_mongo_connection()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="pattern_report.json")
    args = p.parse_args()
    asyncio.run(_amain(args.out))


if __name__ == "__main__":
    main()
