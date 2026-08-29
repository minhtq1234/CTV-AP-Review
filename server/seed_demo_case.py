"""Put the synthetic demo case into the local store, so a fresh clone has
something to look at.

    cd server && python3 seed_demo_case.py

Safe to re-run: it replaces the demo case and leaves every other case alone.
Never touches a real submission -- it only ever writes the one fixed id below.
"""
from __future__ import annotations

import os
import shutil
import sys

from test_fixtures import demo_case

#: A fixed, obviously-synthetic id, so re-seeding replaces the demo rather than
#: piling up copies -- and so it can never collide with a real case's uuid.
DEMO_CASE_ID = "demo0000000000000000000000000000"


def main(data_dir: str = "data") -> int:
    target = os.path.join(data_dir, "cases", DEMO_CASE_ID)
    if os.path.isdir(target):
        shutil.rmtree(target)
    os.makedirs(target, exist_ok=True)
    demo_case.build(target, case_id=DEMO_CASE_ID)
    print(f"seeded demo case at {target}")
    print("restart the API if it is running -- it caches its case list at startup")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
