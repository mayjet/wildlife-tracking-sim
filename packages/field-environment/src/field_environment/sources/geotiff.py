from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.warp import transform_bounds

from ..case.models import SourceArtifact, TerrainGeneration, TerrainProvenance
from ..config import FileTerrainConfig
from ..errors import TerrainDataUnavailableError
from ..repository import resolve_repository_path
from ..terrain.geospatial import create_local_geographic_frame, local_coordinate_system
from ..terrain.heightmap import Heightmap
from ..terrain.quality import calculate_terrain_quality, fill_missing_elevations
from .common import reproject_geographic_raster_to_centered_grid
from .models import TerrainSourceResult


def import_geotiff(
    config: FileTerrainConfig,
    *,
    case_id: str,
    working_directory: str | Path,
    repository_start: str | Path | None = None,
) -> TerrainSourceResult:
    source_path = resolve_repository_path(config.path, start=repository_start)
    if not source_path.is_file():
        raise TerrainDataUnavailableError(f"GeoTIFF not found: {source_path}")
    with rasterio.open(source_path) as dataset:
        if dataset.count != 1:
            raise ValueError("input GeoTIFF must contain exactly one elevation band")
        if dataset.crs is None:
            raise ValueError("input GeoTIFF must declare a CRS")
        geographic_bounds = transform_bounds(dataset.crs, "EPSG:4326", *dataset.bounds)
        center_lon = (geographic_bounds[0] + geographic_bounds[2]) / 2.0
        center_lat = (geographic_bounds[1] + geographic_bounds[3]) / 2.0
        frame = create_local_geographic_frame(center_lat, center_lon)
        local_bounds = transform_bounds(dataset.crs, frame.crs, *dataset.bounds)
        source_values = dataset.read(1).astype(np.float32)
        source_transform = dataset.transform
        source_crs = dataset.crs
        source_nodata = dataset.nodata
        if config.cell_size_m is not None:
            cell_size_m = config.cell_size_m
        elif dataset.crs.is_projected:
            cell_size_m = float(max(abs(dataset.transform.a), abs(dataset.transform.e)))
        else:
            cell_size_m = 30.0
    size_m = config.size_m or max(
        local_bounds[2] - local_bounds[0], local_bounds[3] - local_bounds[1]
    )
    size_m = np.ceil(size_m / cell_size_m) * cell_size_m
    projected_values, grid = reproject_geographic_raster_to_centered_grid(
        source_values,
        source_transform=source_transform,
        source_crs=source_crs,
        frame=frame,
        size_m=float(size_m),
        cell_size_m=float(cell_size_m),
        source_nodata=source_nodata,
    )
    filled_values, missing_fraction = fill_missing_elevations(
        projected_values, config.missing_data
    )
    heightmap = Heightmap(values=filled_values.astype(np.float32), grid=grid)
    quality = calculate_terrain_quality(
        heightmap.values,
        grid,
        missing_fraction_before_fill=missing_fraction,
        effective_source_resolution_m=None,
        fill_method=config.missing_data if missing_fraction else "none",
    )
    case_relative = f"source/import/{source_path.name}"
    return TerrainSourceResult(
        heightmap=heightmap,
        coordinate_system=local_coordinate_system(
            case_id,
            center_lat,
            center_lon,
            vertical_datum="input GeoTIFF vertical reference; consult source metadata",
        ),
        generation=TerrainGeneration(
            method="file",
            source="file",
            seed=0,
            parameters={
                "input_filename": source_path.name,
                "size_m": float(size_m),
                "cell_size_m": float(cell_size_m),
            },
        ),
        provenance=TerrainProvenance(
            source="file",
            dataset=source_path.name,
            elevation_type="user-provided raster",
            source_crs=str(source_crs),
            vertical_datum="not specified by common GeoTIFF metadata",
            center_lat=center_lat,
            center_lon=center_lon,
            geographic_bounds=tuple(map(float, geographic_bounds)),
            effective_resolution_m=None,
            output_cell_size_m=float(cell_size_m),
            fill_method=config.missing_data if missing_fraction else "none",
            source_data_refs=(case_relative,),
            attribution="User-provided GeoTIFF; attribution must be supplied by the user",
        ),
        quality=quality,
        source_artifacts=(
            SourceArtifact(source_path=source_path, case_relative_path=case_relative),
        ),
    )
