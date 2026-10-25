from __future__ import annotations

import json
import re
from dataclasses import dataclass
from math import degrees, tan
from pathlib import Path
from typing import TextIO

import numpy as np
from shepherd_contracts import CameraLayout, CameraOrientation, CameraSpec, Position3D

from .cameras import camera_forward_vector
from .mesh import TerrainMesh
from .prisms import iter_layer_polygons, iter_polygons, layer_union, polygon_to_prism_mesh


def _elevation_inside_bounds(heightmap, x_m: float, y_m: float) -> float:
    min_x_m = heightmap.grid.origin.x_m
    min_y_m = heightmap.grid.origin.y_m
    max_x_m = min_x_m + (heightmap.grid.width_cells - 1) * heightmap.grid.cell_size_m
    max_y_m = min_y_m + (heightmap.grid.height_cells - 1) * heightmap.grid.cell_size_m
    clamped_x_m = min(max(x_m, min_x_m), max_x_m)
    clamped_y_m = min(max(y_m, min_y_m), max_y_m)
    return heightmap.surface_elevation_at(clamped_x_m, clamped_y_m)


def _write_prism_scope(
    stream,
    layer,
    heightmap,
    *,
    scope_name: str,
    prim_prefix: str,
    source_layer: str,
    display_color: tuple[float, float, float],
    default_height_m: float,
    follow_terrain: bool,
    subtract=None,
    clip=None,
    geometry_override=None,
) -> None:
    if layer is None or layer.status.value != "available" or heightmap is None:
        return
    polygons = (
        [(polygon, {}) for polygon in iter_polygons(geometry_override)]
        if geometry_override is not None
        else list(iter_layer_polygons(layer, subtract=subtract, clip=clip))
    )
    if not polygons:
        return
    stream.write(f'    def Scope "{scope_name}"\n    {{\n')
    for feature_index, (polygon, properties) in enumerate(polygons):
        height_m = (
            properties.get("height_m")
            or properties.get("assumed_height_m")
            or layer.assumed_height_m
            or default_height_m
        )
        if follow_terrain:
            ground_elevation = lambda coordinates: np.asarray(
                [
                    _elevation_inside_bounds(heightmap, x_m, y_m)
                    for x_m, y_m in coordinates
                ],
                dtype=np.float64,
            )
        else:
            ground_point = polygon.representative_point()
            ground_z = _elevation_inside_bounds(heightmap, ground_point.x, ground_point.y)
            ground_elevation = lambda coordinates, value=ground_z: np.full(
                len(coordinates), value, dtype=np.float64
            )
        prism = polygon_to_prism_mesh(
            polygon,
            ground_elevation=ground_elevation,
            height_m=float(height_m),
            max_triangle_edge_m=(
                heightmap.grid.cell_size_m * 2.0 if follow_terrain else None
            ),
        )
        prim_name = f"{prim_prefix}_{feature_index:05d}"
        stream.write(f'        def Mesh "{prim_name}"\n        {{\n')
        stream.write("            point3d[] points = ")
        _write_tuple_array(stream, prism.vertices, indent="                ", precision=12)
        stream.write("\n            int[] faceVertexCounts = ")
        _write_integer_array(
            stream,
            np.full(len(prism.faces), 3, dtype=np.int32),
            indent="                ",
        )
        stream.write("\n            int[] faceVertexIndices = ")
        _write_integer_array(stream, prism.faces, indent="                ")
        stream.write("\n            normal3f[] normals = ")
        _write_tuple_array(stream, prism.face_normals, indent="                ")
        stream.write(
            '\n            (\n                interpolation = "uniform"\n            )\n'
            '\n            uniform token subdivisionScheme = "none"\n'
            "            uniform bool doubleSided = true\n"
            f"            color3f[] primvars:displayColor = "
            f"[({display_color[0]}, {display_color[1]}, {display_color[2]})]\n"
            '            uniform token primvars:displayColor:interpolation = "constant"\n'
            "            float[] primvars:displayOpacity = [1]\n"
            '            uniform token primvars:displayOpacity:interpolation = "constant"\n'
            f"            custom double shepherd:heightM = {float(height_m):.17g}\n"
            f'            custom string shepherd:sourceLayer = "{source_layer}"\n'
            "        }\n"
        )
    stream.write("    }\n\n")


# 森林Polygonを地表に沿う高さ5 mの完全遮蔽領域として出力する．
def _write_forest_prisms(
    stream, layer, heightmap, *, subtract=None, clip=None, geometry_override=None
) -> None:
    _write_prism_scope(
        stream,
        layer,
        heightmap,
        scope_name="Forest",
        prim_prefix="Forest",
        source_layer="forest",
        display_color=(0.04, 0.28, 0.07),
        default_height_m=10.0,
        follow_terrain=True,
        subtract=subtract,
        clip=clip,
        geometry_override=geometry_override,
    )


