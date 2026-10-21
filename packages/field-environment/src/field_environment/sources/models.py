from __future__ import annotations

from dataclasses import dataclass

from shepherd_contracts import LocalCoordinateSystem

from ..case.models import SourceArtifact, TerrainGeneration, TerrainProvenance
from ..terrain.heightmap import Heightmap
from ..terrain.quality import TerrainQuality


@dataclass(frozen=True)
class TerrainSourceResult:
    heightmap: Heightmap
    coordinate_system: LocalCoordinateSystem
    generation: TerrainGeneration
    provenance: TerrainProvenance
    quality: TerrainQuality
    source_artifacts: tuple[SourceArtifact, ...] = ()
