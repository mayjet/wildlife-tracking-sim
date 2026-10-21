from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from shepherd_contracts import CaseSpec, JsonValue, Position2D

from ..farm.boundary import FarmBoundary
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


class CaseDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_version: Literal["1.0"] = "1.0"
    case: CaseSpec
    terrain: TerrainMetadata
    generation: TerrainGeneration
    provenance: TerrainProvenance | None = None
    quality: TerrainQuality | None = None
    feature_layers: dict[str, FeatureLayerMetadata] = Field(default_factory=dict)
    input_config_digest: str | None = None
    history: tuple[dict[str, JsonValue], ...] = ()


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
    input_config_digest: str | None = None
    history: tuple[dict[str, JsonValue], ...] = ()
    source_artifacts: tuple[SourceArtifact, ...] = ()

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
        ):
            if layer is not None:
                feature_layers[name] = FeatureLayerMetadata(
                    status=layer.status.value,
                    data_ref=filename if layer.status.value != "unavailable" else None,
                    source=layer.source,
                    assumed_height_m=layer.assumed_height_m,
                )
        return CaseDocument(
            case=self.case_spec,
            terrain=self.terrain_metadata,
            generation=self.generation,
            provenance=self.provenance,
            quality=self.quality,
            feature_layers=feature_layers,
            input_config_digest=self.input_config_digest,
            history=self.history,
        )
