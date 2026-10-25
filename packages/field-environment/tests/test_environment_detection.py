from __future__ import annotations

from dataclasses import replace

import numpy as np

from field_environment import (
    FeatureLayerStatus,
    PolygonFeatureLayer,
    RasterLayer,
    create_feature_layer,
    detect_forest,
    detect_farm_complexes,
    detect_pasture_candidates,
    load_case,
    save_case,
)
from shapely.geometry import box, mapping, shape


def test_forest_and_pasture_candidates_are_distinct(environment_case) -> None:
    values = np.full(environment_case.heightmap.values.shape, 10, dtype=np.uint8)
    values[2:8, 3:12] = 30
    landcover = RasterLayer(
        layer_type="landcover",
        values=values,
        grid=environment_case.heightmap.grid,
        source="test",
        attribution="test",
        source_resolution_m=10.0,
    )
    buildings = create_feature_layer(
        layer_type="buildings",
        status=FeatureLayerStatus.EMPTY,
        coordinate_system_name=environment_case.case_spec.coordinate_system.name,
    )
    forest = detect_forest(
        landcover,
        coordinate_system_name=environment_case.case_spec.coordinate_system.name,
        minimum_area_m2=100.0,
    )
    pasture = detect_pasture_candidates(
        landcover,
        np.zeros_like(environment_case.heightmap.values),
        coordinate_system_name=environment_case.case_spec.coordinate_system.name,
        buildings=buildings,
        maximum_slope_deg=20.0,
        minimum_area_m2=100.0,
    )
    assert forest.status is FeatureLayerStatus.AVAILABLE
    assert pasture.status is FeatureLayerStatus.AVAILABLE
    assert all(
        feature["properties"]["classification"]
        == "candidate_not_confirmed_property_boundary"
        for feature in pasture.features
    )


def test_detection_layers_round_trip(tmp_path, environment_case) -> None:
    grid = environment_case.heightmap.grid
    landcover = RasterLayer(
        layer_type="landcover",
        values=np.full(environment_case.heightmap.values.shape, 30, dtype=np.uint8),
        grid=grid,
        source="ESA WorldCover 2021 v200",
        attribution="test attribution",
        source_resolution_m=10.0,
    )
    imagery = RasterLayer(
        layer_type="imagery",
        values=np.full(environment_case.heightmap.values.shape + (3,), 127, dtype=np.uint8),
        grid=grid,
        source="GSI seamlessphoto",
        attribution="test attribution",
        source_resolution_m=1.0,
    )
    forest = detect_forest(
        landcover,
        coordinate_system_name=environment_case.case_spec.coordinate_system.name,
    )
    pasture = detect_pasture_candidates(
        landcover,
        np.zeros_like(environment_case.heightmap.values),
        coordinate_system_name=environment_case.case_spec.coordinate_system.name,
        buildings=None,
        minimum_area_m2=100.0,
    )
    environment_refs = environment_case.case_spec.environment.model_copy(
        update={"landcover": "landcover.tif"}
    )
    updated = replace(
        environment_case,
        case_spec=environment_case.case_spec.model_copy(
            update={"environment": environment_refs}
        ),
        imagery=imagery,
        landcover=landcover,
        forest=forest,
        pasture_candidates=pasture,
    )
    save_case(updated, tmp_path)
    restored = load_case(tmp_path, updated.case_spec.case_id)
    np.testing.assert_array_equal(restored.imagery.values, imagery.values)
    np.testing.assert_array_equal(restored.landcover.values, landcover.values)
    assert restored.forest.status is FeatureLayerStatus.EMPTY
    assert restored.pasture_candidates.status is FeatureLayerStatus.AVAILABLE


def test_farm_complex_connects_open_blocks_and_partitions_buildings(environment_case) -> None:
    coordinate_system_name = environment_case.case_spec.coordinate_system.name
    pasture = PolygonFeatureLayer(
        layer_type="pasture_candidates",
        status=FeatureLayerStatus.AVAILABLE,
        coordinate_system_name=coordinate_system_name,
        features=(
            {
                "type": "Feature",
                "geometry": mapping(box(20, 20, 80, 100)),
                "properties": {},
            },
            {
                "type": "Feature",
                "geometry": mapping(box(100, 20, 160, 100)),
                "properties": {},
            },
        ),
    )
    buildings = PolygonFeatureLayer(
        layer_type="buildings",
        status=FeatureLayerStatus.AVAILABLE,
        coordinate_system_name=coordinate_system_name,
        assumed_height_m=5.0,
        features=(
            {
                "type": "Feature",
                "geometry": mapping(box(70, 45, 78, 55)),
                "properties": {},
            },
            {
                "type": "Feature",
                "geometry": mapping(box(180, 0, 190, 10)),
                "properties": {},
            },
        ),
    )
    result = detect_farm_complexes(
        pasture,
        environment_case.heightmap.grid,
        coordinate_system_name=coordinate_system_name,
        buildings=buildings,
        anchor_x_m=50,
        anchor_y_m=60,
        bridge_gap_m=30,
        facility_maximum_distance_m=20,
        monitoring_buffer_m=5,
        minimum_area_m2=100,
    )
    selected = shape(result.monitoring_area.features[0]["geometry"])
    assert selected.covers(box(20, 20, 80, 100).centroid)
    assert selected.covers(box(100, 20, 160, 100).centroid)
    assert len(result.facility_buildings.features) == 1
    assert len(result.excluded_buildings.features) == 1
    assert result.selected_candidate_id == 1
    assert len(selected.interiors) == 0


def test_detection_config_rejects_unknown_connectivity_parameter() -> None:
    from field_environment import PastureDetectionConfig

    with np.testing.assert_raises(ValueError):
        PastureDetectionConfig.model_validate({"unknown_bridge_rule": 5})
