from __future__ import annotations

from math import atan2

import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point, shape
from shapely.ops import unary_union
from shapely.prepared import prep

from field_environment import EnvironmentCase, FeatureLayerStatus, TraversabilityValue


def build_route_points(
    environment_case: EnvironmentCase,
    coordinates: np.ndarray,
    segment_indices: np.ndarray,
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    coordinates = np.asarray(coordinates, dtype=np.float64)
    if coordinates.ndim != 2 or coordinates.shape[1] != 2 or len(coordinates) < 2:
        raise ValueError("route coordinates must have shape (n, 2), n >= 2")
    if len(segment_indices) != len(coordinates):
        raise ValueError("segment_indices length must match coordinates")
    deltas = np.diff(coordinates, axis=0)
    lengths = np.linalg.norm(deltas, axis=1)
    if np.any(lengths <= 0.0):
        raise ValueError("resolved route contains duplicate adjacent points")
    distance = np.concatenate(([0.0], np.cumsum(lengths)))
    buildings = environment_case.buildings
    building_geometry = None
    prepared_buildings = None
    if buildings is not None and buildings.status is FeatureLayerStatus.AVAILABLE:
        building_geometry = unary_union(
            [shape(feature["geometry"]) for feature in buildings.features]
        )
        prepared_buildings = prep(building_geometry)
    forest = environment_case.forest
    prepared_forest = None
    if forest is not None and forest.status is FeatureLayerStatus.AVAILABLE:
        forest_geometry = unary_union(
            [shape(feature["geometry"]) for feature in forest.features]
        )
        prepared_forest = prep(forest_geometry)
    elevations = []
    inside_farm = []
    inside_forest = []
    for x_m, y_m in coordinates:
        try:
            elevations.append(environment_case.heightmap.surface_elevation_at(x_m, y_m))
        except IndexError as error:
            raise ValueError("resolved route leaves the terrain surface") from error
        inside_farm.append(environment_case.farm_boundary.polygon.covers(Point(x_m, y_m)))
        inside_forest.append(
            bool(prepared_forest is not None and prepared_forest.covers(Point(x_m, y_m)))
        )
        if prepared_buildings is not None and prepared_buildings.covers(Point(x_m, y_m)):
            raise ValueError("resolved route enters a building")
        if environment_case.traversability is not None:
            x_index, y_index = environment_case.heightmap.indices_at(x_m, y_m)
            if (
                environment_case.traversability.values[y_index, x_index]
                == TraversabilityValue.PROHIBITED
            ):
                raise ValueError(
                    "resolved route enters prohibited traversability at "
                    f"x={x_m:.2f} m, y={y_m:.2f} m "
                    f"(waypoint segment {int(segment_indices[len(elevations) - 1]) + 1})"
                )
    line = LineString(coordinates)
    if building_geometry is not None:
        if line.intersects(building_geometry):
            raise ValueError("resolved route segment intersects a building")
    headings = np.asarray([atan2(delta[1], delta[0]) for delta in deltas])
    headings = np.concatenate((headings, headings[-1:]))
    elevation_values = np.asarray(elevations)
    slopes = np.concatenate((np.diff(elevation_values) / lengths, [0.0]))
    warnings = []
    if not all(inside_farm):
        warnings.append("route includes positions outside the farm boundary")
    if any(inside_forest):
        warnings.append("route includes positions inside forest")
    frame = pd.DataFrame(
        {
            "path_index": np.arange(len(coordinates), dtype=np.int64),
            "segment_index": np.asarray(segment_indices, dtype=np.int64),
            "distance_m": distance,
            "x_m": coordinates[:, 0],
            "y_m": coordinates[:, 1],
            "z_m": elevation_values,
            "heading_rad": headings,
            "slope_ratio": slopes,
            "inside_farm": inside_farm,
            "inside_forest": inside_forest,
        }
    )
    return frame, tuple(warnings)