# 建物外周を地表から高さ方向へ押し出した簡易3D Meshとして出力する．
def _write_building_prisms(
    stream,
    layer,
    heightmap,
    *,
    scope_name: str = "Buildings",
    source_layer: str = "buildings",
    display_color: tuple[float, float, float] = (0.48, 0.48, 0.52),
    subtract=None,
    clip=None,
) -> None:
    _write_prism_scope(
        stream,
        layer,
        heightmap,
        scope_name=scope_name,
        prim_prefix=scope_name,
        source_layer=source_layer,
        display_color=display_color,
        default_height_m=5.0,
        follow_terrain=False,
        subtract=subtract,
        clip=clip,
    )


@dataclass(frozen=True)
class UsdSceneSummary:
    meters_per_unit: float
    up_axis: str
    layout: CameraLayout
    terrain_vertices: np.ndarray
    terrain_faces: np.ndarray


def _rotation_matrix(camera: CameraSpec) -> np.ndarray:
    yaw = camera.orientation.yaw_rad
    pitch = camera.orientation.pitch_rad
    roll = camera.orientation.roll_rad
    cos_yaw, sin_yaw = np.cos(yaw), np.sin(yaw)
    cos_pitch, sin_pitch = np.cos(pitch), np.sin(pitch)
    cos_roll, sin_roll = np.cos(roll), np.sin(roll)
    rotate_z = np.array(
        [[cos_yaw, -sin_yaw, 0.0], [sin_yaw, cos_yaw, 0.0], [0.0, 0.0, 1.0]]
    )
    rotate_y = np.array(
        [[cos_pitch, 0.0, sin_pitch], [0.0, 1.0, 0.0], [-sin_pitch, 0.0, cos_pitch]]
    )
    rotate_x = np.array(
        [[1.0, 0.0, 0.0], [0.0, cos_roll, -sin_roll], [0.0, sin_roll, cos_roll]]
    )
    return rotate_z @ rotate_y @ rotate_x


