from __future__ import annotations

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


def inspect_genesis() -> GenesisStatus:
    if util.find_spec("genesis") is None:
        return GenesisStatus(False, None, False, "genesis-world is not installed")
    import genesis as gs

    version = getattr(gs, "__version__", None)
    usd_api_available = hasattr(gs, "morphs") and hasattr(gs.morphs, "USD")
    pxr_available = util.find_spec("pxr") is not None
    if not usd_api_available:
        return GenesisStatus(True, version, False, "installed Genesis has no gs.morphs.USD API")
    if not pxr_available:
        return GenesisStatus(True, version, False, "usd-core (pxr) is not installed")
    return GenesisStatus(True, version, True, "Genesis USD import dependencies are available")


def load_usd_scene(
    path: str | Path,
    *,
    backend: str = "cpu",
    show_viewer: bool = False,
) -> tuple[Any, list[Any]]:
    status = inspect_genesis()
    if not status.usd_support_available:
        raise RuntimeError(status.reason)
    import genesis as gs

    backend_value = getattr(gs, backend)
    gs.init(backend=backend_value)
    scene = gs.Scene(show_viewer=show_viewer)
    entities = scene.add_stage(
        morph=gs.morphs.USD(
            file=str(Path(path).resolve()),
            fixed=True,
            convexify=False,
            decimate=False,
            align=False,
        )
    )
    scene.build()
    return scene, entities
