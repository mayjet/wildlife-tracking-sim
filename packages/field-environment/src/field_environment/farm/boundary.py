from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shapely.geometry import Polygon, box, mapping, shape
from shapely.geometry.base import BaseGeometry
from shepherd_contracts import AxisAlignedBounds2D


@dataclass(frozen=True)
class FarmBoundary:
    polygon: Polygon
    coordinate_system_name: str

    def __post_init__(self) -> None:
        if not isinstance(self.polygon, Polygon):
            raise TypeError("farm boundary must be a Polygon")
        if self.polygon.is_empty or not self.polygon.is_valid or self.polygon.area <= 0.0:
            raise ValueError("farm boundary must be a non-empty valid Polygon with positive area")
        if not self.coordinate_system_name:
            raise ValueError("coordinate_system_name is required")

    @classmethod
    def rectangle(
        cls,
        *,
        min_x_m: float,
        min_y_m: float,
        max_x_m: float,
        max_y_m: float,
        coordinate_system_name: str,
    ) -> "FarmBoundary":
        if max_x_m <= min_x_m or max_y_m <= min_y_m:
            raise ValueError("maximum boundary coordinates must exceed minimum coordinates")
        return cls(
            polygon=box(min_x_m, min_y_m, max_x_m, max_y_m),
            coordinate_system_name=coordinate_system_name,
        )

    @property
    def bounds(self) -> AxisAlignedBounds2D:
        min_x, min_y, max_x, max_y = self.polygon.bounds
        return AxisAlignedBounds2D(
            min_x_m=min_x,
            min_y_m=min_y,
            max_x_m=max_x,
            max_y_m=max_y,
        )

    def validate_within(self, terrain_bounds: AxisAlignedBounds2D) -> None:
        terrain_polygon = box(
            terrain_bounds.min_x_m,
            terrain_bounds.min_y_m,
            terrain_bounds.max_x_m,
            terrain_bounds.max_y_m,
        )
        if not terrain_polygon.covers(self.polygon):
            raise ValueError("farm boundary must be fully contained in the terrain extent")

    def to_geojson(self) -> dict[str, Any]:
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "role": "farm_boundary",
                        "coordinate_system": self.coordinate_system_name,
                    },
                    "geometry": mapping(self.polygon),
                }
            ],
        }

    @classmethod
    def from_geojson(cls, document: dict[str, Any]) -> "FarmBoundary":
        if document.get("type") != "FeatureCollection":
            raise ValueError("farm boundary GeoJSON must be a FeatureCollection")
        features = document.get("features")
        if not isinstance(features, list) or len(features) != 1:
            raise ValueError("farm boundary GeoJSON must contain exactly one feature")
        feature = features[0]
        geometry: BaseGeometry = shape(feature.get("geometry"))
        properties = feature.get("properties") or {}
        coordinate_system = properties.get("coordinate_system")
        if not isinstance(coordinate_system, str):
            raise ValueError("farm boundary feature requires coordinate_system")
        if not isinstance(geometry, Polygon):
            raise ValueError("farm boundary geometry must be a Polygon")
        return cls(polygon=geometry, coordinate_system_name=coordinate_system)

