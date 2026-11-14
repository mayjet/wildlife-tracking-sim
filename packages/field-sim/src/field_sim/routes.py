from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from matplotlib import pyplot as plt
from pydantic import BaseModel, ConfigDict, Field, model_validator
from shapely.geometry import LineString, mapping

from field_environment import EnvironmentCase, resolve_case_path, resolve_repository_path, validate_case_id

from .config import SimulationConfig, TimedWaypoint, WaypointMotion
from .waypoints import WaypointSet, write_waypoint_geojson


class RouteDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    route_id: str = Field(min_length=1)
    route_group_id: str = Field(min_length=1)
    method: str = Field(min_length=1)
    module: str | None = None
    waypoint_set: str = Field(min_length=1)
    seed: int = 0
    parent_route_id: str | None = None
    parameters: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_ids(self) -> "RouteDefinition":
        validate_case_id(self.route_id)
        validate_case_id(self.route_group_id)
        if self.parent_route_id is not None:
            validate_case_id(self.parent_route_id)
        return self


@dataclass(frozen=True)
class ResolvedRoute:
    definition: RouteDefinition
    waypoint_set: WaypointSet
    points: pd.DataFrame
    warnings: tuple[str, ...] = ()
    planning: dict[str, object] = field(default_factory=dict)

    @property
    def length_m(self) -> float:
        return float(self.points["distance_m"].iloc[-1])

    @property
    def route_sha256(self) -> str:
        digest = hashlib.sha256()
        digest.update(self.definition.model_dump_json().encode("utf-8"))
        digest.update(self.waypoint_set.model_dump_json(by_alias=True).encode("utf-8"))
        digest.update(self.points.to_csv(index=False).encode("utf-8"))
        return digest.hexdigest()


def load_route_definition(
    path: str | Path,
    *,
    start: str | Path | None = None,
) -> tuple[RouteDefinition, Path]:
    resolved = resolve_repository_path(path, start=start)
    if not resolved.is_file():
        raise FileNotFoundError(f"route definition not found: {resolved}")
    raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    return RouteDefinition.model_validate(raw), resolved


def route_to_simulation_config(
    route: ResolvedRoute,
    *,
    dataset_id: str,
    speed_mps: float,
    step_s: float,
    truth_id: str = "deer-001",
    age_class: str = "UNKNOWN",
    seed: int | None = None,
) -> SimulationConfig:
    if speed_mps <= 0.0 or step_s <= 0.0:
        raise ValueError("speed_mps and step_s must be positive")
    points = route.points
    times = points["distance_m"].to_numpy(dtype=float) / speed_mps
    timed = [
        TimedWaypoint(
            timestamp_s=float(timestamp_s),
            position={"x_m": float(row.x_m), "y_m": float(row.y_m)},
        )
        for timestamp_s, row in zip(times, points.itertuples(index=False))
    ]
    duration_s = float(np.ceil(times[-1] / step_s) * step_s)
    if duration_s > times[-1] + 1.0e-9:
        last = points.iloc[-1]
        timed.append(
            TimedWaypoint(
                timestamp_s=duration_s,
                position={"x_m": float(last.x_m), "y_m": float(last.y_m)},
            )
        )
    return SimulationConfig(
        case_id=route.waypoint_set.case_id,
        dataset_id=dataset_id,
        seed=route.definition.seed if seed is None else seed,
        duration_s=duration_s,
        step_s=step_s,
        truth_id=truth_id,
        age_class=age_class,
        motion=WaypointMotion(kind="waypoints", waypoints=tuple(timed)),
    )


def save_resolved_route(
    cases_root: str | Path,
    route: ResolvedRoute,
    *,
    overwrite: bool = False,
) -> Path:
    case_directory = resolve_case_path(cases_root, route.waypoint_set.case_id)
    group_directory = case_directory / "routes" / route.definition.route_group_id
    destination = group_directory / "variants" / route.definition.route_id
    if destination.exists() and not overwrite:
        raise FileExistsError(f"ResolvedRoute already exists: {destination}")
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.mkdir(parents=True, exist_ok=False)
    group_directory.mkdir(parents=True, exist_ok=True)
    try:
        (group_directory / "waypoints.json").write_text(
            route.waypoint_set.model_dump_json(indent=2, by_alias=True), encoding="utf-8"
        )
        write_waypoint_geojson(group_directory / "waypoints.geojson", route.waypoint_set)
        route.points.to_parquet(temporary / "path_points.parquet", index=False, engine="pyarrow")
        line = LineString(route.points[["x_m", "y_m"]].to_numpy())
        (temporary / "path.geojson").write_text(
            json.dumps(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "geometry": mapping(line),
                            "properties": {
                                "route_id": route.definition.route_id,
                                "method": route.definition.method,
                                "coordinate_system": "case-local-ENU-metres",
                            },
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        metadata = {
            "schema_version": "1.0",
            "definition": route.definition.model_dump(mode="json"),
            "waypoint_set_id": route.waypoint_set.waypoint_set_id,
            "case_id": route.waypoint_set.case_id,
            "length_m": route.length_m,
            "point_count": len(route.points),
            "route_sha256": route.route_sha256,
            "warnings": list(route.warnings),
            "planning": route.planning,
        }
        (temporary / "route.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        figure, axis = plt.subplots(figsize=(7, 7))
        axis.plot(route.points["x_m"], route.points["y_m"], linewidth=2.0)
        axis.scatter(
            [point.x_m for point in route.waypoint_set.waypoints],
            [point.y_m for point in route.waypoint_set.waypoints],
            marker="o",
            color="red",
            label="Waypoints",
        )
        axis.set_aspect("equal", adjustable="box")
        axis.set_xlabel("x / East (m)")
        axis.set_ylabel("y / North (m)")
        axis.set_title(route.definition.route_id)
        axis.legend()
        figure.tight_layout()
        figure.savefig(temporary / "preview.png", dpi=150)
        plt.close(figure)
        if destination.exists():
            import shutil

            shutil.rmtree(destination)
        temporary.replace(destination)
    except Exception:
        import shutil

        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return destination


def load_resolved_route(
    cases_root: str | Path,
    case_id: str,
    route_id: str,
) -> ResolvedRoute:
    case_directory = resolve_case_path(cases_root, case_id)
    matches = list((case_directory / "routes").glob(f"*/variants/{route_id}"))
    if not matches:
        raise FileNotFoundError(f"ResolvedRoute not found: {route_id}")
    if len(matches) > 1:
        raise ValueError(f"ResolvedRoute id is not unique: {route_id}")
    directory = matches[0]
    metadata = json.loads((directory / "route.json").read_text(encoding="utf-8"))
    group_directory = directory.parent.parent
    waypoint_set = WaypointSet.model_validate_json(
        (group_directory / "waypoints.json").read_text(encoding="utf-8")
    )
    route = ResolvedRoute(
        definition=RouteDefinition.model_validate(metadata["definition"]),
        waypoint_set=waypoint_set,
        points=pd.read_parquet(directory / "path_points.parquet", engine="pyarrow"),
        warnings=tuple(metadata.get("warnings", ())),
        planning=metadata.get("planning", {}),
    )
    if route.route_sha256 != metadata.get("route_sha256"):
        raise ValueError(f"ResolvedRoute hash mismatch: {route_id}")
    return route
