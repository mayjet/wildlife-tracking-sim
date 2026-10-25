from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from shepherd_contracts import CaseSpec, JsonValue, Position2D

from ..farm.boundary import FarmBoundary
from ..environment_detection import RasterLayer
from ..features import PolygonFeatureLayer, TraversabilityMap
from ..terrain.heightmap import Heightmap
from ..terrain.quality import TerrainQuality


class TerrainMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    width_cells: int = Field(gt=0)
    height_cells: int = Field(gt=0)
    cell_size_m: float = Field(gt=0.0)
    origin: Position2D
    array_axis_order: Literal["YX"] = "YX"
    origin_is_cell_center: Literal[True] = True
    dtype: Literal["float32", "float64"]


class TerrainGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    method: Literal["flat", "hills", "valley", "ridge", "composite", "alos", "gsi", "file"]
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    seed: int
    source: str = "synthetic"


class TerrainProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    source: Literal["synthetic", "alos", "gsi", "file"]
    dataset: str
    elevation_type: str
    source_crs: str | None = None
    vertical_datum: str
    center_lat: float | None = None
    center_lon: float | None = None
    geographic_bounds: tuple[float, float, float, float] | None = None
    effective_resolution_m: float | None = Field(default=None, gt=0.0)
    output_cell_size_m: float = Field(gt=0.0)
    fill_method: str
    source_data_refs: tuple[str, ...] = ()
    attribution: str
    license_url: str | None = None


class FeatureLayerMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["unavailable", "empty", "available"]
    data_ref: str | None = None
    source: str | None = None
    assumed_height_m: float | None = None


class SourceArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_path: Path
    case_relative_path: str


class DetectionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    imagery_ref: str | None = None
    imagery_source: str | None = None
    imagery_attribution: str | None = None
    imagery_source_resolution_m: float | None = Field(default=None, gt=0.0)
    landcover_ref: str | None = None
    landcover_source: str | None = None
    landcover_attribution: str | None = None
    landcover_source_resolution_m: float | None = Field(default=None, gt=0.0)
    pasture_candidates_ref: str | None = None
    farm_complex_candidates_ref: str | None = None
    monitoring_area_ref: str | None = None
    facility_buildings_ref: str | None = None
    excluded_buildings_ref: str | None = None


class ProcessingStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    step_id: str = Field(min_length=1)
    status: Literal["completed", "skipped"]
    description: str = Field(min_length=1)
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    metrics: dict[str, JsonValue] = Field(default_factory=dict)


class CaseDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_version: Literal["1.0"] = "1.0"
    case: CaseSpec
    terrain: TerrainMetadata
    generation: TerrainGeneration
    provenance: TerrainProvenance | None = None
    quality: TerrainQuality | None = None
    feature_layers: dict[str, FeatureLayerMetadata] = Field(default_factory=dict)
    detection: DetectionMetadata | None = None
    input_config_digest: str | None = None
    history: tuple[dict[str, JsonValue], ...] = ()
    processing_steps: tuple[ProcessingStep, ...] = ()


@dataclass(frozen=True)
class EnvironmentCase:
    case_spec: CaseSpec
    heightmap: Heightmap
    farm_boundary: FarmBoundary
    generation: TerrainGeneration
    provenance: TerrainProvenance | None = None
    quality: TerrainQuality | None = None
    buildings: PolygonFeatureLayer | None = None
    forest: PolygonFeatureLayer | None = None
    traversability: TraversabilityMap | None = None
    imagery: RasterLayer | None = None
    landcover: RasterLayer | None = None
    pasture_candidates: PolygonFeatureLayer | None = None
    farm_complex_candidates: PolygonFeatureLayer | None = None
    monitoring_area: PolygonFeatureLayer | None = None
    facility_buildings: PolygonFeatureLayer | None = None
    excluded_buildings: PolygonFeatureLayer | None = None
    scene_crop: PolygonFeatureLayer | None = None
    input_config_digest: str | None = None
    history: tuple[dict[str, JsonValue], ...] = ()
    source_artifacts: tuple[SourceArtifact, ...] = ()
    processing_steps: tuple[ProcessingStep, ...] = ()

    @property
    def terrain_metadata(self) -> TerrainMetadata:
        return TerrainMetadata(
            width_cells=self.heightmap.grid.width_cells,
            height_cells=self.heightmap.grid.height_cells,
            cell_size_m=self.heightmap.grid.cell_size_m,
            origin=self.heightmap.grid.origin,
            dtype=str(self.heightmap.values.dtype),
        )

    @property
    def document(self) -> CaseDocument:
        feature_layers = {}
        for name, layer, filename in (
            ("buildings", self.buildings, "buildings.geojson"),
            ("forest", self.forest, "forest.geojson"),
            ("pasture_candidates", self.pasture_candidates, "pasture_candidates.geojson"),
            (
                "farm_complex_candidates",
                self.farm_complex_candidates,
                "farm_complex_candidates.geojson",
            ),
            ("monitoring_area", self.monitoring_area, "monitoring_area.geojson"),
            ("facility_buildings", self.facility_buildings, "facility_buildings.geojson"),
            ("excluded_buildings", self.excluded_buildings, "excluded_buildings.geojson"),
            ("scene_crop", self.scene_crop, "scene_crop.geojson"),
        ):
            if layer is not None:
                feature_layers[name] = FeatureLayerMetadata(
                    status=layer.status.value,
                    data_ref=filename if layer.status.value != "unavailable" else None,
                    source=layer.source,
                    assumed_height_m=layer.assumed_height_m,
                )
        detection = None
        if self.imagery is not None or self.landcover is not None or self.pasture_candidates is not None:
            detection = DetectionMetadata(
                imagery_ref="imagery_rgb.tif" if self.imagery is not None else None,
                imagery_source=self.imagery.source if self.imagery is not None else None,
                imagery_attribution=self.imagery.attribution if self.imagery is not None else None,
                imagery_source_resolution_m=(
                    self.imagery.source_resolution_m if self.imagery is not None else None
                ),
                landcover_ref="landcover.tif" if self.landcover is not None else None,
                landcover_source=self.landcover.source if self.landcover is not None else None,
                landcover_attribution=self.landcover.attribution if self.landcover is not None else None,
                landcover_source_resolution_m=(
                    self.landcover.source_resolution_m if self.landcover is not None else None
                ),
                pasture_candidates_ref=(
                    "pasture_candidates.geojson" if self.pasture_candidates is not None else None
                ),
                farm_complex_candidates_ref=(
                    "farm_complex_candidates.geojson"
                    if self.farm_complex_candidates is not None
                    else None
                ),
                monitoring_area_ref=(
                    "monitoring_area.geojson" if self.monitoring_area is not None else None
                ),
                facility_buildings_ref=(
                    "facility_buildings.geojson" if self.facility_buildings is not None else None
                ),
                excluded_buildings_ref=(
                    "excluded_buildings.geojson" if self.excluded_buildings is not None else None
                ),
            )
        return CaseDocument(
            case=self.case_spec,
            terrain=self.terrain_metadata,
            generation=self.generation,
            provenance=self.provenance,
            quality=self.quality,
            feature_layers=feature_layers,
            detection=detection,
            input_config_digest=self.input_config_digest,
            history=self.history,
            processing_steps=self.processing_steps,
        )
