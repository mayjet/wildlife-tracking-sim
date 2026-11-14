from __future__ import annotations

import time
from dataclasses import dataclass
from importlib import util
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GenesisStatus:
    installed: bool
    version: str | None
    usd_support_available: bool
    reason: str
    mesh_support_available: bool = False


@dataclass(frozen=True)
class GenesisViewerOptions:
    resolution: tuple[int, int] = (1280, 720)
    camera_position: tuple[float, float, float] = (3.5, 0.5, 2.5)
    camera_look_at: tuple[float, float, float] = (0.0, 0.0, 0.5)
    camera_fov_deg: float = 45.0
    refresh_rate_hz: int = 30
    show_world_frame: bool = True
    world_frame_size_m: float = 100.0

    def __post_init__(self) -> None:
        if self.resolution[0] <= 0 or self.resolution[1] <= 0:
            raise ValueError("viewer resolution must be positive")
        if not 1.0 <= self.camera_fov_deg < 180.0:
            raise ValueError("camera_fov_deg must be in [1, 180)")
        if self.refresh_rate_hz <= 0:
            raise ValueError("refresh_rate_hz must be positive")
        if self.world_frame_size_m <= 0.0:
            raise ValueError("world_frame_size_m must be positive")


@dataclass(frozen=True)
class GenesisScene:
    scene: Any
    entities: tuple[Any, ...]
    usd_path: Path | None
    backend: str
    asset_paths: tuple[Path, ...] = ()


@dataclass(frozen=True)
class GenesisMeshSource:
    name: str
    path: Path
    color: tuple[float, float, float]
    opacity: float = 1.0
    double_sided: bool = True


def inspect_genesis() -> GenesisStatus:
    if util.find_spec("genesis") is None:
        return GenesisStatus(False, None, False, "genesis-world is not installed", False)
    import genesis as gs

    version = getattr(gs, "__version__", None)
    usd_api_available = hasattr(gs, "morphs") and hasattr(gs.morphs, "USD")
    mesh_api_available = hasattr(gs, "morphs") and hasattr(gs.morphs, "Mesh")
    pxr_available = util.find_spec("pxr") is not None
    if not mesh_api_available:
        return GenesisStatus(
            True,
            version,
            False,
            "installed Genesis has no gs.morphs.Mesh API",
            False,
        )
    if not usd_api_available:
        return GenesisStatus(
            True,
            version,
            False,
            "Genesis mesh import is available; gs.morphs.USD is unavailable",
            True,
        )
    if not pxr_available:
        return GenesisStatus(
            True,
            version,
            False,
            "Genesis mesh import is available; usd-core (pxr) is not installed",
            True,
        )
    return GenesisStatus(
        True,
        version,
        True,
        "Genesis mesh and USD import dependencies are available",
        True,
    )


def _resolve_backend(genesis_module: Any, backend: str) -> Any:
    normalized = backend.lower()
    aliases = {"cuda": "cuda", "gpu": "gpu", "cpu": "cpu"}
    attribute = aliases.get(normalized)
    if attribute is None or not hasattr(genesis_module, attribute):
        choices = ", ".join(sorted(aliases))
        raise ValueError(f"unsupported Genesis backend {backend!r}; choose one of: {choices}")
    return getattr(genesis_module, attribute)


def _create_scene(genesis_module: Any, options: GenesisViewerOptions, show_viewer: bool) -> Any:
    return genesis_module.Scene(
        viewer_options=genesis_module.options.ViewerOptions(
            res=options.resolution,
            camera_pos=options.camera_position,
            camera_lookat=options.camera_look_at,
            camera_up=(0.0, 0.0, 1.0),
            camera_fov=options.camera_fov_deg,
            refresh_rate=options.refresh_rate_hz,
        ),
        vis_options=genesis_module.options.VisOptions(
            show_world_frame=options.show_world_frame,
            world_frame_size=options.world_frame_size_m,
            show_link_frame=False,
            show_cameras=True,
            shadow=True,
            plane_reflection=False,
            ambient_light=(0.35, 0.35, 0.35),
        ),
        show_viewer=show_viewer,
    )


