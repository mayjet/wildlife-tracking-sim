from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
for source_root in (
    REPOSITORY_ROOT / "libs" / "shepherd-contracts" / "src",
    REPOSITORY_ROOT / "packages" / "field-environment" / "src",
    REPOSITORY_ROOT / "packages" / "field-tracker" / "src",
    REPOSITORY_ROOT / "packages" / "field-benchmark" / "src",
):
    sys.path.insert(0, str(source_root))
