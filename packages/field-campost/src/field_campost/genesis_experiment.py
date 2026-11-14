from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import numpy as np
from shepherd_contracts import CameraSpec, ObservationPointLayout

from .cameras import camera_rotation_matrix
from .genesis import GenesisScene


VIEWER_FRUSTUM_DISTANCE_M = 40.0


@dataclass(frozen=True)
class GenesisInfrastructureAssets:
    poles: Path
    camera_housings: Path
    infrastructure_usda: Path


@dataclass(frozen=True)
class GenesisSceneLayers:
    scene_usda: Path
    debug_usda: Path


@dataclass(frozen=True)
class GenesisRouteOverlay:
    route_id: str
    positions: np.ndarray
    waypoints: np.ndarray
    color: tuple[float, float, float, float] = (1.0, 0.10, 0.75, 0.98)


@dataclass(frozen=True)
class GenesisVisibilityOverlay:
    visible_positions: np.ndarray
    hidden_positions: np.ndarray


@dataclass(frozen=True)
class GenesisValidationRay:
    start: tuple[float, float, float]
    end: tuple[float, float, float]
    visible: bool
    reason: str


@dataclass
class _Mesh:
    vertices: list[tuple[float, float, float]] = field(default_factory=list)
    faces: list[tuple[int, int, int]] = field(default_factory=list)

    def add_vertices_and_faces(
        self,
        vertices: np.ndarray,
        faces: Iterable[tuple[int, int, int]],
    ) -> None:
        offset = len(self.vertices)
        self.vertices.extend(tuple(map(float, vertex)) for vertex in vertices)
        self.faces.extend(tuple(offset + int(index) for index in face) for face in faces)


def _add_vertical_cylinder(
    mesh: _Mesh,
    *,
    x_m: float,
    y_m: float,
    bottom_z_m: float,
    top_z_m: float,
    radius_m: float,
    sides: int = 10,
) -> None:
    angles = np.linspace(0.0, 2.0 * np.pi, sides, endpoint=False)
    ring = np.column_stack((np.cos(angles), np.sin(angles))) * radius_m
    vertices = np.vstack(
        (
            np.column_stack(
                (x_m + ring[:, 0], y_m + ring[:, 1], np.full(sides, bottom_z_m))
            ),
            np.column_stack(
                (x_m + ring[:, 0], y_m + ring[:, 1], np.full(sides, top_z_m))
            ),
            np.asarray(((x_m, y_m, bottom_z_m), (x_m, y_m, top_z_m))),
        )
    )
    bottom_center = 2 * sides
    top_center = bottom_center + 1
    faces = []
    for index in range(sides):
        next_index = (index + 1) % sides
        faces.extend(
            (
                (index, next_index, sides + next_index),
                (index, sides + next_index, sides + index),
                (bottom_center, next_index, index),
                (top_center, sides + index, sides + next_index),
            )
        )
    mesh.add_vertices_and_faces(vertices, faces)


def _add_oriented_box(
    mesh: _Mesh,
    *,
    center: np.ndarray,
    rotation: np.ndarray,
    size: tuple[float, float, float],
) -> None:
    half = np.asarray(size, dtype=np.float64) / 2.0
    local = np.asarray(
        [
            (-half[0], -half[1], -half[2]),
            (half[0], -half[1], -half[2]),
            (half[0], half[1], -half[2]),
            (-half[0], half[1], -half[2]),
            (-half[0], -half[1], half[2]),
            (half[0], -half[1], half[2]),
            (half[0], half[1], half[2]),
            (-half[0], half[1], half[2]),
        ],
        dtype=np.float64,
    )
    vertices = local @ rotation.T + center
    faces = (
        (0, 2, 1), (0, 3, 2),
        (4, 5, 6), (4, 6, 7),
        (0, 1, 5), (0, 5, 4),
        (1, 2, 6), (1, 6, 5),
        (2, 3, 7), (2, 7, 6),
        (3, 0, 4), (3, 4, 7),
    )
    mesh.add_vertices_and_faces(vertices, faces)


def _write_obj(path: Path, name: str, mesh: _Mesh) -> Path:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(f"o {name}\n")
        for x_m, y_m, z_m in mesh.vertices:
            stream.write(f"v {x_m:.9g} {y_m:.9g} {z_m:.9g}\n")
        for first, second, third in mesh.faces:
            stream.write(f"f {first + 1} {second + 1} {third + 1}\n")
    return path


def _usd_points(vertices: list[tuple[float, float, float]]) -> str:
    return ",\n                ".join(
        f"({x_m:.9g}, {y_m:.9g}, {z_m:.9g})" for x_m, y_m, z_m in vertices
    )


