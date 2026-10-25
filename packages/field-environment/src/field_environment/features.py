from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pyproj import Transformer
from rasterio.features import rasterize
from rasterio.transform import from_origin
from shapely.geometry import mapping, shape
from shapely.ops import transform

from shepherd_contracts import LocalCoordinateSystem

from .terrain.heightmap import TerrainGridSpec
from .terrain.quality import slope_degrees


FeatureLayerType = Literal[
    "buildings",
    "forest",
    "pasture_candidates",
    "farm_complex_candidates",
    "monitoring_area",
    "facility_buildings",
    "excluded_buildings",
    "scene_crop",
]


class FeatureLayerStatus(str, Enum):
    UNAVAILABLE = "unavailable"
    EMPTY = "empty"
    AVAILABLE = "available"


@dataclass(frozen=True)
class PolygonFeatureLayer:
    layer_type: FeatureLayerType
    status: FeatureLayerStatus
    coordinate_system_name: str
    features: tuple[dict[str, Any], ...] = ()
    source: str | None = None
    assumed_height_m: float | None = None

    def __post_init__(self) -> None:
        if self.status is FeatureLayerStatus.AVAILABLE and not self.features:
            raise ValueError("available feature layers must contain at least one feature")
        if self.status is not FeatureLayerStatus.AVAILABLE and self.features:
            raise ValueError("only available feature layers may contain features")
        for feature in self.features:
            geometry = shape(feature.get("geometry"))
            if geometry.geom_type not in {"Polygon", "MultiPolygon"} or not geometry.is_valid:
                raise ValueError("feature geometries must be valid Polygon or MultiPolygon values")

    def to_geojson(self) -> dict[str, Any]:
        return {
            "type": "FeatureCollection",
            "coordinate_system_name": self.coordinate_system_name,
            "layer_type": self.layer_type,
            "status": self.status.value,
            "source": self.source,
            "assumed_height_m": self.assumed_height_m,
            "features": list(self.features),
        }

    @classmethod
    def from_geojson(cls, document: dict[str, Any]) -> "PolygonFeatureLayer":
        if document.get("type") != "FeatureCollection":
            raise ValueError("feature layer must be a GeoJSON FeatureCollection")
        return cls(
            layer_type=document["layer_type"],
            status=FeatureLayerStatus(document["status"]),
            coordinate_system_name=document["coordinate_system_name"],
            features=tuple(document.get("features", ())),
            source=document.get("source"),
            assumed_height_m=document.get("assumed_height_m"),
        )

    def covers(self, x_m: float, y_m: float) -> bool:
        from shapely.geometry import Point

        point = Point(x_m, y_m)
        return any(shape(feature["geometry"]).covers(point) for feature in self.features)


class TraversabilityValue(IntEnum):
    UNKNOWN = 0
    TRAVERSABLE = 1
    DIFFICULT = 2
    PROHIBITED = 3


@dataclass(frozen=True)
class TraversabilityMap:
    values: np.ndarray
    grid: TerrainGridSpec
    difficult_slope_deg: float | None

    def __post_init__(self) -> None:
        values = np.asarray(self.values, dtype=np.uint8)
        expected = (self.grid.height_cells, self.grid.width_cells)
        if values.shape != expected:
            raise ValueError(f"traversability shape must be {expected}")
        allowed = {value.value for value in TraversabilityValue}
        if not set(np.unique(values)).issubset(allowed):
            raise ValueError("traversability contains an unknown category")
        stored = np.array(values, copy=True, order="C")
        stored.setflags(write=False)
        object.__setattr__(self, "values", stored)


def load_polygon_feature_layer(
    path: str | Path,
    *,
    layer_type: FeatureLayerType,
    coordinate_system: LocalCoordinateSystem,
    source: str | None = None,
    assumed_height_m: float | None = None,
) -> PolygonFeatureLayer:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("type") != "FeatureCollection":
        raise ValueError("input feature data must be a GeoJSON FeatureCollection")
    input_name = document.get("coordinate_system_name")
    crs_name = ((document.get("crs") or {}).get("properties") or {}).get("name")
    transformer = None
    if input_name == coordinate_system.name:
        pass
    elif crs_name and "4326" in crs_name:
        if coordinate_system.projected_crs is None:
            raise ValueError("Case has no projected CRS for geographic feature conversion")
        transformer = Transformer.from_crs(
            "EPSG:4326", coordinate_system.projected_crs, always_xy=True
        )
    else:
        raise ValueError(
            "feature GeoJSON must declare the Case coordinate_system_name or EPSG:4326 CRS"
        )

    features = []
    for raw_feature in document.get("features", []):
        geometry = shape(raw_feature.get("geometry"))
        if transformer is not None:
            geometry = transform(transformer.transform, geometry)
        properties = dict(raw_feature.get("properties") or {})
        if layer_type == "buildings" and "height_m" not in properties:
            properties["height_m"] = None
            if assumed_height_m is not None:
                properties["assumed_height_m"] = assumed_height_m
        features.append(
            {"type": "Feature", "geometry": mapping(geometry), "properties": properties}
        )
    status = FeatureLayerStatus.AVAILABLE if features else FeatureLayerStatus.EMPTY
    return PolygonFeatureLayer(
        layer_type=layer_type,
        status=status,
        coordinate_system_name=coordinate_system.name,
        features=tuple(features),
        source=source or str(path),
        assumed_height_m=assumed_height_m,
    )


def create_feature_layer(
    *,
    layer_type: FeatureLayerType,
    status: FeatureLayerStatus,
    coordinate_system_name: str,
    source: str | None = None,
    assumed_height_m: float | None = None,
) -> PolygonFeatureLayer:
    return PolygonFeatureLayer(
        layer_type=layer_type,
        status=status,
        coordinate_system_name=coordinate_system_name,
        source=source,
        assumed_height_m=assumed_height_m,
    )


def generate_traversability(
    elevations: np.ndarray,
    grid: TerrainGridSpec,
    *,
    buildings: PolygonFeatureLayer | None,
    forest: PolygonFeatureLayer | None,
    difficult_slope_deg: float | None,
) -> TraversabilityMap:
    values = np.full(elevations.shape, TraversabilityValue.UNKNOWN, dtype=np.uint8)
    transform_north_up = from_origin(
        grid.bounds.min_x_m,
        grid.bounds.max_y_m,
        grid.cell_size_m,
        grid.cell_size_m,
    )
    if forest is not None and forest.status is FeatureLayerStatus.AVAILABLE:
        mask = rasterize(
            [(feature["geometry"], 1) for feature in forest.features],
            out_shape=elevations.shape,
            transform=transform_north_up,
            fill=0,
            dtype="uint8",
        )[::-1, :]
        values[mask == 1] = TraversabilityValue.TRAVERSABLE
    if difficult_slope_deg is not None:
        slopes = slope_degrees(elevations, grid.cell_size_m)
        values[slopes >= difficult_slope_deg] = TraversabilityValue.DIFFICULT
    if buildings is not None and buildings.status is FeatureLayerStatus.AVAILABLE:
        mask = rasterize(
            [(feature["geometry"], 1) for feature in buildings.features],
            out_shape=elevations.shape,
            transform=transform_north_up,
            fill=0,
            dtype="uint8",
        )[::-1, :]
        values[mask == 1] = TraversabilityValue.PROHIBITED
    return TraversabilityMap(
        values=values,
        grid=grid,
        difficult_slope_deg=difficult_slope_deg,
    )
