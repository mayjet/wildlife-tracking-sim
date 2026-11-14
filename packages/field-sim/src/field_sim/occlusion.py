from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import hypot

import numpy as np
from shapely import make_valid
from shapely.geometry import GeometryCollection, LineString, MultiLineString, Point, box, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree

from field_environment import EnvironmentCase, FeatureLayerStatus


class OcclusionKind(str, Enum):
    NONE = "NONE"
    TERRAIN = "TERRAIN"
    FOREST = "FOREST"
    BUILDING = "BUILDING"


@dataclass(frozen=True)
class RayOcclusion:
    kind: OcclusionKind
    distance_m: float | None = None


@dataclass(frozen=True)
class _Obstacle:
    geometry: object
    kind: OcclusionKind
    height_m: float
    follow_terrain: bool
    base_z_m: float | None


def _valid_polygonal(geometry):
    if geometry.is_empty:
        return GeometryCollection()
    return geometry if geometry.is_valid else make_valid(geometry)


def _layer_union(layer):
    if layer is None or layer.status is not FeatureLayerStatus.AVAILABLE:
        return GeometryCollection()
    return unary_union([shape(feature["geometry"]) for feature in layer.features])


def _feature_height(layer, properties: dict, default_height_m: float) -> float:
    return float(
        properties.get("height_m")
        or properties.get("assumed_height_m")
        or layer.assumed_height_m
        or default_height_m
    )


def _analytic_extent(environment_case: EnvironmentCase):
    grid = environment_case.heightmap.grid
    return box(
        grid.origin.x_m,
        grid.origin.y_m,
        grid.origin.x_m + (grid.width_cells - 1) * grid.cell_size_m,
        grid.origin.y_m + (grid.height_cells - 1) * grid.cell_size_m,
    )


def _forest_scene_geometry(environment_case: EnvironmentCase):
    crop = _analytic_extent(environment_case)
    forest = _layer_union(environment_case.forest).intersection(crop)
    buildings = _layer_union(environment_case.buildings).intersection(crop)
    forest = forest.difference(buildings)
    smoothing_m = 0.0
    if environment_case.scene_crop is not None and environment_case.scene_crop.features:
        smoothing_m = float(
            environment_case.scene_crop.features[0]
            .get("properties", {})
            .get("forest_boundary_smoothing_m", 0.0)
        )
    if smoothing_m > 0.0 and not forest.is_empty:
        half = smoothing_m * 0.5
        forest = forest.buffer(half, join_style=2).buffer(-half, join_style=2)
        forest = forest.simplify(half, preserve_topology=True)
    return _valid_polygonal(forest)


def _intersection_lines(geometry):
    if geometry.is_empty:
        return
    if isinstance(geometry, LineString):
        yield geometry
    elif isinstance(geometry, MultiLineString):
        yield from geometry.geoms
    elif hasattr(geometry, "geoms"):
        for part in geometry.geoms:
            yield from _intersection_lines(part)


def _polygon_parts(geometry):
    if geometry.is_empty:
        return
    if geometry.geom_type == "Polygon":
        yield geometry
    elif hasattr(geometry, "geoms"):
        for part in geometry.geoms:
            yield from _polygon_parts(part)


