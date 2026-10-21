from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from field_environment import Heightmap


@dataclass(frozen=True)
class TerrainMesh:
    vertices: NDArray[np.float32]
    faces: NDArray[np.int32]
    normals: NDArray[np.float32]

    def __post_init__(self) -> None:
        vertices = np.asarray(self.vertices, dtype=np.float32, order="C")
        faces = np.asarray(self.faces, dtype=np.int32, order="C")
        normals = np.asarray(self.normals, dtype=np.float32, order="C")
        if vertices.ndim != 2 or vertices.shape[1] != 3:
            raise ValueError("vertices must have shape (N, 3)")
        if faces.ndim != 2 or faces.shape[1] != 3:
            raise ValueError("faces must have shape (M, 3)")
        if normals.shape != vertices.shape:
            raise ValueError("normals must match the vertices shape")
        if not np.isfinite(vertices).all() or not np.isfinite(normals).all():
            raise ValueError("mesh coordinates and normals must be finite")
        if faces.size and (faces.min() < 0 or faces.max() >= len(vertices)):
            raise ValueError("face index is outside the vertex array")
        for values in (vertices, faces, normals):
            values.setflags(write=False)
        object.__setattr__(self, "vertices", vertices)
        object.__setattr__(self, "faces", faces)
        object.__setattr__(self, "normals", normals)


def heightmap_to_mesh(heightmap: Heightmap) -> TerrainMesh:
    grid = heightmap.grid
    if grid.width_cells < 2 or grid.height_cells < 2:
        raise ValueError("terrain mesh requires at least two cells on each axis")

    x_coordinates = grid.origin.x_m + np.arange(grid.width_cells) * grid.cell_size_m
    y_coordinates = grid.origin.y_m + np.arange(grid.height_cells) * grid.cell_size_m
    x_grid, y_grid = np.meshgrid(x_coordinates, y_coordinates, indexing="xy")
    vertices = np.empty((grid.width_cells * grid.height_cells, 3), dtype=np.float32)
    vertices[:, 0] = x_grid.ravel().astype(np.float32, copy=False)
    vertices[:, 1] = y_grid.ravel().astype(np.float32, copy=False)
    vertices[:, 2] = heightmap.values.ravel().astype(np.float32, copy=False)

    rows = np.arange(grid.height_cells - 1, dtype=np.int32)[:, None]
    columns = np.arange(grid.width_cells - 1, dtype=np.int32)[None, :]
    south_west = rows * grid.width_cells + columns
    south_east = south_west + 1
    north_west = south_west + grid.width_cells
    north_east = north_west + 1
    faces = np.empty((2 * south_west.size, 3), dtype=np.int32)
    faces[0::2] = np.stack(
        (south_west.ravel(), south_east.ravel(), north_east.ravel()), axis=1
    )
    faces[1::2] = np.stack(
        (south_west.ravel(), north_east.ravel(), north_west.ravel()), axis=1
    )

    triangle_normals = np.cross(
        vertices[faces[:, 1]] - vertices[faces[:, 0]],
        vertices[faces[:, 2]] - vertices[faces[:, 0]],
    )
    normals = np.zeros_like(vertices)
    for face_column in range(3):
        np.add.at(normals, faces[:, face_column], triangle_normals)
    lengths = np.linalg.norm(normals, axis=1)
    if np.any(lengths == 0.0):
        raise ValueError("terrain mesh contains a vertex without a valid normal")
    normals /= lengths[:, None]
    return TerrainMesh(vertices=vertices, faces=faces, normals=normals)


def validate_mesh_against_heightmap(
    mesh: TerrainMesh,
    heightmap: Heightmap,
    *,
    absolute_tolerance_m: float = 1e-5,
) -> None:
    expected_vertices = heightmap.grid.width_cells * heightmap.grid.height_cells
    if len(mesh.vertices) != expected_vertices:
        raise ValueError("mesh vertex count does not match the Heightmap")
    expected_x = heightmap.grid.origin.x_m + (
        np.arange(heightmap.grid.width_cells) * heightmap.grid.cell_size_m
    )
    expected_y = heightmap.grid.origin.y_m + (
        np.arange(heightmap.grid.height_cells) * heightmap.grid.cell_size_m
    )
    if not np.allclose(
        mesh.vertices[:, 0].reshape(heightmap.values.shape), expected_x[None, :], atol=1e-9
    ):
        raise ValueError("mesh x coordinates do not match Heightmap cell centers")
    if not np.allclose(
        mesh.vertices[:, 1].reshape(heightmap.values.shape), expected_y[:, None], atol=1e-9
    ):
        raise ValueError("mesh y coordinates do not match Heightmap cell centers")
    if not np.allclose(
        mesh.vertices[:, 2].reshape(heightmap.values.shape),
        heightmap.values,
        rtol=0.0,
        atol=absolute_tolerance_m,
    ):
        raise ValueError("mesh elevations do not match Heightmap values")
