from __future__ import annotations

from field_environment import Heightmap


def surface_elevation_at(heightmap: Heightmap, x_m: float, y_m: float) -> float:
    return heightmap.surface_elevation_at(x_m, y_m)
