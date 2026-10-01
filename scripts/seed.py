#!/usr/bin/env python3
"""Database initialisation + optional demo seed.

    python -m scripts.seed              # migrate + seed demo user
    python -m scripts.seed --no-demo    # migrate only
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialise the LocalAI Workspace database")
    parser.add_argument("--no-demo", action="store_true", help="skip demo user creation")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    from database.migrations import init_db

    applied = init_db()
    print(f"migrations applied: {applied or 'none (already up to date)'}")

    if not args.no_demo:
        from database.seed import seed_demo

        created = seed_demo()
        print(f"seeded: {created}")
        if created.get("users"):
            print("demo login -> demo@localai.workspace / demo1234")


if __name__ == "__main__":
    main()
