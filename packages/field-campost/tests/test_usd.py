import re
from dataclasses import replace

import numpy as np
import pytest
from shapely.geometry import box, mapping

from field_campost import (
    heightmap_to_mesh,
    plot_environment_3d,
    read_environment_usd,
    validate_usd_with_pxr,
    write_environment_usd,
)
from field_environment import FeatureLayerStatus, PolygonFeatureLayer


def test_usd_round_trip_preserves_mesh_and_cameras(tmp_path, environment_case, camera_layout):
    mesh = heightmap_to_mesh(environment_case.heightmap)
    path = write_environment_usd(mesh, camera_layout, tmp_path / "environment.usd")

    summary = read_environment_usd(path)

    assert summary.meters_per_unit == 1.0
    assert summary.up_axis == "Z"
    assert summary.layout == camera_layout
    np.testing.assert_allclose(summary.terrain_vertices, mesh.vertices)
    np.testing.assert_array_equal(summary.terrain_faces, mesh.faces)


def test_usd_does_not_overwrite_implicitly(tmp_path, environment_case, camera_layout):
    mesh = heightmap_to_mesh(environment_case.heightmap)
    path = write_environment_usd(mesh, camera_layout, tmp_path / "environment.usd")

    with pytest.raises(FileExistsError):
        write_environment_usd(mesh, camera_layout, path)


def test_pxr_validation_is_explicitly_optional(tmp_path, environment_case, camera_layout):
    mesh = heightmap_to_mesh(environment_case.heightmap)
    path = write_environment_usd(mesh, camera_layout, tmp_path / "environment.usd")

    try:
        validate_usd_with_pxr(path)
    except RuntimeError as error:
        assert "usd-core" in str(error)


def test_usd_keeps_terrain_forest_and_buildings_as_separate_elements(
    tmp_path, environment_case, camera_layout
):
    coordinate_system_name = environment_case.case_spec.coordinate_system.name
    forest = PolygonFeatureLayer(
        layer_type="forest",
        status=FeatureLayerStatus.AVAILABLE,
        coordinate_system_name=coordinate_system_name,
        features=(
            {"type": "Feature", "geometry": mapping(box(10, 10, 20, 20)), "properties": {}},
        ),
    )
    buildings = PolygonFeatureLayer(
        layer_type="buildings",
        status=FeatureLayerStatus.AVAILABLE,
        coordinate_system_name=coordinate_system_name,
        features=(
            {
                "type": "Feature",
                "geometry": mapping(box(20, 10, 30, 20)),
                "properties": {"height_m": 8.0},
            },
        ),
    )
    facility_buildings = PolygonFeatureLayer(
        layer_type="facility_buildings",
        status=FeatureLayerStatus.AVAILABLE,
        coordinate_system_name=coordinate_system_name,
        features=(
            {
                "type": "Feature",
                "geometry": mapping(box(20, 10, 25, 20)),
                "properties": {"height_m": 8.0},
            },
        ),
    )
    mesh = heightmap_to_mesh(environment_case.heightmap)
    path = write_environment_usd(
        mesh,
        camera_layout,
        tmp_path / "features.usd",
        heightmap=environment_case.heightmap,
        forest=forest,
        buildings=buildings,
        facility_buildings=facility_buildings,
    )
    document = path.read_text(encoding="utf-8")
    assert 'def Scope "Forest"' in document
    assert 'def Mesh "Forest_00000"' in document
    assert 'def Cube "Forest_00000"' not in document
    assert 'def Scope "Buildings"' in document
    assert 'def Mesh "Buildings_00000"' in document
    assert 'def Scope "FacilityBuildings"' in document
    assert 'def Mesh "FacilityBuildings_00000"' in document
    assert 'shepherd:sourceLayer = "facility_buildings"' in document
    assert "custom double shepherd:heightM = 8" in document
    assert "primvars:displayColor" in document
    assert 'def Mesh "Terrain"' in document
    face_count_arrays = re.findall(
        r"int\[\] faceVertexCounts\s*=\s*\[(.*?)\]", document, re.DOTALL
    )
    assert face_count_arrays
    assert all(
        set(np.fromstring(values.replace("\n", ""), sep=",", dtype=np.int32)) == {3}
        for values in face_count_arrays
    )


def test_environment_3d_preview_can_be_rendered(environment_case, camera_layout):
    figure, axis = plot_environment_3d(environment_case, camera_layout)
    assert axis.get_title() == "Terrain and extruded building footprints"
    figure.canvas.draw()


def test_environment_3d_preview_can_focus_on_facilities(environment_case, camera_layout):
    coordinate_system_name = environment_case.case_spec.coordinate_system.name
    facility_buildings = PolygonFeatureLayer(
        layer_type="facility_buildings",
        status=FeatureLayerStatus.AVAILABLE,
        coordinate_system_name=coordinate_system_name,
        features=(
            {
                "type": "Feature",
                "geometry": mapping(box(20, 10, 30, 20)),
                "properties": {"height_m": 8.0},
            },
        ),
    )
    focused_case = replace(environment_case, facility_buildings=facility_buildings)
    figure, axis = plot_environment_3d(
        focused_case,
        camera_layout,
        focus_on_facilities=True,
        focus_padding_m=5.0,
    )
    assert axis.get_title() == "Facility buildings and local terrain"
    assert axis.get_xlim() == pytest.approx((15.0, 35.0))
    figure.canvas.draw()