def _usd_camera_transform(camera: CameraSpec) -> np.ndarray:
    body_to_world = _rotation_matrix(camera)
    usd_camera_to_body = np.array(
        [[0.0, 0.0, -1.0], [-1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    )
    camera_to_world = body_to_world @ usd_camera_to_body
    transform = np.eye(4)
    transform[:3, :3] = camera_to_world
    transform[:3, 3] = [camera.position.x_m, camera.position.y_m, camera.position.z_m]
    return transform


def _usd_identifier(value: str, prefix: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_]", "_", value)
    if not sanitized or sanitized[0].isdigit():
        sanitized = f"_{sanitized}"
    return f"{prefix}_{sanitized}"


def _write_tuple_array(
    stream: TextIO,
    values: np.ndarray,
    *,
    indent: str,
    precision: int = 9,
) -> None:
    stream.write("[\n")
    formatter = f"{{:.{precision}g}}"
    for index, row in enumerate(values):
        rendered = ", ".join(formatter.format(float(value)) for value in row)
        suffix = "," if index + 1 < len(values) else ""
        stream.write(f"{indent}({rendered}){suffix}\n")
    stream.write(f"{indent[:-4]}]")


def _write_integer_array(stream: TextIO, values: np.ndarray, *, indent: str) -> None:
    stream.write("[")
    flat = values.reshape(-1)
    chunk_size = 24
    for start in range(0, len(flat), chunk_size):
        if start:
            stream.write(",\n" + indent)
        stream.write(", ".join(str(int(value)) for value in flat[start : start + chunk_size]))
    stream.write("]")


def write_environment_usd(
    mesh: TerrainMesh,
    layout: CameraLayout,
    path: str | Path,
    *,
    heightmap=None,
    buildings=None,
    forest=None,
    facility_buildings=None,
    scene_crop=None,
    forest_boundary_smoothing_m: float = 0.0,
    overwrite: bool = False,
) -> Path:
    destination = Path(path)
    if destination.exists() and not overwrite:
        raise FileExistsError(f"USD already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(
                '#usda 1.0\n(\n    defaultPrim = "World"\n    metersPerUnit = 1\n'
                '    upAxis = "Z"\n)\n\ndef Xform "World"\n{\n'
            )
            stream.write(f"    custom string shepherd:layoutId = {json.dumps(layout.layout_id)}\n")
            stream.write('    def Mesh "Terrain"\n    {\n')
            stream.write("        point3f[] points = ")
            _write_tuple_array(stream, mesh.vertices, indent="            ")
            stream.write("\n        int[] faceVertexCounts = ")
            _write_integer_array(
                stream, np.full(len(mesh.faces), 3, dtype=np.int32), indent="            "
            )
            stream.write("\n        int[] faceVertexIndices = ")
            _write_integer_array(stream, mesh.faces, indent="            ")
            stream.write("\n        normal3f[] normals = ")
            _write_tuple_array(stream, mesh.normals, indent="            ")
            stream.write(
                '\n        (\n            interpolation = "vertex"\n        )\n'
                '        uniform token subdivisionScheme = "none"\n'
                "        uniform bool doubleSided = true\n"
                "        color3f[] primvars:displayColor = [(0.42, 0.35, 0.20)]\n"
                '        uniform token primvars:displayColor:interpolation = "constant"\n'
                "    }\n\n"
            )
            building_footprints = layer_union(buildings)
            facility_footprints = layer_union(facility_buildings)
            forest_geometry = layer_union(forest)
            if scene_crop is not None:
                building_footprints = building_footprints.intersection(scene_crop)
                facility_footprints = facility_footprints.intersection(scene_crop)
                forest_geometry = forest_geometry.intersection(scene_crop)
            forest_geometry = forest_geometry.difference(building_footprints)
            if forest_boundary_smoothing_m > 0.0 and not forest_geometry.is_empty:
                half = forest_boundary_smoothing_m * 0.5
                forest_geometry = forest_geometry.buffer(half, join_style=2).buffer(
                    -half, join_style=2
                )
                forest_geometry = forest_geometry.simplify(half, preserve_topology=True)
            _write_forest_prisms(
                stream,
                forest,
                heightmap,
                geometry_override=forest_geometry,
            )
            _write_building_prisms(
                stream,
                buildings,
                heightmap,
                subtract=facility_footprints,
                clip=scene_crop,
            )
            _write_building_prisms(
                stream,
                facility_buildings,
                heightmap,
                scope_name="FacilityBuildings",
                source_layer="facility_buildings",
                display_color=(0.85, 0.42, 0.08),
                clip=scene_crop,
            )
            stream.write('    def Scope "Cameras"\n    {\n')
            for camera in layout.cameras:
                prim_name = _usd_identifier(camera.camera_id, "Camera")
                transform = _usd_camera_transform(camera).T
                horizontal_aperture_mm = 20.955
                focal_length_mm = horizontal_aperture_mm / (
                    2.0 * tan(camera.horizontal_fov_rad / 2.0)
                )
                vertical_aperture_mm = 2.0 * focal_length_mm * tan(
                    camera.vertical_fov_rad / 2.0
                )
                stream.write(f'        def Xform "{prim_name}"\n        {{\n')
                stream.write(
                    f"            custom string shepherd:cameraId = "
                    f"{json.dumps(camera.camera_id)}\n"
                )
                stream.write(
                    "            custom double3 shepherd:positionM = "
                    f"({camera.position.x_m:.17g}, {camera.position.y_m:.17g}, "
                    f"{camera.position.z_m:.17g})\n"
                )
                stream.write(
                    "            custom double3 shepherd:orientationRad = "
                    f"({camera.orientation.yaw_rad:.17g}, "
                    f"{camera.orientation.pitch_rad:.17g}, "
                    f"{camera.orientation.roll_rad:.17g})\n"
                )
                stream.write(
                    f"            custom double shepherd:horizontalFovRad = "
                    f"{camera.horizontal_fov_rad:.17g}\n"
                    f"            custom double shepherd:verticalFovRad = "
                    f"{camera.vertical_fov_rad:.17g}\n"
                    f"            custom double shepherd:maxObservationDistanceM = "
                    f"{camera.max_observation_distance_m:.17g}\n"
                    f"            custom double shepherd:observationIntervalS = "
                    f"{camera.observation_interval_s:.17g}\n"
                )
                rows = [
                    "(" + ", ".join(f"{float(value):.17g}" for value in row) + ")"
                    for row in transform
                ]
                stream.write(
                    "            matrix4d xformOp:transform = ("
                    + ", ".join(rows)
                    + ")\n"
                    '            uniform token[] xformOpOrder = ["xformOp:transform"]\n'
                    '            def Camera "Visualization"\n            {\n'
                    f"                float horizontalAperture = {horizontal_aperture_mm:.9g}\n"
                    f"                float verticalAperture = {vertical_aperture_mm:.9g}\n"
                    f"                float focalLength = {focal_length_mm:.9g}\n"
                    f"                float2 clippingRange = (0.1, "
                    f"{camera.max_observation_distance_m:.9g})\n"
                    "            }\n        }\n"
                )
            stream.write("    }\n}\n")
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def _parse_tuples(text: str, width: int, dtype: np.dtype) -> np.ndarray:
    rows = []
    for match in re.finditer(r"\(([^()]*)\)", text):
        values = [value.strip() for value in match.group(1).split(",")]
        if len(values) == width:
            rows.append(values)
    return np.asarray(rows, dtype=dtype)


def _extract_array(document: str, declaration: str) -> str:
    match = re.search(re.escape(declaration) + r"\s*=\s*\[(.*?)\]", document, re.DOTALL)
    if match is None:
        raise ValueError(f"USD is missing {declaration}")
    return match.group(1)


def read_environment_usd(path: str | Path) -> UsdSceneSummary:
    document = Path(path).read_text(encoding="utf-8")
    if not document.startswith("#usda 1.0"):
        raise ValueError("only ASCII USDA 1.0 files are supported by this reader")
    meters_match = re.search(r"metersPerUnit\s*=\s*([0-9.eE+-]+)", document)
    up_axis_match = re.search(r'upAxis\s*=\s*"([XYZ])"', document)
    layout_match = re.search(r'shepherd:layoutId\s*=\s*("(?:\\.|[^"])*")', document)
    if meters_match is None or up_axis_match is None or layout_match is None:
        raise ValueError("USD stage metadata is incomplete")

    vertices = _parse_tuples(_extract_array(document, "point3f[] points"), 3, np.float32)
    indices_text = _extract_array(document, "int[] faceVertexIndices")
    indices = np.fromstring(indices_text.replace("\n", ""), sep=",", dtype=np.int32)
    if len(indices) % 3:
        raise ValueError("terrain face index count is not divisible by three")
    faces = indices.reshape(-1, 3)

    camera_pattern = re.compile(
        r'custom string shepherd:cameraId\s*=\s*("(?:\\.|[^"])*").*?'
        r"custom double3 shepherd:positionM\s*=\s*\(([^)]*)\).*?"
        r"custom double3 shepherd:orientationRad\s*=\s*\(([^)]*)\).*?"
        r"custom double shepherd:horizontalFovRad\s*=\s*([0-9.eE+-]+).*?"
        r"custom double shepherd:verticalFovRad\s*=\s*([0-9.eE+-]+).*?"
        r"custom double shepherd:maxObservationDistanceM\s*=\s*([0-9.eE+-]+).*?"
        r"custom double shepherd:observationIntervalS\s*=\s*([0-9.eE+-]+)",
        re.DOTALL,
    )
    cameras = []
    for match in camera_pattern.finditer(document):
        position = [float(value) for value in match.group(2).split(",")]
        orientation = [float(value) for value in match.group(3).split(",")]
        cameras.append(
            CameraSpec(
                camera_id=json.loads(match.group(1)),
                position=Position3D(x_m=position[0], y_m=position[1], z_m=position[2]),
                orientation=CameraOrientation(
                    yaw_rad=orientation[0], pitch_rad=orientation[1], roll_rad=orientation[2]
                ),
                horizontal_fov_rad=float(match.group(4)),
                vertical_fov_rad=float(match.group(5)),
                max_observation_distance_m=float(match.group(6)),
                observation_interval_s=float(match.group(7)),
            )
        )
    layout = CameraLayout(layout_id=json.loads(layout_match.group(1)), cameras=tuple(cameras))
    return UsdSceneSummary(
        meters_per_unit=float(meters_match.group(1)),
        up_axis=up_axis_match.group(1),
        layout=layout,
        terrain_vertices=vertices,
        terrain_faces=faces,
    )


def validate_usd_with_pxr(path: str | Path) -> None:
    try:
        from pxr import Usd, UsdGeom
    except ImportError as error:
        raise RuntimeError("usd-core is not installed; pxr validation is unavailable") from error
    stage = Usd.Stage.Open(str(path))
    if stage is None:
        raise ValueError("pxr could not open the USD stage")
    if UsdGeom.GetStageMetersPerUnit(stage) != 1.0:
        raise ValueError("USD stage must use meters")
    if UsdGeom.GetStageUpAxis(stage) != UsdGeom.Tokens.z:
        raise ValueError("USD stage must use Z-up")


def camera_look_at(camera: CameraSpec, distance_m: float = 1.0) -> tuple[float, float, float]:
    target = np.array(
        [camera.position.x_m, camera.position.y_m, camera.position.z_m], dtype=float
    ) + camera_forward_vector(camera) * distance_m
    return float(target[0]), float(target[1]), float(target[2])