# USD環境をGenesis Sceneへ読み込み，Viewerと将来のSimulationで共有できる形にする．
def build_genesis_scene(
    path: str | Path,
    *,
    backend: str = "gpu",
    show_viewer: bool = False,
    viewer_options: GenesisViewerOptions | None = None,
    collision: bool = False,
) -> GenesisScene:
    usd_path = Path(path).expanduser().resolve()
    if not usd_path.is_file():
        raise FileNotFoundError(f"USD environment does not exist: {usd_path}")
    status = inspect_genesis()
    if not status.usd_support_available:
        raise RuntimeError(status.reason)
    import genesis as gs

    options = viewer_options or GenesisViewerOptions()
    gs.init(backend=_resolve_backend(gs, backend))
    scene = _create_scene(gs, options, show_viewer)
    entities = scene.add_stage(
        morph=gs.morphs.USD(
            file=str(usd_path),
            fixed=True,
            visualization=True,
            collision=collision,
            convexify=False,
            decimate=False,
            align=False,
        ),
        vis_mode="visual",
    )
    scene.build()
    return GenesisScene(
        scene=scene,
        entities=tuple(entities),
        usd_path=usd_path,
        backend=backend,
        asset_paths=(usd_path,),
    )


# OBJ派生Meshを使い，USDランタイムに依存せずCaseをGenesisへ読み込む．
def build_genesis_mesh_scene(
    sources: tuple[GenesisMeshSource, ...],
    *,
    backend: str = "gpu",
    show_viewer: bool = False,
    viewer_options: GenesisViewerOptions | None = None,
    collision: bool = False,
) -> GenesisScene:
    if not sources:
        raise ValueError("at least one Genesis mesh source is required")
    resolved_sources = tuple(
        GenesisMeshSource(
            source.name,
            source.path.expanduser().resolve(),
            source.color,
            source.opacity,
            source.double_sided,
        )
        for source in sources
    )
    missing = [source.path for source in resolved_sources if not source.path.is_file()]
    if missing:
        raise FileNotFoundError(f"Genesis mesh asset does not exist: {missing[0]}")
    status = inspect_genesis()
    if not status.mesh_support_available:
        raise RuntimeError(status.reason)
    import genesis as gs

    options = viewer_options or GenesisViewerOptions()
    gs.init(backend=_resolve_backend(gs, backend))
    scene = _create_scene(gs, options, show_viewer)
    entities = []
    for source in resolved_sources:
        entity = scene.add_entity(
            morph=gs.morphs.Mesh(
                file=str(source.path),
                fixed=True,
                visualization=True,
                collision=collision,
                convexify=False,
                decimate=False,
                align=False,
                file_meshes_are_zup=True,
            ),
            surface=gs.surfaces.Default(
                color=source.color,
                opacity=source.opacity,
                roughness=0.9,
                metallic=0.0,
                double_sided=source.double_sided,
            ),
            vis_mode="visual",
            name=source.name,
        )
        entities.append(entity)
    scene.build()
    return GenesisScene(
        scene=scene,
        entities=tuple(entities),
        usd_path=None,
        backend=backend,
        asset_paths=tuple(source.path for source in resolved_sources),
    )


# Viewerウィンドウが閉じられるまで静的な実験環境を表示し続ける．
def run_genesis_viewer(genesis_scene: GenesisScene, *, poll_interval_s: float = 0.1) -> None:
    if poll_interval_s <= 0.0:
        raise ValueError("poll_interval_s must be positive")
    viewer = getattr(genesis_scene.scene, "viewer", None)
    if viewer is None:
        raise RuntimeError("Genesis Scene was created without an interactive viewer")
    try:
        while viewer.is_alive():
            time.sleep(poll_interval_s)
    except KeyboardInterrupt:
        stop = getattr(viewer, "stop", None)
        if callable(stop):
            stop()


def load_usd_scene(
    path: str | Path,
    *,
    backend: str = "cpu",
    show_viewer: bool = False,
) -> tuple[Any, list[Any]]:
    genesis_scene = build_genesis_scene(
        path,
        backend=backend,
        show_viewer=show_viewer,
        collision=True,
    )
    return genesis_scene.scene, list(genesis_scene.entities)
