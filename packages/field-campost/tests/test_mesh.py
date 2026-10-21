import numpy as np

from field_campost import heightmap_to_mesh, validate_mesh_against_heightmap
from field_environment import Heightmap, TerrainGridSpec


def test_mesh_matches_heightmap_cell_centers(environment_case):
    mesh = heightmap_to_mesh(environment_case.heightmap)

    assert mesh.vertices.shape == (12, 3)
    assert mesh.faces.shape == (12, 3)
    assert mesh.normals.shape == mesh.vertices.shape
    validate_mesh_against_heightmap(mesh, environment_case.heightmap)


def test_flat_mesh_normals_point_up():
    grid = TerrainGridSpec.from_extent(width_m=20.0, height_m=20.0, cell_size_m=10.0)
    heightmap = Heightmap(values=np.full((2, 2), 4.0, dtype=np.float32), grid=grid)

    mesh = heightmap_to_mesh(heightmap)

    np.testing.assert_allclose(mesh.normals, [[0.0, 0.0, 1.0]] * 4)
    assert np.all(mesh.normals[:, 2] > 0.0)


def test_mesh_rejects_single_cell_axis():
    grid = TerrainGridSpec.from_extent(width_m=10.0, height_m=20.0, cell_size_m=10.0)
    heightmap = Heightmap(values=np.zeros((2, 1), dtype=np.float32), grid=grid)

    try:
        heightmap_to_mesh(heightmap)
    except ValueError as error:
        assert "at least two cells" in str(error)
    else:
        raise AssertionError("single-cell terrain unexpectedly produced a mesh")
