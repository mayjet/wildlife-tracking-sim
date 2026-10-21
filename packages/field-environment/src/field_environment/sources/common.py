from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject

from ..terrain.geospatial import LocalGeographicFrame, centered_grid


def reproject_geographic_raster_to_centered_grid(
    source_values_north_up: np.ndarray,
    *,
    source_transform,
    source_crs,
    frame: LocalGeographicFrame,
    size_m: float,
    cell_size_m: float,
    source_nodata: float | None = None,
) -> tuple[np.ndarray, object]:
    grid = centered_grid(size_m, cell_size_m)
    destination_north_up = np.full(
        (grid.height_cells, grid.width_cells), np.nan, dtype=np.float32
    )
    destination_transform = from_origin(
        grid.bounds.min_x_m,
        grid.bounds.max_y_m,
        grid.cell_size_m,
        grid.cell_size_m,
    )
    reproject(
        source=np.asarray(source_values_north_up),
        destination=destination_north_up,
        src_transform=source_transform,
        src_crs=source_crs,
        src_nodata=source_nodata,
        dst_transform=destination_transform,
        dst_crs=frame.crs,
        dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )
    return destination_north_up[::-1, :], grid


def write_source_geotiff(
    path: str | Path,
    values_north_up: np.ndarray,
    *,
    transform,
    crs: str,
    nodata: float | None = np.nan,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        destination,
        "w",
        driver="GTiff",
        width=values_north_up.shape[1],
        height=values_north_up.shape[0],
        count=1,
        dtype="float32",
        transform=transform,
        crs=crs,
        nodata=nodata,
        compress="deflate",
    ) as dataset:
        dataset.write(np.asarray(values_north_up, dtype=np.float32), 1)
    return destination