def _write_usda_mesh(stream, name: str, mesh: _Mesh, color: tuple[float, float, float]) -> None:
    indices = ", ".join(str(index) for face in mesh.faces for index in face)
    counts = ", ".join("3" for _ in mesh.faces)
    stream.write(
        f'''    def Mesh "{name}"
    {{
        uniform token subdivisionScheme = "none"
        point3f[] points = [
                {_usd_points(mesh.vertices)}
        ]
        int[] faceVertexCounts = [{counts}]
        int[] faceVertexIndices = [{indices}]
        color3f[] primvars:displayColor = [({color[0]}, {color[1]}, {color[2]})] (
            interpolation = "constant"
        )
        custom string shepherd:role = "physical-infrastructure"
    }}
'''
    )


# CameraSpecの光学中心を変えずに，ポールとカメラ筐体の共通Meshを生成する．
def write_observation_infrastructure_assets(
    layout: ObservationPointLayout,
    directory: str | Path,
    *,
    pole_radius_m: float = 0.04,
    camera_size_m: tuple[float, float, float] = (0.30, 0.16, 0.12),
) -> GenesisInfrastructureAssets:
    destination = Path(directory).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    pole_height_m = float(layout.metadata.get("mount_profile", {}).get("pole_height_m", 5.0))
    poles = _Mesh()
    housings = _Mesh()
    cameras = {camera.camera_id: camera for camera in layout.camera_layout.cameras}
    for point in layout.points:
        _add_vertical_cylinder(
            poles,
            x_m=point.position.x_m,
            y_m=point.position.y_m,
            bottom_z_m=point.position.z_m - pole_height_m,
            top_z_m=point.position.z_m,
            radius_m=pole_radius_m,
        )
        for camera_id in point.camera_ids:
            camera = cameras[camera_id]
            rotation = camera_rotation_matrix(camera)
            optical_center = np.asarray(
                (camera.position.x_m, camera.position.y_m, camera.position.z_m),
                dtype=np.float64,
            )
            housing_center = optical_center - rotation[:, 0] * (camera_size_m[0] / 2.0)
            _add_oriented_box(
                housings,
                center=housing_center,
                rotation=rotation,
                size=camera_size_m,
            )
    poles_path = _write_obj(destination / "observation_poles.obj", "observation_poles", poles)
    cameras_path = _write_obj(
        destination / "camera_housings.obj", "camera_housings", housings
    )
    usda_path = destination / "infrastructure.usda"
    with usda_path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(
            f'''#usda 1.0
(
    defaultPrim = "ObservationInfrastructure"
    metersPerUnit = 1
    upAxis = "Z"
)

def Xform "ObservationInfrastructure"
{{
    custom string shepherd:layoutId = "{layout.layout_id}"
    custom string shepherd:cameraSource = "CameraSpec optical frames"
    custom string shepherd:selfOcclusionPolicy = "exclude the owning mount from its sensor ray"
'''
        )
        _write_usda_mesh(stream, "Poles", poles, (0.18, 0.18, 0.20))
        _write_usda_mesh(stream, "CameraHousings", housings, (0.05, 0.18, 0.30))
        stream.write("}\n")
    return GenesisInfrastructureAssets(poles_path, cameras_path, usda_path)


# 環境USD・設備USD・検証UI層を他シミュレータでも合成できるSceneへ分離する．
def write_experiment_scene_layers(
    case_directory: str | Path,
    layout_id: str,
) -> GenesisSceneLayers:
    case_path = Path(case_directory).expanduser().resolve()
    scene_directory = case_path / "scenes" / layout_id
    scene_directory.mkdir(parents=True, exist_ok=True)
    debug_path = scene_directory / "debug.usda"
    debug_path.write_text(
        f'''#usda 1.0
(
    defaultPrim = "DebugUI"
    metersPerUnit = 1
    upAxis = "Z"
)

def Xform "DebugUI"
{{
    custom string shepherd:layoutId = "{layout_id}"
    custom string shepherd:role = "viewer-only; excluded from physics and sensor rays"
}}
''',
        encoding="utf-8",
    )
    scene_path = scene_directory / "scene.usda"
    scene_path.write_text(
        f'''#usda 1.0
(
    defaultPrim = "World"
    metersPerUnit = 1
    upAxis = "Z"
    subLayers = [
        @../../environment.usd@,
        @../../observation_point_layouts/{layout_id}/infrastructure.usda@,
        @debug.usda@
    ]
)

def Xform "World"
{{
    custom string shepherd:layoutId = "{layout_id}"
}}
''',
        encoding="utf-8",
    )
    return GenesisSceneLayers(scene_path, debug_path)


