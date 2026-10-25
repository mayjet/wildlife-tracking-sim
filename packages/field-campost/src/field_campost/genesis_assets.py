from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

import numpy as np
from field_environment import (
    EnvironmentCase,
    FeatureLayerStatus,
    crop_heightmap,
    scene_crop_geometry,
)

from .mesh import heightmap_to_mesh
from .prisms import iter_layer_polygons, iter_polygons, layer_union, polygon_to_prism_mesh


@dataclass(frozen=True)
class GenesisMeshAssets:
    terrain: Path
    forest: Path | None
    buildings: Path | None
    facility_buildings: Path | None = None


def _write_vertices(stream: TextIO, vertices: np.ndarray) -> None:
    for x_m, y_m, z_m in vertices:
        stream.write(f"v {float(x_m):.9g} {float(y_m):.9g} {float(z_m):.9g}\n")


def _write_terrain_obj(heightmap, destination: Path) -> None:
    mesh = heightmap_to_mesh(heightmap)
    with destination.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("o terrain\n")
        _write_vertices(stream, mesh.vertices)
        for first, second, third in mesh.faces + 1:
            stream.write(f"f {int(first)} {int(second)} {int(third)}\n")


def _sample_surface(heightmap, coordinates: np.ndarray) -> np.ndarray:
    min_x_m = heightmap.grid.origin.x_m
    min_y_m = heightmap.grid.origin.y_m
    max_x_m = min_x_m + (heightmap.grid.width_cells - 1) * heightmap.grid.cell_size_m
    max_y_m = min_y_m + (heightmap.grid.height_cells - 1) * heightmap.grid.cell_size_m
    elevations = []
    for x_m, y_m in coordinates:
        sample_x_m = min(max(float(x_m), min_x_m), max_x_m)
        sample_y_m = min(max(float(y_m), min_y_m), max_y_m)
        elevations.append(heightmap.surface_elevation_at(sample_x_m, sample_y_m))
    return np.asarray(elevations, dtype=np.float64)


def _write_layer_obj(
    heightmap,
    layer,
    destination: Path,
    *,
    default_height_m: float | None,
    follow_terrain: bool,
    subtract=None,
    clip=None,
    geometry_override=None,
) -> Path | None:
    if layer is None or layer.status is not FeatureLayerStatus.AVAILABLE:
        destination.unlink(missing_ok=True)
        return None
    vertex_offset = 1
    written_polygons = 0
    with destination.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(f"o {layer.layer_type}\n")
        polygon_source = (
            ((polygon, {}) for polygon in iter_polygons(geometry_override))
            if geometry_override is not None
            else iter_layer_polygons(layer, subtract=subtract, clip=clip)
        )
        for polygon, properties in polygon_source:
            height_m = (
                properties.get("height_m")
                or properties.get("assumed_height_m")
                or layer.assumed_height_m
                or default_height_m
            )
            if height_m is None:
                continue
            if follow_terrain:
                ground_elevation = lambda coordinates: _sample_surface(
                    heightmap, coordinates
                )
            else:
                representative = polygon.representative_point()
                ground_z = _sample_surface(
                    heightmap,
                    np.asarray([[representative.x, representative.y]], dtype=np.float64),
                )[0]
                ground_elevation = lambda coordinates, value=ground_z: np.full(
                    len(coordinates), value, dtype=np.float64
                )
            prism = polygon_to_prism_mesh(
                polygon,
                ground_elevation=ground_elevation,
                height_m=float(height_m),
                max_triangle_edge_m=(
                    heightmap.grid.cell_size_m * 2.0
                    if follow_terrain
                    else None
                ),
            )
            _write_vertices(stream, prism.vertices)
            for first, second, third in prism.faces + vertex_offset:
                stream.write(f"f {int(first)} {int(second)} {int(third)}\n")
            vertex_offset += len(prism.vertices)
            written_polygons += 1
    if written_polygons == 0:
        destination.unlink(missing_ok=True)
        return None
    return destination


# CaseからGenesis表示専用の地形・森林・建物Meshを生成する．
def write_genesis_mesh_assets(
    environment_case: EnvironmentCase,
    directory: str | Path,
) -> GenesisMeshAssets:
    destination = Path(directory).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    crop_geometry = scene_crop_geometry(environment_case)
    cropped_heightmap = crop_heightmap(environment_case.heightmap, crop_geometry)
    terrain_path = destination / "terrain.obj"
    forest_path = destination / "forest.obj"
    buildings_path = destination / "buildings.obj"
    facility_buildings_path = destination / "facility_buildings.obj"
    _write_terrain_obj(cropped_heightmap, terrain_path)
    building_footprints = layer_union(environment_case.buildings).intersection(crop_geometry)
    facility_footprints = layer_union(environment_case.facility_buildings).intersection(crop_geometry)
    forest_geometry = layer_union(environment_case.forest).intersection(crop_geometry)
    forest_geometry = forest_geometry.difference(building_footprints)
    smoothing_m = 0.0
    if environment_case.scene_crop is not None and environment_case.scene_crop.features:
        smoothing_m = float(
            environment_case.scene_crop.features[0].get("properties", {}).get(
                "forest_boundary_smoothing_m", 0.0
            )
        )
    if smoothing_m > 0.0 and not forest_geometry.is_empty:
        half = smoothing_m * 0.5
        forest_geometry = forest_geometry.buffer(half, join_style=2).buffer(-half, join_style=2)
        forest_geometry = forest_geometry.simplify(half, preserve_topology=True)
    forest_result = _write_layer_obj(
        cropped_heightmap,
        environment_case.forest,
        forest_path,
        default_height_m=10.0,
        follow_terrain=True,
        geometry_override=forest_geometry,
    )
    buildings_result = _write_layer_obj(
        cropped_heightmap,
        environment_case.buildings,
        buildings_path,
        default_height_m=5.0,
        follow_terrain=False,
        subtract=facility_footprints,
        clip=crop_geometry,
    )
    facility_buildings_result = _write_layer_obj(
        cropped_heightmap,
        environment_case.facility_buildings,
        facility_buildings_path,
        default_height_m=5.0,
        follow_terrain=False,
        clip=crop_geometry,
    )
    return GenesisMeshAssets(
        terrain=terrain_path,
        forest=forest_result,
        buildings=buildings_result,
        facility_buildings=facility_buildings_result,
    )
