from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from rasterio.transform import from_bounds

from ..case.models import SourceArtifact, TerrainGeneration, TerrainProvenance
from ..config import GeographicTerrainConfig
from ..errors import TerrainAcquisitionError, TerrainDataUnavailableError
from ..terrain.geospatial import (
    create_local_geographic_frame,
    geographic_bounds_for_square,
    local_coordinate_system,
)
from ..terrain.heightmap import Heightmap
from ..terrain.quality import calculate_terrain_quality, fill_missing_elevations
from .common import reproject_geographic_raster_to_centered_grid, write_source_geotiff
from .models import TerrainSourceResult

AW3D30_COLLECTION = "JAXA.EORC_ALOS.PRISM_AW3D30.v3.2_global"
AW3D30_DATE_RANGE = ("2021-02-01T00:00:00", "2021-02-28T23:59:59")


def _expanded_jaxa_bounds(
    bounds: tuple[float, float, float, float], minimum_degrees: float = 0.0101
) -> tuple[float, float, float, float]:
    west, south, east, north = bounds
    center_lon = (west + east) / 2.0
    center_lat = (south + north) / 2.0
    width = max(east - west, minimum_degrees)
    height = max(north - south, minimum_degrees)
    return (
        center_lon - width / 2.0,
        center_lat - height / 2.0,
        center_lon + width / 2.0,
        center_lat + height / 2.0,
    )


def _download_aw3d30(bounds, output_path: Path) -> tuple[np.ndarray, object, tuple]:
    try:
        from jaxa.earth import je
    except ImportError as error:
        raise TerrainAcquisitionError(
            "jaxa-earth is required for ALOS acquisition; install field-environment[alos]"
        ) from error
    try:
        data = (
            je.ImageCollection(AW3D30_COLLECTION, ssl_verify=True)
            .filter_date(list(AW3D30_DATE_RANGE))
            .filter_resolution(ppu=3600)
            .filter_bounds(bbox=list(bounds))
            .select("DSM")
            .get_images()
        )
    except Exception as error:
        raise TerrainAcquisitionError(f"JAXA Earth API request failed: {error}") from error
    raster = data.raster
    masked = np.ma.asarray(raster.img[0, :, :, 0], dtype=np.float32)
    values = np.asarray(masked.filled(np.nan), dtype=np.float32)
    values[(values <= -9999.0) | (values >= 10000.0)] = np.nan
    lon_min, lon_max = map(float, raster.lonlim[0])
    lat_min, lat_max = map(float, raster.latlim[0])
    transform = from_bounds(lon_min, lat_min, lon_max, lat_max, values.shape[1], values.shape[0])
    write_source_geotiff(
        output_path,
        values,
        transform=transform,
        crs="EPSG:4326",
        nodata=np.nan,
    )
    return values, transform, (lon_min, lat_min, lon_max, lat_max)


def acquire_alos_aw3d30(
    config: GeographicTerrainConfig,
    *,
    case_id: str,
    working_directory: str | Path,
) -> TerrainSourceResult:
    if config.source != "alos":
        raise ValueError("ALOS adapter requires terrain.source=alos")
    working = Path(working_directory)
    raw_path = working / "source" / "jaxa" / "aw3d30_dsm.tif"
    requested_bounds = geographic_bounds_for_square(
        config.center_lat, config.center_lon, config.size_m
    )
    fetch_bounds = _expanded_jaxa_bounds(requested_bounds)
    if raw_path.is_file():
        import rasterio

        with rasterio.open(raw_path) as dataset:
            source_values = dataset.read(1)
            source_transform = dataset.transform
    elif config.offline:
        raise TerrainDataUnavailableError(f"cached ALOS source not found: {raw_path}")
    else:
        source_values, source_transform, _ = _download_aw3d30(fetch_bounds, raw_path)

    frame = create_local_geographic_frame(config.center_lat, config.center_lon)
    projected_values, grid = reproject_geographic_raster_to_centered_grid(
        source_values,
        source_transform=source_transform,
        source_crs="EPSG:4326",
        frame=frame,
        size_m=config.size_m,
        cell_size_m=config.cell_size_m,
        source_nodata=np.nan,
    )
    filled_values, missing_fraction = fill_missing_elevations(
        projected_values, config.missing_data
    )
    heightmap = Heightmap(values=filled_values.astype(np.float32), grid=grid)
    quality = calculate_terrain_quality(
        heightmap.values,
        grid,
        missing_fraction_before_fill=missing_fraction,
        effective_source_resolution_m=30.0,
        fill_method=config.missing_data if missing_fraction else "none",
    )
    metadata_path = working / "source" / "jaxa" / "request.json"
    metadata_path.write_text(
        json.dumps(
            {
                "collection": AW3D30_COLLECTION,
                "band": "DSM",
                "date_range": AW3D30_DATE_RANGE,
                "requested_bounds": requested_bounds,
                "api_fetch_bounds": fetch_bounds,
                "ppu": 3600,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    refs = ("source/jaxa/aw3d30_dsm.tif", "source/jaxa/request.json")
    return TerrainSourceResult(
        heightmap=heightmap,
        coordinate_system=local_coordinate_system(
            case_id,
            config.center_lat,
            config.center_lon,
            vertical_datum="AW3D30 DSM height; vertical reference follows JAXA product metadata",
        ),
        generation=TerrainGeneration(
            method="alos",
            source="alos",
            seed=0,
            parameters={
                "collection": AW3D30_COLLECTION,
                "band": "DSM",
                "size_m": config.size_m,
                "cell_size_m": config.cell_size_m,
            },
        ),
        provenance=TerrainProvenance(
            source="alos",
            dataset=AW3D30_COLLECTION,
            elevation_type="DSM",
            source_crs="EPSG:4326",
            vertical_datum="JAXA AW3D30 product height reference",
            center_lat=config.center_lat,
            center_lon=config.center_lon,
            geographic_bounds=requested_bounds,
            effective_resolution_m=30.0,
            output_cell_size_m=config.cell_size_m,
            fill_method=config.missing_data if missing_fraction else "none",
            source_data_refs=refs,
            attribution="This data was obtained using JAXA Earth API; AW3D30 by JAXA EORC",
            license_url="https://earth.jaxa.jp/policy/",
        ),
        quality=quality,
        source_artifacts=(
            SourceArtifact(source_path=raw_path, case_relative_path=refs[0]),
            SourceArtifact(source_path=metadata_path, case_relative_path=refs[1]),
        ),
    )
