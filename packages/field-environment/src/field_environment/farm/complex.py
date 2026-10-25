from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from rasterio.features import rasterize, shapes
from rasterio.transform import from_origin
from scipy import ndimage
from shapely.geometry import Point, Polygon, box, mapping, shape
from shapely.ops import unary_union

from ..features import FeatureLayerStatus, PolygonFeatureLayer
from ..terrain.heightmap import TerrainGridSpec


@dataclass(frozen=True)
class FarmComplexResult:
    candidates: PolygonFeatureLayer
    monitoring_area: PolygonFeatureLayer
    facility_buildings: PolygonFeatureLayer
    excluded_buildings: PolygonFeatureLayer
    selected_candidate_id: int | None
    metrics: dict[str, float | int | bool]


def _north_up_transform(grid: TerrainGridSpec):
    return from_origin(
        grid.bounds.min_x_m,
        grid.bounds.max_y_m,
        grid.cell_size_m,
        grid.cell_size_m,
    )


def _rasterize_layer(layer: PolygonFeatureLayer, grid: TerrainGridSpec) -> np.ndarray:
    if layer.status is not FeatureLayerStatus.AVAILABLE:
        return np.zeros((grid.height_cells, grid.width_cells), dtype=bool)
    north_up = rasterize(
        [(feature["geometry"], 1) for feature in layer.features],
        out_shape=(grid.height_cells, grid.width_cells),
        transform=_north_up_transform(grid),
        fill=0,
        dtype="uint8",
    )
    return north_up[::-1, :].astype(bool)


def _disk(radius_cells: int) -> np.ndarray:
    if radius_cells <= 0:
        return np.ones((1, 1), dtype=bool)
    coordinates = np.arange(-radius_cells, radius_cells + 1)
    y_coordinates, x_coordinates = np.meshgrid(coordinates, coordinates, indexing="ij")
    return x_coordinates**2 + y_coordinates**2 <= radius_cells**2


def _fill_small_holes(mask: np.ndarray, maximum_cells: int | None) -> np.ndarray:
    if maximum_cells is None:
        return ndimage.binary_fill_holes(mask)
    if maximum_cells <= 0:
        return mask
    holes = ndimage.binary_fill_holes(mask) & ~mask
    labels, count = ndimage.label(holes)
    result = mask.copy()
    for label_value in range(1, count + 1):
        region = labels == label_value
        if int(region.sum()) <= maximum_cells:
            result[region] = True
    return result


def _component_features(
    mask_south_up: np.ndarray,
    grid: TerrainGridSpec,
    *,
    minimum_area_m2: float,
    anchor: Point,
) -> tuple[dict, ...]:
    north_up = np.asarray(mask_south_up, dtype=np.uint8)[::-1, :]
    features = []
    for geometry, value in shapes(
        north_up,
        mask=north_up.astype(bool),
        transform=_north_up_transform(grid),
    ):
        if value != 1:
            continue
        polygon = shape(geometry)
        if polygon.is_empty or not polygon.is_valid or polygon.area < minimum_area_m2:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": mapping(polygon),
                "properties": {
                    "area_m2": float(polygon.area),
                    "distance_to_selection_anchor_m": float(polygon.distance(anchor)),
                    "contains_selection_anchor": bool(polygon.covers(anchor)),
                },
            }
        )
    features.sort(
        key=lambda feature: (
            not feature["properties"]["contains_selection_anchor"],
            feature["properties"]["distance_to_selection_anchor_m"],
            -feature["properties"]["area_m2"],
        )
    )
    for candidate_id, feature in enumerate(features, start=1):
        feature["properties"]["candidate_id"] = candidate_id
    return tuple(features)


def _building_partition(
    buildings: PolygonFeatureLayer | None,
    selected_geometry,
    *,
    coordinate_system_name: str,
    maximum_distance_m: float,
) -> tuple[PolygonFeatureLayer, PolygonFeatureLayer]:
    facility_features = []
    excluded_features = []
    if buildings is not None and buildings.status is FeatureLayerStatus.AVAILABLE:
        for feature in buildings.features:
            geometry = shape(feature["geometry"])
            properties = dict(feature.get("properties") or {})
            distance = float(geometry.distance(selected_geometry))
            properties["distance_to_selected_farm_complex_m"] = distance
            output = {
                "type": "Feature",
                "geometry": feature["geometry"],
                "properties": properties,
            }
            if distance <= maximum_distance_m:
                properties["farm_membership"] = "facility_candidate"
                facility_features.append(output)
            else:
                properties["farm_membership"] = "excluded"
                excluded_features.append(output)

    def create_layer(layer_type: str, values: list[dict]) -> PolygonFeatureLayer:
        return PolygonFeatureLayer(
            layer_type=layer_type,
            status=(FeatureLayerStatus.AVAILABLE if values else FeatureLayerStatus.EMPTY),
            coordinate_system_name=coordinate_system_name,
            features=tuple(values),
            source="acquired buildings partitioned by selected farm complex",
            assumed_height_m=buildings.assumed_height_m if buildings is not None else None,
        )

    return (
        create_layer("facility_buildings", facility_features),
        create_layer("excluded_buildings", excluded_features),
    )


