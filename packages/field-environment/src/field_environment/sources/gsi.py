from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import numpy as np
import requests
from PIL import Image

from ..case.models import SourceArtifact, TerrainGeneration, TerrainProvenance
from ..config import GeographicTerrainConfig
from ..errors import TerrainAcquisitionError, TerrainDataUnavailableError
from ..terrain.geospatial import (
    centered_grid,
    create_local_geographic_frame,
    geographic_bounds_for_square,
    grid_coordinates,
    local_coordinate_system,
)
from ..terrain.heightmap import Heightmap
from ..terrain.quality import calculate_terrain_quality, fill_missing_elevations
from .models import TerrainSourceResult

GSI_DATASETS = {
    "dem1a_png": (17, 1.0),
    "dem5a_png": (15, 5.0),
    "dem5b_png": (15, 5.0),
    "dem5c_png": (15, 5.0),
    "dem_png": (14, 10.0),
}
GSI_TILE_URL = "https://cyberjapandata.gsi.go.jp/xyz/{dataset}/{z}/{x}/{y}.png"


def decode_gsi_elevation_png(content: bytes) -> np.ndarray:
    rgb = np.asarray(Image.open(BytesIO(content)).convert("RGB"), dtype=np.int64)
    encoded = rgb[..., 0] * 65536 + rgb[..., 1] * 256 + rgb[..., 2]
    values = np.where(
        encoded < 2**23,
        encoded * 0.01,
        np.where(encoded == 2**23, np.nan, (encoded - 2**24) * 0.01),
    )
    return values.astype(np.float32)


def _tile_coordinates(lon: np.ndarray, lat: np.ndarray, zoom: int):
    count = 2**zoom
    x_float = (lon + 180.0) / 360.0 * count
    latitude_radians = np.radians(np.clip(lat, -85.05112878, 85.05112878))
    y_float = (
        1.0 - np.arcsinh(np.tan(latitude_radians)) / np.pi
    ) / 2.0 * count
    tile_x = np.floor(x_float).astype(np.int64)
    tile_y = np.floor(y_float).astype(np.int64)
    pixel_x = np.clip(np.floor((x_float - tile_x) * 256).astype(np.int64), 0, 255)
    pixel_y = np.clip(np.floor((y_float - tile_y) * 256).astype(np.int64), 0, 255)
    return tile_x, tile_y, pixel_x, pixel_y


def _read_or_download_tile(
    dataset: str,
    zoom: int,
    tile_x: int,
    tile_y: int,
    *,
    cache_root: Path,
    offline: bool,
    session: requests.Session,
) -> tuple[np.ndarray | None, Path | None]:
    path = cache_root / dataset / str(zoom) / str(tile_x) / f"{tile_y}.png"
    if path.is_file():
        return decode_gsi_elevation_png(path.read_bytes()), path
    if offline:
        return None, None
    url = GSI_TILE_URL.format(dataset=dataset, z=zoom, x=tile_x, y=tile_y)
    try:
        response = session.get(url, timeout=30)
    except requests.RequestException as error:
        raise TerrainAcquisitionError(f"GSI tile request failed for {url}: {error}") from error
    if response.status_code in (204, 404):
        return None, None
    try:
        response.raise_for_status()
    except requests.RequestException as error:
        raise TerrainAcquisitionError(f"GSI tile request failed for {url}: {error}") from error
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    return decode_gsi_elevation_png(response.content), path