# Caseの地形・森林・建物に対して3D視線の最初の遮蔽を判定する．
class AnalyticRaycastBackend:
    def __init__(self, environment_case: EnvironmentCase, *, sample_step_m: float = 0.5):
        if sample_step_m <= 0.0:
            raise ValueError("sample_step_m must be positive")
        self.environment_case = environment_case
        self.sample_step_m = float(sample_step_m)
        self._forest_geometry = _forest_scene_geometry(environment_case)
        self._obstacles = self._build_obstacles()
        geometries = [obstacle.geometry for obstacle in self._obstacles]
        self._tree = STRtree(geometries) if geometries else None

    def _surface_elevation(self, x_m: float, y_m: float) -> float:
        return self.environment_case.heightmap.surface_elevation_at(x_m, y_m)

    def _surface_elevations(self, x_m: np.ndarray, y_m: np.ndarray) -> np.ndarray:
        heightmap = self.environment_case.heightmap
        grid = heightmap.grid
        x_coordinate = (x_m - grid.origin.x_m) / grid.cell_size_m
        y_coordinate = (y_m - grid.origin.y_m) / grid.cell_size_m
        tolerance = 1.0e-9
        if np.any(x_coordinate < -tolerance) or np.any(
            x_coordinate > grid.width_cells - 1 + tolerance
        ):
            raise IndexError("x coordinate is outside the terrain mesh surface")
        if np.any(y_coordinate < -tolerance) or np.any(
            y_coordinate > grid.height_cells - 1 + tolerance
        ):
            raise IndexError("y coordinate is outside the terrain mesh surface")
        x_coordinate = np.clip(x_coordinate, 0.0, grid.width_cells - 1)
        y_coordinate = np.clip(y_coordinate, 0.0, grid.height_cells - 1)
        x_index = np.minimum(np.floor(x_coordinate).astype(int), grid.width_cells - 2)
        y_index = np.minimum(np.floor(y_coordinate).astype(int), grid.height_cells - 2)
        u = x_coordinate - x_index
        v = y_coordinate - y_index
        south_west = heightmap.values[y_index, x_index]
        south_east = heightmap.values[y_index, x_index + 1]
        north_west = heightmap.values[y_index + 1, x_index]
        north_east = heightmap.values[y_index + 1, x_index + 1]
        return np.where(
            v <= u,
            south_west + u * (south_east - south_west) + v * (north_east - south_east),
            south_west + u * (north_east - south_west) + v * (north_west - south_west),
        )

    def _build_obstacles(self) -> tuple[_Obstacle, ...]:
        obstacles = []
        forest_layer = self.environment_case.forest
        if not self._forest_geometry.is_empty and forest_layer is not None:
            obstacles.append(
                _Obstacle(
                    geometry=self._forest_geometry,
                    kind=OcclusionKind.FOREST,
                    height_m=float(forest_layer.assumed_height_m or 10.0),
                    follow_terrain=True,
                    base_z_m=None,
                )
            )
        crop = _analytic_extent(self.environment_case)
        facility_footprints = _layer_union(
            self.environment_case.facility_buildings
        ).intersection(crop)
        for buildings, subtract in (
            (self.environment_case.buildings, facility_footprints),
            (self.environment_case.facility_buildings, GeometryCollection()),
        ):
            if buildings is None or buildings.status is not FeatureLayerStatus.AVAILABLE:
                continue
            for feature in buildings.features:
                geometry = shape(feature["geometry"]).intersection(crop)
                if not subtract.is_empty:
                    geometry = geometry.difference(subtract)
                properties = feature.get("properties") or {}
                for polygon in _polygon_parts(_valid_polygonal(geometry)):
                    representative = polygon.representative_point()
                    base_z_m = self._surface_elevation(representative.x, representative.y)
                    obstacles.append(
                        _Obstacle(
                            geometry=polygon,
                            kind=OcclusionKind.BUILDING,
                            height_m=_feature_height(buildings, properties, 5.0),
                            follow_terrain=False,
                            base_z_m=base_z_m,
                        )
                    )
        return tuple(obstacles)

    def point_inside_forest(self, x_m: float, y_m: float) -> bool:
        return bool(
            not self._forest_geometry.is_empty
            and self._forest_geometry.covers(Point(float(x_m), float(y_m)))
        )

    def _terrain_hit_distance(
        self,
        origin: np.ndarray,
        target: np.ndarray,
        *,
        epsilon_m: float,
    ) -> float | None:
        direction = target - origin
        distance = float(np.linalg.norm(direction))
        horizontal_distance = hypot(float(direction[0]), float(direction[1]))
        if distance <= epsilon_m or horizontal_distance <= epsilon_m:
            return None
        step_m = min(self.sample_step_m, self.environment_case.heightmap.grid.cell_size_m / 2.0)
        sample_count = max(1, int(np.ceil(horizontal_distance / step_m)))
        horizontal_samples = np.linspace(
            step_m, horizontal_distance - step_m, sample_count - 1
        )
        if not len(horizontal_samples):
            return None
        fractions = horizontal_samples / horizontal_distance
        x_m = origin[0] + direction[0] * fractions
        y_m = origin[1] + direction[1] * fractions
        ray_z_m = origin[2] + direction[2] * fractions
        try:
            terrain_z_m = self._surface_elevations(x_m, y_m)
        except IndexError:
            return None
        blocked = np.flatnonzero(terrain_z_m >= ray_z_m - epsilon_m)
        if len(blocked):
            return distance * float(fractions[blocked[0]])
        return None

    def _obstacle_hit_distance(
        self,
        origin: np.ndarray,
        target: np.ndarray,
        *,
        epsilon_m: float,
    ) -> tuple[float | None, OcclusionKind]:
        if self._tree is None:
            return None, OcclusionKind.NONE
        direction = target - origin
        total_distance = float(np.linalg.norm(direction))
        horizontal_distance = hypot(float(direction[0]), float(direction[1]))
        if horizontal_distance <= epsilon_m:
            return None, OcclusionKind.NONE
        line = LineString(((float(origin[0]), float(origin[1])), (float(target[0]), float(target[1]))))
        nearest_distance = None
        nearest_kind = OcclusionKind.NONE
        for obstacle_index in self._tree.query(line):
            obstacle = self._obstacles[int(obstacle_index)]
            intersection = line.intersection(obstacle.geometry)
            for segment in _intersection_lines(intersection):
                projected = [line.project(Point(coordinate)) for coordinate in segment.coords]
                start_m, stop_m = min(projected), max(projected)
                start_m = max(start_m, epsilon_m)
                stop_m = min(stop_m, horizontal_distance - epsilon_m)
                if stop_m <= start_m:
                    continue
                length_m = stop_m - start_m
                sample_count = max(2, int(np.ceil(length_m / self.sample_step_m)) + 1)
                horizontal_samples = np.linspace(start_m, stop_m, sample_count)
                fractions = horizontal_samples / horizontal_distance
                x_m = origin[0] + direction[0] * fractions
                y_m = origin[1] + direction[1] * fractions
                ray_z_m = origin[2] + direction[2] * fractions
                base_z_m = (
                    self._surface_elevations(x_m, y_m)
                    if obstacle.follow_terrain
                    else np.full(len(fractions), float(obstacle.base_z_m))
                )
                blocked = np.flatnonzero(
                    (base_z_m - epsilon_m <= ray_z_m)
                    & (ray_z_m <= base_z_m + obstacle.height_m + epsilon_m)
                )
                if len(blocked):
                    hit_distance = total_distance * float(fractions[blocked[0]])
                    if nearest_distance is None or hit_distance < nearest_distance:
                        nearest_distance = hit_distance
                        nearest_kind = obstacle.kind
        return nearest_distance, nearest_kind

    def first_occlusion(
        self,
        origin_xyz: np.ndarray,
        target_xyz: np.ndarray,
        *,
        epsilon_m: float = 0.05,
    ) -> RayOcclusion:
        origin = np.asarray(origin_xyz, dtype=np.float64)
        target = np.asarray(target_xyz, dtype=np.float64)
        if origin.shape != (3,) or target.shape != (3,):
            raise ValueError("ray origin and target must have shape (3,)")
        if not np.isfinite(origin).all() or not np.isfinite(target).all():
            raise ValueError("ray coordinates must be finite")
        terrain_distance = self._terrain_hit_distance(origin, target, epsilon_m=epsilon_m)
        obstacle_distance, obstacle_kind = self._obstacle_hit_distance(
            origin, target, epsilon_m=epsilon_m
        )
        if terrain_distance is None and obstacle_distance is None:
            return RayOcclusion(OcclusionKind.NONE)
        if obstacle_distance is None or (
            terrain_distance is not None and terrain_distance <= obstacle_distance
        ):
            return RayOcclusion(OcclusionKind.TERRAIN, terrain_distance)
        return RayOcclusion(obstacle_kind, obstacle_distance)
