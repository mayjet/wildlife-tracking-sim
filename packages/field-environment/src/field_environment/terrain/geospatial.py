from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from pyproj import CRS, Transformer
from shepherd_contracts import GeodeticOrigin, LocalCoordinateSystem, Position2D

from .heightmap import TerrainGridSpec


@dataclass(frozen=True)
class LocalGeographicFrame:
    center_lat: float
    center_lon: float
    crs: CRS
    to_geographic: Transformer
    from_geographic: Transformer


def create_local_geographic_frame(center_lat: float, center_lon: float) -> LocalGeographicFrame:
    crs = CRS.from_proj4(
        f"+proj=aeqd +lat_0={center_lat:.12g} +lon_0={center_lon:.12g} "
        "+datum=WGS84 +units=m +no_defs"
    )
    return LocalGeographicFrame(
        center_lat=center_lat,
        center_lon=center_lon,
        crs=crs,
        to_geographic=Transformer.from_crs(crs, "EPSG:4326", always_xy=True),
        from_geographic=Transformer.from_crs("EPSG:4326", crs, always_xy=True),
    )


def geographic_bounds_for_square(
    center_lat: float, center_lon: float, size_m: float
) -> tuple[float, float, float, float]:
    frame = create_local_geographic_frame(center_lat, center_lon)
    half = size_m / 2.0
    x = np.array([-half, half, half, -half], dtype=float)
    y = np.array([-half, -half, half, half], dtype=float)
    lon, lat = frame.to_geographic.transform(x, y)
    return float(np.min(lon)), float(np.min(lat)), float(np.max(lon)), float(np.max(lat))


def centered_grid(size_m: float, cell_size_m: float) -> TerrainGridSpec:
    return TerrainGridSpec.from_extent(
        width_m=size_m,
        height_m=size_m,
        cell_size_m=cell_size_m,
        min_x_m=-size_m / 2.0,
        min_y_m=-size_m / 2.0,
    )


def local_coordinate_system(
    case_id: str,
    center_lat: float,
    center_lon: float,
    *,
    vertical_datum: str,
) -> LocalCoordinateSystem:
    frame = create_local_geographic_frame(center_lat, center_lon)
    return LocalCoordinateSystem(
        name=f"{case_id}-local-enu",
        origin_description="local ENU origin at configured geographic center",
        geodetic_origin=GeodeticOrigin(
            latitude_deg=center_lat,
            longitude_deg=center_lon,
            altitude_m=0.0,
        ),
        geographic_crs="EPSG:4326",
        projected_crs=frame.crs.to_string(),
        geographic_conversion="WGS84 geographic coordinates transformed by local azimuthal equidistant projection",
        vertical_datum=vertical_datum,
    )


def grid_coordinates(grid: TerrainGridSpec) -> tuple[np.ndarray, np.ndarray]:
    x = grid.origin.x_m + np.arange(grid.width_cells) * grid.cell_size_m
    y = grid.origin.y_m + np.arange(grid.height_cells) * grid.cell_size_m
    return np.meshgrid(x, y, indexing="xy")
