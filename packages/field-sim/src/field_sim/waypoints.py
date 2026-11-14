from __future__ import annotations

import json
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from shapely.geometry import mapping, Point

from field_environment import EnvironmentCase, resolve_repository_path, validate_case_id


class WaypointSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    waypoint_id: str = Field(alias="id", min_length=1)
    x_m: float
    y_m: float
    dwell_s: float = Field(default=0.0, ge=0.0)


class WaypointSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    waypoint_set_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    waypoints: tuple[WaypointSpec, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_identifiers(self) -> "WaypointSet":
        validate_case_id(self.waypoint_set_id)
        validate_case_id(self.case_id)
        identifiers = [waypoint.waypoint_id for waypoint in self.waypoints]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("waypoint ids must be unique")
        return self


def load_waypoint_set(
    path: str | Path,
    *,
    start: str | Path | None = None,
) -> tuple[WaypointSet, Path]:
    resolved = resolve_repository_path(path, start=start)
    if not resolved.is_file():
        raise FileNotFoundError(f"waypoint set not found: {resolved}")
    raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    return WaypointSet.model_validate(raw), resolved


def validate_waypoint_set(
    environment_case: EnvironmentCase,
    waypoint_set: WaypointSet,
) -> tuple[str, ...]:
    if waypoint_set.case_id != environment_case.case_spec.case_id:
        raise ValueError("WaypointSet.case_id does not match the loaded Case")
    warnings = []
    for waypoint in waypoint_set.waypoints:
        try:
            environment_case.heightmap.surface_elevation_at(waypoint.x_m, waypoint.y_m)
        except IndexError as error:
            raise ValueError(
                f"waypoint {waypoint.waypoint_id} is outside the terrain surface"
            ) from error
        if environment_case.buildings is not None and environment_case.buildings.covers(
            waypoint.x_m, waypoint.y_m
        ):
            raise ValueError(f"waypoint {waypoint.waypoint_id} is inside a building")
        if not environment_case.farm_boundary.polygon.covers(
            Point(waypoint.x_m, waypoint.y_m)
        ):
            warnings.append(f"{waypoint.waypoint_id}: outside farm boundary")
        if environment_case.forest is not None and environment_case.forest.covers(
            waypoint.x_m, waypoint.y_m
        ):
            warnings.append(f"{waypoint.waypoint_id}: inside forest")
    return tuple(warnings)


def save_waypoint_set(
    path: str | Path,
    waypoint_set: WaypointSet,
    *,
    overwrite: bool = False,
) -> Path:
    destination = Path(path).expanduser().resolve()
    if destination.exists() and not overwrite:
        raise FileExistsError(f"WaypointSet already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = waypoint_set.model_dump(mode="json", by_alias=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    temporary.replace(destination)
    return destination


def waypoint_set_geojson(waypoint_set: WaypointSet) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": mapping(Point(waypoint.x_m, waypoint.y_m)),
                "properties": {
                    "waypoint_id": waypoint.waypoint_id,
                    "order": index,
                    "dwell_s": waypoint.dwell_s,
                    "coordinate_system": "case-local-ENU-metres",
                },
            }
            for index, waypoint in enumerate(waypoint_set.waypoints)
        ],
    }


def write_waypoint_geojson(path: str | Path, waypoint_set: WaypointSet) -> Path:
    destination = Path(path)
    destination.write_text(
        json.dumps(waypoint_set_geojson(waypoint_set), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return destination
