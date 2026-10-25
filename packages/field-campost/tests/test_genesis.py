from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from shapely.geometry import Polygon, box, mapping

import field_campost.genesis as genesis_module
from field_campost import (
    GenesisMeshSource,
    GenesisScene,
    GenesisStatus,
    GenesisViewerOptions,
    build_genesis_mesh_scene,
    build_genesis_scene,
    inspect_genesis,
    run_genesis_viewer,
    write_genesis_mesh_assets,
)
from field_environment import FeatureLayerStatus, PolygonFeatureLayer


def test_genesis_status_is_reportable_without_optional_dependency():
    status = inspect_genesis()

    assert isinstance(status.installed, bool)
    assert isinstance(status.usd_support_available, bool)
    assert isinstance(status.mesh_support_available, bool)
    assert status.reason


def test_viewer_options_reject_invalid_values():
    with pytest.raises(ValueError, match="resolution"):
        GenesisViewerOptions(resolution=(0, 720))
    with pytest.raises(ValueError, match="camera_fov_deg"):
        GenesisViewerOptions(camera_fov_deg=180.0)


def test_build_genesis_scene_uses_visual_only_usd(monkeypatch, tmp_path):
    usd_path = tmp_path / "environment.usd"
    usd_path.write_text("#usda 1.0\n", encoding="utf-8")
    calls = {}

    class FakeScene:
        def __init__(self, **kwargs):
            calls["scene"] = kwargs
            self.viewer = None

        def add_stage(self, **kwargs):
            calls["stage"] = kwargs
            return ["terrain", "forest", "buildings"]

        def build(self):
            calls["built"] = True

    class FakeUsd:
        def __init__(self, **kwargs):
            self.parameters = kwargs

    fake_genesis = SimpleNamespace(
        __version__="test",
        cpu="cpu-backend",
        gpu="gpu-backend",
        cuda="cuda-backend",
        init=lambda **kwargs: calls.setdefault("init", kwargs),
        Scene=FakeScene,
        options=SimpleNamespace(
            ViewerOptions=lambda **kwargs: SimpleNamespace(**kwargs),
            VisOptions=lambda **kwargs: SimpleNamespace(**kwargs),
        ),
        morphs=SimpleNamespace(USD=FakeUsd),
    )
    monkeypatch.setitem(sys.modules, "genesis", fake_genesis)
    monkeypatch.setattr(
        genesis_module,
        "inspect_genesis",
        lambda: GenesisStatus(True, "test", True, "available"),
    )

    result = build_genesis_scene(
        usd_path,
        backend="gpu",
        show_viewer=True,
        viewer_options=GenesisViewerOptions(resolution=(800, 600)),
        collision=False,
    )

    assert result.usd_path == usd_path
    assert result.entities == ("terrain", "forest", "buildings")
    assert calls["init"] == {"backend": "gpu-backend"}
    assert calls["scene"]["show_viewer"] is True
    assert calls["scene"]["viewer_options"].res == (800, 600)
    assert calls["stage"]["vis_mode"] == "visual"
    assert calls["stage"]["morph"].parameters["collision"] is False
    assert calls["built"] is True


def test_run_genesis_viewer_waits_until_window_closes(monkeypatch, tmp_path):
    states = iter((True, False))
    viewer = SimpleNamespace(is_alive=lambda: next(states))
    scene = GenesisScene(
        scene=SimpleNamespace(viewer=viewer),
        entities=(),
        usd_path=Path(tmp_path / "environment.usd"),
        backend="cpu",
    )
    sleeps = []
    monkeypatch.setattr(genesis_module.time, "sleep", sleeps.append)

    run_genesis_viewer(scene, poll_interval_s=0.25)

    assert sleeps == [0.25]


def test_genesis_mesh_assets_keep_environment_layers_separate(tmp_path, environment_case):
    assets = write_genesis_mesh_assets(environment_case, tmp_path / "viewer")

    assert assets.terrain.is_file()
    assert assets.terrain.read_text(encoding="utf-8").startswith("o terrain\n")
    assert assets.forest is None
    assert assets.buildings is None
    assert assets.facility_buildings is None


