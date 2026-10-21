from __future__ import annotations

import numpy as np

from field_environment import Heightmap


def surface_elevation_at(heightmap: Heightmap, x_m: float, y_m: float) -> float:
    grid = heightmap.grid
    x_coordinate = (x_m - grid.origin.x_m) / grid.cell_size_m
    y_coordinate = (y_m - grid.origin.y_m) / grid.cell_size_m
    tolerance = 1e-9
    if not (-tolerance <= x_coordinate <= grid.width_cells - 1 + tolerance):
        raise IndexError("x coordinate is outside the terrain mesh surface")
    if not (-tolerance <= y_coordinate <= grid.height_cells - 1 + tolerance):
        raise IndexError("y coordinate is outside the terrain mesh surface")
    x_coordinate = float(np.clip(x_coordinate, 0.0, grid.width_cells - 1))
    y_coordinate = float(np.clip(y_coordinate, 0.0, grid.height_cells - 1))
    x_index = min(int(np.floor(x_coordinate)), grid.width_cells - 2)
    y_index = min(int(np.floor(y_coordinate)), grid.height_cells - 2)
    u = x_coordinate - x_index
    v = y_coordinate - y_index
    south_west = float(heightmap.values[y_index, x_index])
    south_east = float(heightmap.values[y_index, x_index + 1])
    north_west = float(heightmap.values[y_index + 1, x_index])
    north_east = float(heightmap.values[y_index + 1, x_index + 1])
    if v <= u:
        return south_west + u * (south_east - south_west) + v * (north_east - south_east)
    return south_west + u * (north_east - north_west) + v * (north_west - south_west)
