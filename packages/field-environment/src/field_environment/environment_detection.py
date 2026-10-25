from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from rasterio.features import shapes
from rasterio.transform import from_origin
from shapely.geometry import Point, mapping, shape

from .features import FeatureLayerStatus, PolygonFeatureLayer
from .terrain.heightmap import TerrainGridSpec
from .terrain.quality import slope_degrees


WORLD_COVER_CLASSES = {
    0: "no_data",
    10: "tree_cover",
    20: "shrubland",
    30: "grassland",
    40: "cropland",
    50: "built_up",
    60: "bare_sparse_vegetation",
    70: "snow_ice",
    80: "permanent_water",
    90: "herbaceous_wetland",
    95: "mangroves",
    100: "moss_lichen",
}


@dataclass(frozen=True)
class RasterLayer:
    layer_type: Literal["imagery", "landcover"]
    values: np.ndarray
    grid: TerrainGridSpec
    source: str
    attribution: str
    source_resolution_m: float | None = None

    def __post_init__(self) -> None:
        values = np.asarray(self.values)
        expected = (self.grid.height_cells, self.grid.width_cells)
        if self.layer_type == "imagery":
            if values.shape != expected + (3,):
                raise ValueError(f"imagery shape must be {expected + (3,)}")
            stored = np.asarray(values, dtype=np.uint8)
        else:
            if values.shape != expected:
                raise ValueError(f"landcover shape must be {expected}")
            unknown = set(np.unique(values)) - set(WORLD_COVER_CLASSES)
            if unknown:
                raise ValueError(f"unknown WorldCover classes: {sorted(unknown)}")
            stored = np.asarray(values, dtype=np.uint8)
        stored = np.array(stored, copy=True, order="C")
        stored.setflags(write=False)
        object.__setattr__(self, "values", stored)


def _mask_to_features(
    mask_south_up: np.ndarray,
    grid: TerrainGridSpec,
    *,
    minimum_area_m2: float,
    properties: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], ...]:
    transform_north_up = from_origin(
        grid.bounds.min_x_m,
        grid.bounds.max_y_m,
        grid.cell_size_m,
        grid.cell_size_m,
    )
    mask_north_up = np.asarray(mask_south_up, dtype=np.uint8)[::-1, :]
    features = []
    for geometry, value in shapes(
        mask_north_up,
        mask=mask_north_up.astype(bool),
        transform=transform_north_up,
    ):
        if value != 1:
            continue
        polygon = shape(geometry)
        if polygon.is_empty or not polygon.is_valid or polygon.area < minimum_area_m2:
            continue
        feature_properties = dict(properties or {})
        case_origin = Point(0.0, 0.0)
        feature_properties["area_m2"] = float(polygon.area)
        feature_properties["centroid_x_m"] = float(polygon.centroid.x)
        feature_properties["centroid_y_m"] = float(polygon.centroid.y)
        feature_properties["distance_to_case_origin_m"] = float(polygon.distance(case_origin))
        feature_properties["contains_case_origin"] = bool(polygon.covers(case_origin))
        features.append(
            {
                "type": "Feature",
                "geometry": mapping(polygon),
                "properties": feature_properties,
            }
        )
    return tuple(features)


# 土地被覆データから森林領域を抽出する．
def detect_forest(
    landcover: RasterLayer,
    *,
    coordinate_system_name: str,
    classes: tuple[int, ...] = (10, 95),
    minimum_area_m2: float = 100.0,
) -> PolygonFeatureLayer:
    if landcover.layer_type != "landcover":
        raise ValueError("forest detection requires a landcover raster")
    mask = np.isin(landcover.values, classes)
    features = _mask_to_features(
        mask,
        landcover.grid,
        minimum_area_m2=minimum_area_m2,
        properties={"worldcover_classes": list(classes)},
    )
    return PolygonFeatureLayer(
        layer_type="forest",
        status=FeatureLayerStatus.AVAILABLE if features else FeatureLayerStatus.EMPTY,
        coordinate_system_name=coordinate_system_name,
        features=features,
        source="ESA WorldCover 2021 v200",
        assumed_height_m=5.0,
    )


# 土地被覆，傾斜，建物から開放地候補を抽出する．
def detect_pasture_candidates(
    landcover: RasterLayer,
    elevations: np.ndarray,
    *,
    coordinate_system_name: str,
    buildings: PolygonFeatureLayer | None,
    open_classes: tuple[int, ...] = (30, 40, 60),
    maximum_slope_deg: float = 20.0,
    minimum_area_m2: float = 1000.0,
) -> PolygonFeatureLayer:
    from rasterio.features import rasterize

    if landcover.layer_type != "landcover":
        raise ValueError("pasture detection requires a landcover raster")
    if landcover.grid.width_cells != elevations.shape[1] or landcover.grid.height_cells != elevations.shape[0]:
        raise ValueError("landcover and elevation grids must have the same shape")
    candidate = np.isin(landcover.values, open_classes)
    candidate &= slope_degrees(elevations, landcover.grid.cell_size_m) <= maximum_slope_deg
    if buildings is not None and buildings.status is FeatureLayerStatus.AVAILABLE:
        transform_north_up = from_origin(
            landcover.grid.bounds.min_x_m,
            landcover.grid.bounds.max_y_m,
            landcover.grid.cell_size_m,
            landcover.grid.cell_size_m,
        )
        building_mask = rasterize(
            [(feature["geometry"], 1) for feature in buildings.features],
            out_shape=elevations.shape,
            transform=transform_north_up,
            fill=0,
            dtype="uint8",
        )[::-1, :]
        candidate &= building_mask == 0
    features = _mask_to_features(
        candidate,
        landcover.grid,
        minimum_area_m2=minimum_area_m2,
        properties={
            "worldcover_classes": list(open_classes),
            "maximum_slope_deg": maximum_slope_deg,
            "classification": "candidate_not_confirmed_property_boundary",
        },
    )
    return PolygonFeatureLayer(
        layer_type="pasture_candidates",
        status=FeatureLayerStatus.AVAILABLE if features else FeatureLayerStatus.EMPTY,
        coordinate_system_name=coordinate_system_name,
        features=features,
        source="ESA WorldCover and terrain slope; buildings excluded",
    )
