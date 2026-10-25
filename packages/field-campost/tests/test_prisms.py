from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import Polygon
from shapely.ops import unary_union

from field_campost.prisms import polygon_to_prism_mesh, validate_closed_prism_mesh


def test_prism_triangulation_preserves_concavity_hole_and_height():
    polygon = Polygon(
        shell=((0, 0), (8, 0), (8, 3), (5, 3), (5, 8), (0, 8)),
        holes=(((1, 1), (3, 1), (3, 3), (1, 3)),),
    )
    mesh = polygon_to_prism_mesh(
        polygon,
        ground_elevation=lambda coordinates: coordinates[:, 0] * 0.1
        + coordinates[:, 1] * 0.2,
        height_m=5.0,
        max_triangle_edge_m=2.0,
    )

    assert mesh.faces.ndim == 2
    assert mesh.faces.shape[1] == 3
    vertex_count = len(mesh.vertices) // 2
    np.testing.assert_allclose(
        mesh.vertices[vertex_count:, 2] - mesh.vertices[:vertex_count, 2],
        5.0,
    )

    top_faces = mesh.faces[np.all(mesh.faces >= vertex_count, axis=1)] - vertex_count
    top_xy = mesh.vertices[top_faces, :2]
    top_edges = np.linalg.norm(top_xy - np.roll(top_xy, -1, axis=1), axis=2)
    assert float(top_edges.max()) <= 2.0
    all_xy = mesh.vertices[mesh.faces, :2]
    all_edges = np.linalg.norm(all_xy - np.roll(all_xy, -1, axis=1), axis=2)
    assert float(all_edges.max()) <= 2.0
    edge_counts: dict[tuple[int, int], int] = {}
    for face in mesh.faces:
        for first, second in zip(face, np.roll(face, -1)):
            edge = tuple(sorted((int(first), int(second))))
            edge_counts[edge] = edge_counts.get(edge, 0) + 1
    assert set(edge_counts.values()) == {2}
    top_triangles = [Polygon(mesh.vertices[face, :2]) for face in top_faces]
    top_surface = unary_union(top_triangles)
    assert top_surface.area == pytest.approx(polygon.area)
    assert top_surface.symmetric_difference(polygon).area == pytest.approx(0.0, abs=1.0e-9)
    validate_closed_prism_mesh(mesh)
    assert mesh.face_normals.shape == mesh.faces.shape
    np.testing.assert_allclose(np.linalg.norm(mesh.face_normals, axis=1), 1.0)


def test_prism_rejects_non_positive_height():
    polygon = Polygon(((0, 0), (1, 0), (1, 1), (0, 1)))

    with pytest.raises(ValueError, match="positive"):
        polygon_to_prism_mesh(
            polygon,
            ground_elevation=lambda coordinates: np.zeros(len(coordinates)),
            height_m=0.0,
        )