# 開放地の連続性から牧場候補となる土地の塊を抽出する．
def detect_farm_complexes(
    pasture_candidates: PolygonFeatureLayer,
    grid: TerrainGridSpec,
    *,
    coordinate_system_name: str,
    buildings: PolygonFeatureLayer | None,
    anchor_x_m: float = 0.0,
    anchor_y_m: float = 0.0,
    bridge_gap_m: float = 40.0,
    enclosed_hole_maximum_area_m2: float | None = None,
    facility_maximum_distance_m: float = 40.0,
    monitoring_closing_m: float = 80.0,
    monitoring_buffer_m: float = 10.0,
    minimum_area_m2: float = 1000.0,
) -> FarmComplexResult:
    open_mask = _rasterize_layer(pasture_candidates, grid)
    radius_cells = int(np.ceil(bridge_gap_m / grid.cell_size_m))
    connected_mask = ndimage.binary_closing(open_mask, structure=_disk(radius_cells))
    maximum_hole_cells = (
        None
        if enclosed_hole_maximum_area_m2 is None
        else int(np.floor(enclosed_hole_maximum_area_m2 / grid.cell_size_m**2))
    )
    connected_mask = _fill_small_holes(connected_mask, maximum_hole_cells)
    anchor = Point(anchor_x_m, anchor_y_m)
    candidate_features = _component_features(
        connected_mask,
        grid,
        minimum_area_m2=minimum_area_m2,
        anchor=anchor,
    )
    candidates = PolygonFeatureLayer(
        layer_type="farm_complex_candidates",
        status=(
            FeatureLayerStatus.AVAILABLE if candidate_features else FeatureLayerStatus.EMPTY
        ),
        coordinate_system_name=coordinate_system_name,
        features=candidate_features,
        source="connected open-land components with narrow gaps and enclosed holes bridged",
    )
    if not candidate_features:
        empty = PolygonFeatureLayer(
            layer_type="monitoring_area",
            status=FeatureLayerStatus.EMPTY,
            coordinate_system_name=coordinate_system_name,
            source="no farm complex candidate selected",
        )
        facility, excluded = _building_partition(
            buildings,
            box(0, 0, 0, 0),
            coordinate_system_name=coordinate_system_name,
            maximum_distance_m=-1.0,
        )
        return FarmComplexResult(
            candidates=candidates,
            monitoring_area=empty,
            facility_buildings=facility,
            excluded_buildings=excluded,
            selected_candidate_id=None,
            metrics={"candidate_count": 0, "selected": False},
        )

    selected_feature = candidate_features[0]
    selected_geometry = shape(selected_feature["geometry"])
    facility, excluded = _building_partition(
        buildings,
        selected_geometry,
        coordinate_system_name=coordinate_system_name,
        maximum_distance_m=facility_maximum_distance_m,
    )
    geometries = [selected_geometry]
    if facility.status is FeatureLayerStatus.AVAILABLE:
        geometries.extend(
            shape(feature["geometry"]).buffer(monitoring_buffer_m)
            for feature in facility.features
        )
    terrain_geometry = box(
        grid.bounds.min_x_m,
        grid.bounds.min_y_m,
        grid.bounds.max_x_m,
        grid.bounds.max_y_m,
    )
    monitoring_geometry = unary_union(geometries)
    if monitoring_closing_m > 0.0:
        monitoring_geometry = monitoring_geometry.buffer(monitoring_closing_m).buffer(
            -monitoring_closing_m
        )
    monitoring_geometry = monitoring_geometry.buffer(monitoring_buffer_m).intersection(
        terrain_geometry
    )
    if monitoring_geometry.geom_type == "MultiPolygon":
        monitoring_geometry = max(monitoring_geometry.geoms, key=lambda geometry: geometry.area)
    if monitoring_geometry.geom_type == "Polygon" and monitoring_geometry.interiors:
        monitoring_geometry = Polygon(monitoring_geometry.exterior)
    monitoring_feature = {
        "type": "Feature",
        "geometry": mapping(monitoring_geometry),
        "properties": {
            "role": "experimental_monitoring_area_candidate",
            "selected_candidate_id": selected_feature["properties"]["candidate_id"],
            "area_m2": float(monitoring_geometry.area),
            "legal_property_boundary": False,
        },
    }
    monitoring_area = PolygonFeatureLayer(
        layer_type="monitoring_area",
        status=FeatureLayerStatus.AVAILABLE,
        coordinate_system_name=coordinate_system_name,
        features=(monitoring_feature,),
        source="selected farm complex plus associated facility buildings",
    )
    return FarmComplexResult(
        candidates=candidates,
        monitoring_area=monitoring_area,
        facility_buildings=facility,
        excluded_buildings=excluded,
        selected_candidate_id=int(selected_feature["properties"]["candidate_id"]),
        metrics={
            "candidate_count": len(candidate_features),
            "selected": True,
            "selected_candidate_id": int(selected_feature["properties"]["candidate_id"]),
            "selected_open_area_m2": float(selected_geometry.area),
            "monitoring_area_m2": float(monitoring_geometry.area),
            "facility_building_count": len(facility.features),
            "excluded_building_count": len(excluded.features),
            "bridge_gap_m": bridge_gap_m,
            "monitoring_closing_m": monitoring_closing_m,
            "filled_hole_limit_m2": (
                "all_enclosed_holes"
                if enclosed_hole_maximum_area_m2 is None
                else enclosed_hole_maximum_area_m2
            ),
        },
    )


# 選択済みの監視候補をCaseの牧場境界へ変換する．
def build_monitoring_boundary(
    monitoring_area: PolygonFeatureLayer,
) -> "FarmBoundary":
    from .boundary import FarmBoundary

    if monitoring_area.status is not FeatureLayerStatus.AVAILABLE:
        raise ValueError("monitoring area is unavailable")
    if len(monitoring_area.features) != 1:
        raise ValueError("monitoring area must contain exactly one selected Polygon")
    geometry = shape(monitoring_area.features[0]["geometry"])
    if geometry.geom_type != "Polygon":
        raise ValueError("monitoring area must be a Polygon")
    return FarmBoundary(
        polygon=geometry,
        coordinate_system_name=monitoring_area.coordinate_system_name,
    )
