from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio
import yaml

from ..farm.boundary import FarmBoundary
from ..features import PolygonFeatureLayer, TraversabilityMap
from ..terrain.heightmap import Heightmap, TerrainGridSpec
from .models import CaseDocument, EnvironmentCase
from .validator import validate_case_directory, validate_environment_case
from .writer import resolve_case_path


def _read_heightmap(path: Path, document: CaseDocument) -> Heightmap:
    metadata = document.terrain
    with rasterio.open(path) as dataset:
        if dataset.count != 1:
            raise ValueError("terrain GeoTIFF must contain exactly one band")
        if dataset.transform.b != 0.0 or dataset.transform.d != 0.0:
            raise ValueError("rotated or skewed terrain GeoTIFF is not supported")
        if not np.isclose(dataset.transform.a, metadata.cell_size_m):
            raise ValueError("GeoTIFF x cell size does not match case.yaml")
        if not np.isclose(-dataset.transform.e, metadata.cell_size_m):
            raise ValueError("GeoTIFF y cell size does not match case.yaml")
        if dataset.width != metadata.width_cells or dataset.height != metadata.height_cells:
            raise ValueError("GeoTIFF shape does not match case.yaml")
        expected_left = metadata.origin.x_m - metadata.cell_size_m / 2.0
        expected_top = (
            metadata.origin.y_m
            - metadata.cell_size_m / 2.0
            + metadata.height_cells * metadata.cell_size_m
        )
        if not np.isclose(dataset.transform.c, expected_left):
            raise ValueError("GeoTIFF x origin does not match case.yaml")
        if not np.isclose(dataset.transform.f, expected_top):
            raise ValueError("GeoTIFF y origin does not match case.yaml")
        if dataset.dtypes[0] != metadata.dtype:
            raise ValueError("GeoTIFF dtype does not match case.yaml")
        values = dataset.read(1)[::-1, :]
    grid = TerrainGridSpec(
        width_cells=metadata.width_cells,
        height_cells=metadata.height_cells,
        cell_size_m=metadata.cell_size_m,
        origin=metadata.origin,
    )
    return Heightmap(values=values.astype(metadata.dtype), grid=grid)


def load_case(cases_root: str | Path, case_id: str) -> EnvironmentCase:
    case_directory = resolve_case_path(cases_root, case_id)
    validate_case_directory(case_directory)
    raw_document = yaml.safe_load((case_directory / "case.yaml").read_text(encoding="utf-8"))
    document = CaseDocument.model_validate(raw_document)
    if document.case.case_id != case_id:
        raise ValueError("requested case_id does not match case.yaml")
    heightmap = _read_heightmap(case_directory / "terrain.tif", document)
    boundary_document = json.loads(
        (case_directory / "farm_boundary.geojson").read_text(encoding="utf-8")
    )
    boundary = FarmBoundary.from_geojson(boundary_document)
    feature_layers = {}
    for name, filename in (("buildings", "buildings.geojson"), ("forest", "forest.geojson")):
        metadata = document.feature_layers.get(name)
        if metadata is None:
            feature_layers[name] = None
        elif metadata.status == "unavailable":
            from ..features import create_feature_layer, FeatureLayerStatus

            feature_layers[name] = create_feature_layer(
                layer_type=name,
                status=FeatureLayerStatus.UNAVAILABLE,
                coordinate_system_name=document.case.coordinate_system.name,
                source=metadata.source,
                assumed_height_m=metadata.assumed_height_m,
            )
        else:
            layer_document = json.loads((case_directory / filename).read_text(encoding="utf-8"))
            feature_layers[name] = PolygonFeatureLayer.from_geojson(layer_document)
    traversability = None
    traversability_path = case_directory / "traversability.tif"
    if traversability_path.is_file():
        with rasterio.open(traversability_path) as dataset:
            values = dataset.read(1)[::-1, :]
            difficult_tag = dataset.tags().get("difficult_slope_deg")
        traversability = TraversabilityMap(
            values=values,
            grid=heightmap.grid,
            difficult_slope_deg=(
                None if difficult_tag in (None, "unset") else float(difficult_tag)
            ),
        )
    environment_case = EnvironmentCase(
        case_spec=document.case,
        heightmap=heightmap,
        farm_boundary=boundary,
        generation=document.generation,
        provenance=document.provenance,
        quality=document.quality,
        buildings=feature_layers["buildings"],
        forest=feature_layers["forest"],
        traversability=traversability,
        input_config_digest=document.input_config_digest,
        history=document.history,
    )
    validate_environment_case(environment_case)
    if environment_case.terrain_metadata != document.terrain:
        raise ValueError("loaded Heightmap metadata does not match case.yaml")
    return environment_case