def acquire_gsi_elevation(
    config: GeographicTerrainConfig,
    *,
    case_id: str,
    working_directory: str | Path,
) -> TerrainSourceResult:
    if config.source != "gsi":
        raise ValueError("GSI adapter requires terrain.source=gsi")
    unknown_datasets = set(config.gsi_datasets) - set(GSI_DATASETS)
    if unknown_datasets:
        raise ValueError(f"unknown GSI datasets: {sorted(unknown_datasets)}")
    working = Path(working_directory)
    cache_root = working / "source" / "gsi"
    grid = centered_grid(config.size_m, config.cell_size_m)
    frame = create_local_geographic_frame(config.center_lat, config.center_lon)
    x_grid, y_grid = grid_coordinates(grid)
    lon, lat = frame.to_geographic.transform(x_grid, y_grid)
    values = np.full(x_grid.shape, np.nan, dtype=np.float32)
    used_paths: set[Path] = set()
    used_datasets: set[str] = set()
    session = requests.Session()
    session.headers["User-Agent"] = "wildlife-tracking-sim/0.1"

    for dataset in config.gsi_datasets:
        zoom, _ = GSI_DATASETS[dataset]
        tile_x, tile_y, pixel_x, pixel_y = _tile_coordinates(lon, lat, zoom)
        missing = ~np.isfinite(values)
        pairs = np.unique(np.column_stack((tile_x[missing], tile_y[missing])), axis=0)
        for current_x, current_y in pairs:
            tile, path = _read_or_download_tile(
                dataset,
                zoom,
                int(current_x),
                int(current_y),
                cache_root=cache_root,
                offline=config.offline,
                session=session,
            )
            if tile is None:
                continue
            selected = missing & (tile_x == current_x) & (tile_y == current_y)
            sampled = tile[pixel_y[selected], pixel_x[selected]]
            finite = np.isfinite(sampled)
            selected_indices = np.flatnonzero(selected)
            values.flat[selected_indices[finite]] = sampled[finite]
            if finite.any():
                used_datasets.add(dataset)
                if path is not None:
                    used_paths.add(path)
        if np.isfinite(values).all():
            break

    if not np.isfinite(values).any():
        raise TerrainDataUnavailableError("no GSI elevation cells were available for the area")
    filled_values, missing_fraction = fill_missing_elevations(values, config.missing_data)
    heightmap = Heightmap(values=filled_values.astype(np.float32), grid=grid)
    native_resolution = min(GSI_DATASETS[name][1] for name in used_datasets)
    quality = calculate_terrain_quality(
        heightmap.values,
        grid,
        missing_fraction_before_fill=missing_fraction,
        effective_source_resolution_m=native_resolution,
        fill_method=config.missing_data if missing_fraction else "none",
    )
    requested_bounds = geographic_bounds_for_square(
        config.center_lat, config.center_lon, config.size_m
    )
    metadata_path = cache_root / "request.json"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        json.dumps(
            {
                "datasets_requested": config.gsi_datasets,
                "datasets_used": sorted(used_datasets),
                "geographic_bounds": requested_bounds,
                "sampling": "nearest PNG tile pixel at each output cell center",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    all_paths = sorted(used_paths) + [metadata_path]
    artifacts = tuple(
        SourceArtifact(
            source_path=path,
            case_relative_path=path.relative_to(working).as_posix(),
        )
        for path in all_paths
    )
    refs = tuple(artifact.case_relative_path for artifact in artifacts)
    return TerrainSourceResult(
        heightmap=heightmap,
        coordinate_system=local_coordinate_system(
            case_id,
            config.center_lat,
            config.center_lon,
            vertical_datum="GSI elevation tile height; source model varies by selected tile dataset",
        ),
        generation=TerrainGeneration(
            method="gsi",
            source="gsi",
            seed=0,
            parameters={
                "datasets": list(config.gsi_datasets),
                "size_m": config.size_m,
                "cell_size_m": config.cell_size_m,
            },
        ),
        provenance=TerrainProvenance(
            source="gsi",
            dataset="+".join(sorted(used_datasets)),
            elevation_type="DEM",
            source_crs="Web Mercator XYZ tiles sampled in EPSG:4326",
            vertical_datum="GSI source elevation model reference",
            center_lat=config.center_lat,
            center_lon=config.center_lon,
            geographic_bounds=requested_bounds,
            effective_resolution_m=native_resolution,
            output_cell_size_m=config.cell_size_m,
            fill_method=config.missing_data if missing_fraction else "none",
            source_data_refs=refs,
            attribution="Geospatial Information Authority of Japan elevation tiles",
            license_url="https://maps.gsi.go.jp/help/term.html",
        ),
        quality=quality,
        source_artifacts=artifacts,
    )
