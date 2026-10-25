from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator

import numpy as np
from shapely import constrained_delaunay_triangles, make_valid, unary_union
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, shape
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient


@dataclass(frozen=True)
class PrismMesh:
    vertices: np.ndarray
    faces: np.ndarray
    face_normals: np.ndarray


def _face_normals(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    first = vertices[faces[:, 0]]
    second = vertices[faces[:, 1]]
    third = vertices[faces[:, 2]]
    normals = np.cross(second - first, third - first)
    lengths = np.linalg.norm(normals, axis=1)
    if np.any(lengths <= 0.0):
        raise ValueError("prism contains a degenerate triangle")
    return normals / lengths[:, None]


def validate_closed_prism_mesh(mesh: PrismMesh) -> None:
    edge_counts: dict[tuple[int, int], int] = {}
    for face in mesh.faces:
        for first, second in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
            edge = tuple(sorted((int(first), int(second))))
            edge_counts[edge] = edge_counts.get(edge, 0) + 1
    if any(count != 2 for count in edge_counts.values()):
        raise ValueError("prism mesh is not a closed two-manifold surface")


def iter_polygons(geometry: BaseGeometry) -> Iterator[Polygon]:
    if geometry.is_empty:
        return
    valid_geometry = geometry if geometry.is_valid else make_valid(geometry)
    if isinstance(valid_geometry, Polygon):
        yield valid_geometry
        return
    if isinstance(valid_geometry, (MultiPolygon, GeometryCollection)):
        for part in valid_geometry.geoms:
            yield from iter_polygons(part)


def layer_union(layer) -> BaseGeometry:
    if layer is None or layer.status.value != "available":
        return GeometryCollection()
    geometries = [shape(feature["geometry"]) for feature in layer.features]
    if not geometries:
        return GeometryCollection()
    return unary_union(geometries)


def iter_layer_polygons(
    layer,
    *,
    subtract: BaseGeometry | None = None,
    clip: BaseGeometry | None = None,
):
    if layer is None or layer.status.value != "available":
        return
    for feature in layer.features:
        geometry = shape(feature["geometry"])
        if clip is not None:
            geometry = geometry.intersection(clip)
        if subtract is not None and not subtract.is_empty:
            geometry = geometry.difference(subtract)
        properties = feature.get("properties") or {}
        for polygon in iter_polygons(geometry):
            if polygon.area > 0.0:
                yield polygon, properties


def _refine_triangle(
    triangle: np.ndarray,
    max_edge_length_m: float | None,
) -> Iterator[np.ndarray]:
    pending = [triangle]
    while pending:
        current = pending.pop()
        edges = (
            (0, 1, 2),
            (1, 2, 0),
            (2, 0, 1),
        )
        edge_lengths = [
            float(np.linalg.norm(current[second] - current[first]))
            for first, second, _ in edges
        ]
        longest_index = int(np.argmax(edge_lengths))
        if max_edge_length_m is None or edge_lengths[longest_index] <= max_edge_length_m:
            yield current
            continue
        first, second, opposite = edges[longest_index]
        midpoint = (current[first] + current[second]) * 0.5
        pending.append(np.asarray((midpoint, current[second], current[opposite])))
        pending.append(np.asarray((current[first], midpoint, current[opposite])))


def _triangle_coordinates(
    polygon: Polygon,
    max_edge_length_m: float | None,
) -> Iterator[np.ndarray]:
    triangles = constrained_delaunay_triangles(polygon)
    for triangle in triangles.geoms:
        coordinates = np.asarray(triangle.exterior.coords[:-1], dtype=np.float64)
        if len(coordinates) != 3:
            continue
        if not polygon.covers(triangle):
            continue
        yield from _refine_triangle(coordinates, max_edge_length_m)


def _ring_coordinates(ring, max_edge_length_m: float | None) -> Iterator[np.ndarray]:
    coordinates = np.asarray(ring.coords, dtype=np.float64)
    for index in range(len(coordinates) - 1):
        first = coordinates[index]
        second = coordinates[index + 1]
        yield first
        if max_edge_length_m is None:
            continue
        segment_count = 1
        while float(np.linalg.norm(second - first)) / segment_count > max_edge_length_m:
            segment_count *= 2
        for segment_index in range(1, segment_count):
            yield first + (second - first) * (segment_index / segment_count)


# 凹形状と穴を保った三角形面から地物の柱状Meshを構築する．
def polygon_to_prism_mesh(
    polygon: Polygon,
    *,
    ground_elevation: Callable[[np.ndarray], np.ndarray],
    height_m: float,
    max_triangle_edge_m: float | None = None,
) -> PrismMesh:
    if height_m <= 0.0:
        raise ValueError("prism height must be positive")
    if max_triangle_edge_m is not None and max_triangle_edge_m <= 0.0:
        raise ValueError("maximum triangle edge length must be positive")

    polygon = orient(polygon, sign=1.0)
    coordinate_indices: dict[tuple[float, float], int] = {}
    coordinates: list[tuple[float, float]] = []

    def coordinate_index(coordinate) -> int:
        key = (round(float(coordinate[0]), 9), round(float(coordinate[1]), 9))
        if key not in coordinate_indices:
            coordinate_indices[key] = len(coordinates)
            coordinates.append(key)
        return coordinate_indices[key]

    top_triangles: list[tuple[int, int, int]] = []
    for triangle in _triangle_coordinates(polygon, max_triangle_edge_m):
        indices = tuple(coordinate_index(coordinate) for coordinate in triangle)
        first_edge = triangle[1] - triangle[0]
        second_edge = triangle[2] - triangle[0]
        signed_area = first_edge[0] * second_edge[1] - first_edge[1] * second_edge[0]
        if signed_area < 0.0:
            indices = (indices[0], indices[2], indices[1])
        top_triangles.append(indices)
    if not top_triangles:
        raise ValueError("polygon could not be triangulated")

    rings = (polygon.exterior, *polygon.interiors)
    ring_indices: list[list[int]] = []
    for ring in rings:
        ring_indices.append(
            [
                coordinate_index(coordinate)
                for coordinate in _ring_coordinates(ring, max_triangle_edge_m)
            ]
        )

    xy = np.asarray(coordinates, dtype=np.float64)
    ground_z = np.asarray(ground_elevation(xy), dtype=np.float64)
    if ground_z.shape != (len(xy),) or not np.all(np.isfinite(ground_z)):
        raise ValueError("ground elevation must return one finite value per vertex")
    bottom = np.column_stack((xy, ground_z))
    top = np.column_stack((xy, ground_z + float(height_m)))
    vertex_count = len(xy)

    faces: list[tuple[int, int, int]] = []
    for first, second, third in top_triangles:
        faces.append((third, second, first))
        faces.append((first + vertex_count, second + vertex_count, third + vertex_count))
    for indices in ring_indices:
        for index, first in enumerate(indices):
            second = indices[(index + 1) % len(indices)]
            faces.append((first, second, second + vertex_count))
            faces.append((first, second + vertex_count, first + vertex_count))

    vertices = np.vstack((bottom, top))
    face_array = np.asarray(faces, dtype=np.int32)
    mesh = PrismMesh(
        vertices=vertices,
        faces=face_array,
        face_normals=_face_normals(vertices, face_array),
    )
    validate_closed_prism_mesh(mesh)
    return mesh
