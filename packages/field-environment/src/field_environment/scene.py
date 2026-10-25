from __future__ import annotations

from dataclasses import replace
from math import ceil, floor

import numpy as np
from shapely.geometry import box, mapping, shape

from .case.models import EnvironmentCase, ProcessingStep
from .config import SceneConfig, SceneCropConfig
from .features import FeatureLayerStatus, PolygonFeatureLayer
from .terrain.heightmap import Heightmap, TerrainGridSpec


def _snapped_bounds(environment_case: EnvironmentCase, config: SceneCropConfig):
    farm_min_x, farm_min_y, farm_max_x, farm_max_y = environment_case.farm_boundary.polygon.bounds
    farm_width = farm_max_x - farm_min_x
    farm_height = farm_max_y - farm_min_y
    if config.shape == "square":
        side = max(
            max(farm_width, farm_height) * config.scale,
            max(farm_width, farm_height) + 2.0 * config.minimum_margin_m,
        )
        width = height = side
    else:
        width = max(farm_width * config.scale, farm_width + 2.0 * config.minimum_margin_m)
        height = max(farm_height * config.scale, farm_height + 2.0 * config.minimum_margin_m)
    center_x = (farm_min_x + farm_max_x) * 0.5 + config.center_offset_x_m
    center_y = (farm_min_y + farm_max_y) * 0.5 + config.center_offset_y_m
    min_x, min_y = center_x - width * 0.5, center_y - height * 0.5
    max_x, max_y = center_x + width * 0.5, center_y + height * 0.5
    terrain = environment_case.heightmap.bounds
    if config.snap_to_terrain_grid:
        cell = environment_case.heightmap.grid.cell_size_m
        min_x = terrain.min_x_m + floor((min_x - terrain.min_x_m) / cell) * cell
        min_y = terrain.min_y_m + floor((min_y - terrain.min_y_m) / cell) * cell
        max_x = terrain.min_x_m + ceil((max_x - terrain.min_x_m) / cell) * cell
        max_y = terrain.min_y_m + ceil((max_y - terrain.min_y_m) / cell) * cell
    tolerance = environment_case.heightmap.grid.cell_size_m * 1.0e-9
    if (
        min_x < terrain.min_x_m - tolerance
        or min_y < terrain.min_y_m - tolerance
        or max_x > terrain.max_x_m + tolerance
        or max_y > terrain.max_y_m + tolerance
    ):
        raise ValueError("scene crop extends outside the acquired terrain; reduce scale or offset")
    return min_x, min_y, max_x, max_y


# 農場境界を囲む矩形を，3D生成に用いる実験領域として確定する．
def create_scene_crop(
    environment_case: EnvironmentCase,
    config: SceneCropConfig,
    *,
    forest_boundary_smoothing_m: float = 0.0,
) -> PolygonFeatureLayer | None:
    if not config.enabled:
        return None
    min_x, min_y, max_x, max_y = _snapped_bounds(environment_case, config)
    geometry = box(min_x, min_y, max_x, max_y)
    properties = {
        "role": "scene_crop",
        "source": config.source,
        "shape": config.shape,
        "scale": config.scale,
        "minimum_margin_m": config.minimum_margin_m,
        "center_offset_x_m": config.center_offset_x_m,
        "center_offset_y_m": config.center_offset_y_m,
        "width_m": max_x - min_x,
        "height_m": max_y - min_y,
        "horizontal_area_m2": geometry.area,
        "forest_boundary_smoothing_m": forest_boundary_smoothing_m,
    }
    return PolygonFeatureLayer(
        layer_type="scene_crop",
        status=FeatureLayerStatus.AVAILABLE,
        coordinate_system_name=environment_case.case_spec.coordinate_system.name,
        features=({"type": "Feature", "geometry": mapping(geometry), "properties": properties},),
        source="farm_boundary_derived_scene_crop",
    )


# 森林高さと3Dクロップ範囲をCaseへ記録する．
def apply_scene_config(environment_case: EnvironmentCase, config: SceneConfig) -> EnvironmentCase:
    scene_crop = create_scene_crop(
        environment_case,
        config.crop,
        forest_boundary_smoothing_m=config.forest_boundary_smoothing_m,
    )
    forest = environment_case.forest
    if forest is not None:
        forest = replace(forest, assumed_height_m=config.forest_height_m)
    metrics = {}
    if scene_crop is not None:
        properties = scene_crop.features[0]["properties"]
        metrics = {
            "width_m": properties["width_m"],
            "height_m": properties["height_m"],
            "horizontal_area_m2": properties["horizontal_area_m2"],
        }
    step = ProcessingStep(
        step_id="configure_scene",
        status="completed",
        description="3D出力用クロップ範囲と森林遮蔽高さを設定した",
        inputs=("farm_boundary.geojson", "forest.geojson"),
        outputs=(("scene_crop.geojson",) if scene_crop is not None else ()),
        parameters={
            "forest_height_m": config.forest_height_m,
            "forest_boundary_smoothing_m": config.forest_boundary_smoothing_m,
            "crop": config.crop.model_dump(mode="json"),
        },
        metrics=metrics,
    )
    return replace(
        environment_case,
        forest=forest,
        scene_crop=scene_crop,
        processing_steps=environment_case.processing_steps + (step,),
    )


def scene_crop_geometry(environment_case: EnvironmentCase):
    if environment_case.scene_crop is None or not environment_case.scene_crop.features:
        bounds = environment_case.heightmap.bounds
        return box(bounds.min_x_m, bounds.min_y_m, bounds.max_x_m, bounds.max_y_m)
    return shape(environment_case.scene_crop.features[0]["geometry"])


# 元の3 km標高を保持したまま，3D出力用の矩形Heightmapだけを切り出す．
def crop_heightmap(heightmap: Heightmap, crop_geometry) -> Heightmap:
    min_x, min_y, max_x, max_y = crop_geometry.bounds
    bounds = heightmap.bounds
    cell = heightmap.grid.cell_size_m
    x_start = int(round((min_x - bounds.min_x_m) / cell))
    y_start = int(round((min_y - bounds.min_y_m) / cell))
    x_stop = int(round((max_x - bounds.min_x_m) / cell))
    y_stop = int(round((max_y - bounds.min_y_m) / cell))
    if not (0 <= x_start < x_stop <= heightmap.grid.width_cells):
        raise ValueError("scene crop x bounds do not align with the Heightmap")
    if not (0 <= y_start < y_stop <= heightmap.grid.height_cells):
        raise ValueError("scene crop y bounds do not align with the Heightmap")
    values = np.asarray(heightmap.values[y_start:y_stop, x_start:x_stop])
    grid = TerrainGridSpec.from_extent(
        width_m=(x_stop - x_start) * cell,
        height_m=(y_stop - y_start) * cell,
        cell_size_m=cell,
        min_x_m=bounds.min_x_m + x_start * cell,
        min_y_m=bounds.min_y_m + y_start * cell,
    )
    return Heightmap(values=values, grid=grid)
