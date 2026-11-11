"""Print the seed regions as ``GET /regions`` would return them.

    python scripts/seed_regions.py

The four boxes are the MVP set (two hotspots, two controls). Loading them
into the Regions table is a Detect TODO: ``--write`` is refused on purpose
so this script cannot touch AWS until that PutItem exists.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared" / "python"))

from gnssiw.regions import SEED_REGIONS  # noqa: E402


def main() -> None:
    if "--write" in sys.argv:
        sys.exit(
            "TODO(Detect): PutItem these regions into REGIONS_TABLE. "
            "The skeleton only prints them."
        )
    payload = {"regions": [region.to_api() for region in SEED_REGIONS]}
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
