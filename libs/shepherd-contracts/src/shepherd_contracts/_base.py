from __future__ import annotations

from typing import TypeAlias

from pydantic import BaseModel, ConfigDict, JsonValue

JsonScalar: TypeAlias = str | int | float | bool | None


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