def _camera_frustum_vertices(camera: CameraSpec, distance_m: float) -> np.ndarray:
    half_width = np.tan(camera.horizontal_fov_rad / 2.0) * distance_m
    half_height = np.tan(camera.vertical_fov_rad / 2.0) * distance_m
    rotation = camera_rotation_matrix(camera)
    origin = np.asarray(
        (camera.position.x_m, camera.position.y_m, camera.position.z_m), dtype=np.float64
    )
    corners = np.asarray([
        origin + rotation @ np.asarray((distance_m, y_m, z_m))
        for y_m, z_m in (
            (-half_width, -half_height),
            (half_width, -half_height),
            (half_width, half_height),
            (-half_width, half_height),
        )
    ])
    return np.vstack((origin, corners))


def _camera_frustum_mesh(
    cameras: Iterable[CameraSpec],
    *,
    distance_m: float,
    color: tuple[float, float, float, float],
):
    import trimesh

    vertices = []
    faces = []
    face_template = (
        (0, 1, 2), (0, 2, 3), (0, 3, 4), (0, 4, 1),
        (1, 4, 3), (1, 3, 2),
    )
    for camera in cameras:
        offset = len(vertices)
        vertices.extend(_camera_frustum_vertices(camera, distance_m))
        faces.extend(tuple(offset + index for index in face) for face in face_template)
    mesh = trimesh.Trimesh(
        vertices=np.asarray(vertices, dtype=np.float64),
        faces=np.asarray(faces, dtype=np.int64),
        process=False,
    )
    rgba = np.asarray(
        [round(channel * 255.0) for channel in color], dtype=np.uint8
    )
    mesh.visual.face_colors = np.tile(rgba, (len(mesh.faces), 1))
    return mesh


# Genesisの実物Meshへ，FOV・可視結果・ルート等の検証用UIを重ねる．
def draw_genesis_experiment_overlays(
    genesis_scene: GenesisScene,
    layout: ObservationPointLayout,
    *,
    selected_point_id: str | None = None,
    show_fov: bool = False,
    visibility: GenesisVisibilityOverlay | None = None,
    routes: tuple[GenesisRouteOverlay, ...] = (),
    rays: tuple[GenesisValidationRay, ...] = (),
) -> None:
    scene = genesis_scene.scene
    if show_fov:
        selected = layout.points[0] if selected_point_id is None else next(
            point for point in layout.points if point.point_id == selected_point_id
        )
        cameras = {camera.camera_id: camera for camera in layout.camera_layout.cameras}
        selected_camera_ids = set(selected.camera_ids)
        background_cameras = tuple(
            camera
            for camera in layout.camera_layout.cameras
            if camera.camera_id not in selected_camera_ids
        )
        if background_cameras:
            scene.draw_debug_mesh(
                _camera_frustum_mesh(
                    background_cameras,
                    distance_m=VIEWER_FRUSTUM_DISTANCE_M,
                    color=(0.10, 0.45, 1.0, 0.06),
                )
            )
        selected_cameras = tuple(cameras[camera_id] for camera_id in selected.camera_ids)
        scene.draw_debug_mesh(
            _camera_frustum_mesh(
                selected_cameras,
                distance_m=VIEWER_FRUSTUM_DISTANCE_M,
                color=(1.0, 0.12, 0.12, 0.24),
            )
        )
        for camera in selected_cameras:
            optical = np.asarray(
                (camera.position.x_m, camera.position.y_m, camera.position.z_m)
            )
            scene.draw_debug_arrow(
                optical,
                camera_rotation_matrix(camera)[:, 0] * 2.0,
                radius=0.025,
                color=(0.15, 0.75, 1.0, 0.9),
            )
    if visibility is not None:
        if len(visibility.visible_positions):
            scene.draw_debug_points(
                visibility.visible_positions,
                colors=(0.10, 0.90, 0.25, 0.40),
            )
        if len(visibility.hidden_positions):
            scene.draw_debug_points(
                visibility.hidden_positions,
                colors=(0.95, 0.15, 0.12, 0.25),
            )
    for route in routes:
        if len(route.positions) >= 2:
            scene.draw_debug_trajectory(route.positions, radius=0.35, color=route.color)
        for waypoint in route.waypoints:
            scene.draw_debug_sphere(waypoint, radius=1.5, color=(1.0, 0.95, 0.05, 1.0))
    for ray in rays:
        scene.draw_debug_line(
            ray.start,
            ray.end,
            radius=0.06,
            color=(0.15, 1.0, 0.20, 0.95) if ray.visible else (1.0, 0.10, 0.10, 0.95),
        )
