from __future__ import annotations

import math

from shepherd_contracts import Position3D

from field_environment import Heightmap


def surface_elevation_at(heightmap: Heightmap, x_m: float, y_m: float) -> float:
    return heightmap.surface_elevation_at(x_m, y_m)


# XYを変更せず，共通TerrainMeshと同じ三角形面へ位置を投影する．
def project_to_terrain_surface(
    heightmap: Heightmap,
    x_m: float,
    y_m: float,
    *,
    clearance_m: float = 0.0,
) -> Position3D:
    if not math.isfinite(clearance_m) or clearance_m < 0.0:
        raise ValueError("clearance_m must be finite and non-negative")
    ground_z_m = surface_elevation_at(heightmap, x_m, y_m)
    if not math.isfinite(ground_z_m):
        raise ValueError("terrain surface elevation must be finite")
    return Position3D(
        x_m=float(x_m),
        y_m=float(y_m),
        z_m=float(ground_z_m + clearance_m),
    )