def test_genesis_mesh_assets_triangulate_layers_and_separate_facilities(
    tmp_path, environment_case
):
    coordinate_system_name = environment_case.case_spec.coordinate_system.name
    forest_polygon = Polygon(
        shell=((2, 2), (38, 2), (38, 28), (20, 20), (2, 28)),
        holes=(((8, 8), (14, 8), (14, 14), (8, 14)),),
    )
    forest = PolygonFeatureLayer(
        layer_type="forest",
        status=FeatureLayerStatus.AVAILABLE,
        coordinate_system_name=coordinate_system_name,
        assumed_height_m=5.0,
        features=(
            {"type": "Feature", "geometry": mapping(forest_polygon), "properties": {}},
        ),
    )
    facility_feature = {
        "type": "Feature",
        "geometry": mapping(box(20, 10, 25, 15)),
        "properties": {"height_m": 7.0},
    }
    other_feature = {
        "type": "Feature",
        "geometry": mapping(box(30, 10, 35, 15)),
        "properties": {"height_m": 6.0},
    }
    buildings = PolygonFeatureLayer(
        layer_type="buildings",
        status=FeatureLayerStatus.AVAILABLE,
        coordinate_system_name=coordinate_system_name,
        features=(facility_feature, other_feature),
    )
    facility_buildings = PolygonFeatureLayer(
        layer_type="facility_buildings",
        status=FeatureLayerStatus.AVAILABLE,
        coordinate_system_name=coordinate_system_name,
        features=(facility_feature,),
    )
    layered_case = replace(
        environment_case,
        forest=forest,
        buildings=buildings,
        facility_buildings=facility_buildings,
    )

    assets = write_genesis_mesh_assets(layered_case, tmp_path / "viewer")

    assert assets.forest is not None
    assert assets.buildings is not None
    assert assets.facility_buildings is not None
    for path in (assets.forest, assets.buildings, assets.facility_buildings):
        faces = [line.split()[1:] for line in path.read_text().splitlines() if line.startswith("f ")]
        assert faces
        assert all(len(face) == 3 for face in faces)


def test_build_genesis_mesh_scene_adds_each_visual_layer(monkeypatch, tmp_path):
    terrain_path = tmp_path / "terrain.obj"
    forest_path = tmp_path / "forest.obj"
    terrain_path.write_text("o terrain\nv 0 0 0\n", encoding="utf-8")
    forest_path.write_text("o forest\nv 0 0 0\n", encoding="utf-8")
    calls = {"entities": []}

    class FakeScene:
        def __init__(self, **kwargs):
            calls["scene"] = kwargs
            self.viewer = None

        def add_entity(self, **kwargs):
            calls["entities"].append(kwargs)
            return kwargs["name"]

        def build(self):
            calls["built"] = True

    class FakeMesh:
        def __init__(self, **kwargs):
            self.parameters = kwargs

    fake_genesis = SimpleNamespace(
        cpu="cpu-backend",
        gpu="gpu-backend",
        cuda="cuda-backend",
        init=lambda **kwargs: calls.setdefault("init", kwargs),
        Scene=FakeScene,
        options=SimpleNamespace(
            ViewerOptions=lambda **kwargs: SimpleNamespace(**kwargs),
            VisOptions=lambda **kwargs: SimpleNamespace(**kwargs),
        ),
        morphs=SimpleNamespace(Mesh=FakeMesh),
        surfaces=SimpleNamespace(Default=lambda **kwargs: SimpleNamespace(**kwargs)),
    )
    monkeypatch.setitem(sys.modules, "genesis", fake_genesis)
    monkeypatch.setattr(
        genesis_module,
        "inspect_genesis",
        lambda: GenesisStatus(True, "test", False, "mesh available", True),
    )

    result = build_genesis_mesh_scene(
        (
            GenesisMeshSource("terrain", terrain_path, (0.4, 0.3, 0.2)),
            GenesisMeshSource("forest", forest_path, (0.0, 0.3, 0.0)),
        ),
        backend="cpu",
        collision=False,
    )

    assert result.entities == ("terrain", "forest")
    assert result.asset_paths == (terrain_path, forest_path)
    assert [call["name"] for call in calls["entities"]] == ["terrain", "forest"]
    assert calls["entities"][0]["morph"].parameters["collision"] is False
    assert calls["built"] is True
