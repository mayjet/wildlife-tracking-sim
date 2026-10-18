from __future__ import annotations

from enum import Enum


class AgeClass(str, Enum):
    ADULT = "ADULT"
    JUVENILE = "JUVENILE"
    UNKNOWN = "UNKNOWN"

