from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

import yaml
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform
from shepherd_contracts import FarmBoundarySpec

from .case.models import EnvironmentCase, ProcessingStep, SourceArtifact
from .case.writer import resolve_case_path, save_case, update_case
from .config import (
    CaseMode,
    EnvironmentConfig,
    EnvironmentDetectionConfig,
    EnvironmentFeaturesConfig,
    FeatureInputConfig,
    FileTerrainConfig,
    GeographicTerrainConfig,
    SyntheticTerrainConfig,
    config_digest,
    load_environment_config,
)
from .factory import create_case_from_terrain_source, create_synthetic_case
from .farm import FarmBoundary, build_monitoring_boundary, detect_farm_complexes
from .features import (
    FeatureLayerStatus,
    PolygonFeatureLayer,
    create_feature_layer,
    generate_traversability,
    load_polygon_feature_layer,
)
from .environment_detection import detect_forest, detect_pasture_candidates
from .repository import find_repository_root, resolve_repository_path
from .scene import apply_scene_config
from .sources import (
    acquire_alos_aw3d30,
    acquire_detection_sources,
    acquire_gsi_elevation,
    import_geotiff,
)
from .terrain import TerrainGridSpec


@dataclass(frozen=True)
class EnvironmentWorkflowResult:
    config: EnvironmentConfig
    config_path: Path
    environment_case: EnvironmentCase
    case_directory: Path
    action: CaseMode


def _synthetic_parameters(config: SyntheticTerrainConfig) -> dict[str, float | int]:
    parameters = dict(config.parameters)
    if config.type == "flat":
        parameters.setdefault("elevation_m", 0.0)
    elif config.type == "hills":
        parameters.setdefault("base_elevation_m", 0.0)
        parameters.setdefault("hill_count", 6)
        parameters.setdefault("hill_height_m", config.relief_m)
        parameters.setdefault("hill_radius_m", config.size_m / 6.0)
    elif config.type == "valley":
        parameters.setdefault("base_elevation_m", config.relief_m)
        parameters.setdefault("depth_m", config.relief_m)
        parameters.setdefault("width_m", config.size_m / 5.0)
    elif config.type == "ridge":
        parameters.setdefault("base_elevation_m", 0.0)
        parameters.setdefault("height_m", config.relief_m)
        parameters.setdefault("width_m", config.size_m / 5.0)
    return parameters


def _farm_boundary(config, environment_case: EnvironmentCase) -> FarmBoundary:
    coordinate_system = environment_case.case_spec.coordinate_system
    if config.boundary_type == "rectangle":
        half = config.size_m / 2.0
        boundary = FarmBoundary.rectangle(
            min_x_m=-half,
            min_y_m=-half,
            max_x_m=half,
            max_y_m=half,
            coordinate_system_name=coordinate_system.name,
        )
    else:
        path = resolve_repository_path(config.path)
        document = json.loads(path.read_text(encoding="utf-8"))
        features = document.get("features", [])
        if len(features) != 1:
            raise ValueError("farm boundary input must contain exactly one Polygon")
        geometry = shape(features[0].get("geometry"))
        input_name = (features[0].get("properties") or {}).get("coordinate_system")
        crs_name = ((document.get("crs") or {}).get("properties") or {}).get("name")
        if input_name != coordinate_system.name:
            if not crs_name or "4326" not in crs_name or not coordinate_system.projected_crs:
                raise ValueError("farm boundary must use Case coordinates or EPSG:4326")
            transformer = Transformer.from_crs(
                "EPSG:4326", coordinate_system.projected_crs, always_xy=True
            )
            geometry = transform(transformer.transform, geometry)
        boundary = FarmBoundary(
            polygon=geometry,
            coordinate_system_name=coordinate_system.name,
        )
    boundary.validate_within(environment_case.heightmap.bounds)
    return boundary


def _feature_layer(
    feature_config: FeatureInputConfig,
    *,
    layer_type: str,
    environment_case: EnvironmentCase,
) -> PolygonFeatureLayer:
    status = FeatureLayerStatus(feature_config.status)
    if status is FeatureLayerStatus.AVAILABLE:
        return load_polygon_feature_layer(
            resolve_repository_path(feature_config.path),
            layer_type=layer_type,
            coordinate_system=environment_case.case_spec.coordinate_system,
            source=feature_config.source,
            assumed_height_m=feature_config.assumed_height_m,
        )
    return create_feature_layer(
        layer_type=layer_type,
        status=status,
        coordinate_system_name=environment_case.case_spec.coordinate_system.name,
        source=feature_config.source,
        assumed_height_m=feature_config.assumed_height_m,
    )


def _apply_features(
    environment_case: EnvironmentCase,
    features_config: EnvironmentFeaturesConfig,
) -> EnvironmentCase:
    buildings = _feature_layer(
        features_config.buildings,
        layer_type="buildings",
        environment_case=environment_case,
    )
    forest = _feature_layer(
        features_config.forest,
        layer_type="forest",
        environment_case=environment_case,
    )
    traversability = generate_traversability(
        environment_case.heightmap.values,
        environment_case.heightmap.grid,
        buildings=buildings,
        forest=forest,
        difficult_slope_deg=features_config.difficult_slope_deg,
    )
    environment_refs = environment_case.case_spec.environment.model_copy(
        update={"traversability": "traversability.tif"}
    )
    case_spec = environment_case.case_spec.model_copy(
        update={"environment": environment_refs}
    )
    return replace(
        environment_case,
        case_spec=case_spec,
        buildings=buildings,
        forest=forest,
        traversability=traversability,
    )


def _apply_detection(
    environment_case: EnvironmentCase,
    detection_config: EnvironmentDetectionConfig,
    *,
    working_directory: Path,
    progress: Callable[[str], None] | None = None,
) -> EnvironmentCase:
    if progress is not None:
        progress("[1/5] 衛星画像，土地被覆，建物データを取得しています．")
    result = acquire_detection_sources(
        imagery_config=detection_config.imagery,
        landcover_config=detection_config.landcover,
        building_config=detection_config.buildings,
        heightmap=environment_case.heightmap,
        coordinate_system=environment_case.case_spec.coordinate_system,
        provenance=environment_case.provenance,
        working_directory=working_directory,
    )
    if progress is not None:
        progress("[2/5] 森林と開放地候補を分類しています．")
    forest = detect_forest(
        result.landcover,
        coordinate_system_name=environment_case.case_spec.coordinate_system.name,
        classes=detection_config.forest_classes,
        minimum_area_m2=detection_config.forest_minimum_area_m2,
    )
    pasture_candidates = detect_pasture_candidates(
        result.landcover,
        environment_case.heightmap.values,
        coordinate_system_name=environment_case.case_spec.coordinate_system.name,
        buildings=result.buildings,
        open_classes=detection_config.pasture.open_landcover_classes,
        maximum_slope_deg=detection_config.pasture.maximum_slope_deg,
        minimum_area_m2=detection_config.pasture.minimum_area_m2,
    )
    if progress is not None:
        progress("[3/5] 開放地の連続性から牧場候補の塊を抽出しています．")
    farm_complex = detect_farm_complexes(
        pasture_candidates,
        environment_case.heightmap.grid,
        coordinate_system_name=environment_case.case_spec.coordinate_system.name,
        buildings=result.buildings,
        anchor_x_m=detection_config.pasture.selection_anchor_x_m,
        anchor_y_m=detection_config.pasture.selection_anchor_y_m,
        bridge_gap_m=detection_config.pasture.bridge_gap_m,
        enclosed_hole_maximum_area_m2=(
            detection_config.pasture.enclosed_hole_maximum_area_m2
        ),
        facility_maximum_distance_m=(
            detection_config.pasture.facility_maximum_distance_m
        ),
        monitoring_closing_m=detection_config.pasture.monitoring_closing_m,
        monitoring_buffer_m=detection_config.pasture.monitoring_buffer_m,
        minimum_area_m2=detection_config.pasture.minimum_area_m2,
    )
    traversability = generate_traversability(
        environment_case.heightmap.values,
        environment_case.heightmap.grid,
        buildings=result.buildings,
        forest=forest,
        difficult_slope_deg=detection_config.difficult_slope_deg,
    )
    environment_refs = environment_case.case_spec.environment.model_copy(
        update={"landcover": "landcover.tif", "traversability": "traversability.tif"}
    )
    case_spec = environment_case.case_spec.model_copy(
        update={"environment": environment_refs}
    )
    farm_boundary = environment_case.farm_boundary
    if detection_config.pasture.confirm_monitoring_boundary:
        if progress is not None:
            progress("[4/5] 選択した牧場候補を実験用の監視範囲として確定しています．")
        farm_boundary = build_monitoring_boundary(farm_complex.monitoring_area)
        case_spec = case_spec.model_copy(
            update={
                "farm_boundary": FarmBoundarySpec(
                    data_ref="farm_boundary.geojson",
                    bounds=farm_boundary.bounds,
                )
            }
        )
    elif progress is not None:
        progress("[4/5] 監視範囲は候補として保存し，牧場境界は変更しません．")

    forest_area_m2 = sum(
        float((feature.get("properties") or {}).get("area_m2", 0.0))
        for feature in forest.features
    )
    open_area_m2 = sum(
        float((feature.get("properties") or {}).get("area_m2", 0.0))
        for feature in pasture_candidates.features
    )
    processing_steps = environment_case.processing_steps + (
        ProcessingStep(
            step_id="acquire_detection_sources",
            status="completed",
            description="衛星画像，土地被覆，建物外周を取得してCase座標へ変換した．",
            inputs=(
                environment_case.provenance.dataset
                if environment_case.provenance is not None
                else "terrain",
            ),
            outputs=("imagery_rgb.tif", "landcover.tif", "buildings.geojson"),
            parameters={
                "imagery": detection_config.imagery.model_dump(mode="json"),
                "landcover": detection_config.landcover.model_dump(mode="json"),
                "buildings": detection_config.buildings.model_dump(mode="json"),
            },
            metrics={
                "imagery_cell_size_m": result.imagery.grid.cell_size_m,
                "landcover_cell_size_m": result.landcover.grid.cell_size_m,
                "building_count": len(result.buildings.features),
            },
        ),
        ProcessingStep(
            step_id="classify_forest_open_land",
            status="completed",
            description="土地被覆，傾斜，建物から森林と開放地候補を分類した．",
            inputs=("landcover.tif", "terrain.tif", "buildings.geojson"),
            outputs=("forest.geojson", "pasture_candidates.geojson"),
            parameters={
                "forest_classes": list(detection_config.forest_classes),
                "forest_minimum_area_m2": detection_config.forest_minimum_area_m2,
                "pasture": detection_config.pasture.model_dump(mode="json"),
            },
            metrics={
                "forest_polygon_count": len(forest.features),
                "forest_area_m2": forest_area_m2,
                "open_land_polygon_count": len(pasture_candidates.features),
                "open_land_area_m2": open_area_m2,
            },
        ),
        ProcessingStep(
            step_id="detect_farm_complex",
            status="completed",
            description="開放地の連続性と建物との関係から牧場候補の塊を選択した．",
            inputs=("pasture_candidates.geojson", "buildings.geojson", "forest.geojson"),
            outputs=(
                "farm_complex_candidates.geojson",
                "monitoring_area.geojson",
                "facility_buildings.geojson",
                "excluded_buildings.geojson",
            ),
            parameters={
                "bridge_gap_m": detection_config.pasture.bridge_gap_m,
                "enclosed_hole_maximum_area_m2": (
                    detection_config.pasture.enclosed_hole_maximum_area_m2
                ),
                "facility_maximum_distance_m": (
                    detection_config.pasture.facility_maximum_distance_m
                ),
                "monitoring_buffer_m": detection_config.pasture.monitoring_buffer_m,
                "monitoring_closing_m": detection_config.pasture.monitoring_closing_m,
                "selection_anchor_x_m": detection_config.pasture.selection_anchor_x_m,
                "selection_anchor_y_m": detection_config.pasture.selection_anchor_y_m,
                "confirmed": detection_config.pasture.confirm_monitoring_boundary,
            },
            metrics=farm_complex.metrics,
        ),
    )
    if progress is not None:
        progress("[5/5] 判定結果と処理根拠をCaseへ保存します．")
    return replace(
        environment_case,
        case_spec=case_spec,
        farm_boundary=farm_boundary,
        buildings=result.buildings,
        forest=forest,
        traversability=traversability,
        imagery=result.imagery,
        landcover=result.landcover,
        pasture_candidates=pasture_candidates,
        farm_complex_candidates=farm_complex.candidates,
        monitoring_area=farm_complex.monitoring_area,
        facility_buildings=farm_complex.facility_buildings,
        excluded_buildings=farm_complex.excluded_buildings,
        source_artifacts=environment_case.source_artifacts + result.source_artifacts,
        processing_steps=processing_steps,
    )
def _build_created_case(
    config: EnvironmentConfig,
    *,
    working_directory: Path,
    repository_root: Path,
    progress: Callable[[str], None] | None = None,
) -> EnvironmentCase:
    terrain = config.terrain
    provisional_size_m = config.farm.size_m
    if provisional_size_m is None:
        if isinstance(terrain, (SyntheticTerrainConfig, GeographicTerrainConfig)):
            provisional_size_m = terrain.size_m / 2.0
        else:
            provisional_size_m = 1.0
    if isinstance(terrain, SyntheticTerrainConfig):
        grid = TerrainGridSpec.from_extent(
            terrain.size_m,
            terrain.size_m,
            terrain.cell_size_m,
            min_x_m=-terrain.size_m / 2.0,
            min_y_m=-terrain.size_m / 2.0,
        )
        provisional_farm = FarmBoundary.rectangle(
            min_x_m=-provisional_size_m / 2.0,
            min_y_m=-provisional_size_m / 2.0,
            max_x_m=provisional_size_m / 2.0,
            max_y_m=provisional_size_m / 2.0,
            coordinate_system_name=f"{config.case_id}-local-enu",
        )
        environment_case = create_synthetic_case(
            case_id=config.case_id,
            terrain_kind=terrain.type,
            grid=grid,
            farm_boundary=provisional_farm,
            generation_parameters=_synthetic_parameters(terrain),
            seed=terrain.seed,
            origin_description="center of synthetic terrain extent",
        )
    else:
        if isinstance(terrain, GeographicTerrainConfig) and terrain.source == "alos":
            result = acquire_alos_aw3d30(
                terrain, case_id=config.case_id, working_directory=working_directory
            )
        elif isinstance(terrain, GeographicTerrainConfig) and terrain.source == "gsi":
            result = acquire_gsi_elevation(
                terrain, case_id=config.case_id, working_directory=working_directory
            )
        elif isinstance(terrain, FileTerrainConfig):
            result = import_geotiff(
                terrain,
                case_id=config.case_id,
                working_directory=working_directory,
                repository_start=repository_root,
            )
        else:
            raise ValueError("unsupported terrain configuration")
        provisional_farm = FarmBoundary.rectangle(
            min_x_m=-provisional_size_m / 2.0,
            min_y_m=-provisional_size_m / 2.0,
            max_x_m=provisional_size_m / 2.0,
            max_y_m=provisional_size_m / 2.0,
            coordinate_system_name=result.coordinate_system.name,
        )
        environment_case = create_case_from_terrain_source(
            case_id=config.case_id,
            source_result=result,
            farm_boundary=provisional_farm,
        )
    boundary = _farm_boundary(config.farm, environment_case)
    case_spec = environment_case.case_spec.model_copy(
        update={
            "farm_boundary": FarmBoundarySpec(
                data_ref="farm_boundary.geojson", bounds=boundary.bounds
            )
        }
    )
    environment_case = replace(
        environment_case,
        case_spec=case_spec,
        farm_boundary=boundary,
        input_config_digest=config_digest(config),
        history=({"action": "create", "config_digest": config_digest(config)},),
    )
    if config.features is not None:
        environment_case = _apply_features(environment_case, config.features)
    if config.detection is not None:
        environment_case = _apply_detection(
            environment_case,
            config.detection,
            working_directory=working_directory,
            progress=progress,
        )
    if config.scene is not None:
        environment_case = apply_scene_config(environment_case, config.scene)
    return environment_case


def _clone_case(cases_root: Path, source_case_id: str, case_id: str) -> None:
    source = resolve_case_path(cases_root, source_case_id)
    destination = resolve_case_path(cases_root, case_id)
    if destination.exists():
        raise FileExistsError(f"Case already exists: {destination}")
    shutil.copytree(source, destination)
    document_path = destination / "case.yaml"
    raw = yaml.safe_load(document_path.read_text(encoding="utf-8"))
    raw["case"]["case_id"] = case_id
    history = list(raw.get("history") or [])
    history.append({"action": "clone", "source_case_id": source_case_id})
    raw["history"] = history
    document_path.write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def run_environment_workflow(
    config_file: str | Path,
    *,
    repository_start: str | Path | None = None,
    cases_root: str | Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> EnvironmentWorkflowResult:
    repository_root = find_repository_root(repository_start)
    config, config_path = load_environment_config(config_file, start=repository_root)
    cases_root = Path(cases_root).resolve() if cases_root is not None else repository_root / "cases"
    cases_root.mkdir(parents=True, exist_ok=True)
    case_directory = resolve_case_path(cases_root, config.case_id)

    if config.mode is CaseMode.LOAD:
        from .case.loader import load_case

        return EnvironmentWorkflowResult(
            config=config,
            config_path=config_path,
            environment_case=load_case(cases_root, config.case_id),
            case_directory=case_directory,
            action=config.mode,
        )

    if config.mode is CaseMode.CREATE:
        if case_directory.exists():
            raise FileExistsError(f"Case already exists: {case_directory}")
        with tempfile.TemporaryDirectory(prefix=f".{config.case_id}-", dir=cases_root) as temporary:
            environment_case = _build_created_case(
                config,
                working_directory=Path(temporary),
                repository_root=repository_root,
                progress=progress,
            )
            config_artifact = SourceArtifact(
                source_path=config_path,
                case_relative_path=f"source/config/{config_path.name}",
            )
            environment_case = replace(
                environment_case,
                source_artifacts=environment_case.source_artifacts + (config_artifact,),
            )
            save_case(environment_case, cases_root)
        from .case.loader import load_case

        environment_case = load_case(cases_root, config.case_id)
    else:
        if config.source_case_id is not None:
            _clone_case(cases_root, config.source_case_id, config.case_id)
        from .case.loader import load_case

        environment_case = load_case(cases_root, config.case_id)
        if config.farm is not None:
            boundary = _farm_boundary(config.farm, environment_case)
            case_spec = environment_case.case_spec.model_copy(
                update={
                    "farm_boundary": FarmBoundarySpec(
                        data_ref="farm_boundary.geojson", bounds=boundary.bounds
                    )
                }
            )
            environment_case = replace(
                environment_case, case_spec=case_spec, farm_boundary=boundary
            )
        if config.features is not None:
            environment_case = _apply_features(environment_case, config.features)
        if config.detection is not None:
            with tempfile.TemporaryDirectory(
                prefix=f".{config.case_id}-detection-", dir=cases_root
            ) as temporary:
                temporary_source = Path(temporary) / "source"
                existing_source = case_directory / "source"
                if existing_source.is_dir():
                    shutil.copytree(existing_source, temporary_source, dirs_exist_ok=True)
                environment_case = _apply_detection(
                    environment_case,
                    config.detection,
                    working_directory=Path(temporary),
                    progress=progress,
                )
                config_artifact = SourceArtifact(
                    source_path=config_path,
                    case_relative_path=f"source/config/{config_path.name}",
                )
                environment_case = replace(
                    environment_case,
                    source_artifacts=environment_case.source_artifacts + (config_artifact,),
                    input_config_digest=config_digest(config),
                    history=environment_case.history
                    + ({"action": "edit", "config_digest": config_digest(config)},),
                )
                if config.scene is not None:
                    environment_case = apply_scene_config(environment_case, config.scene)
                update_case(environment_case, cases_root)
        else:
            if config.scene is not None:
                environment_case = apply_scene_config(environment_case, config.scene)
            environment_case = replace(
                environment_case,
                input_config_digest=config_digest(config),
                history=environment_case.history
                + ({"action": "edit", "config_digest": config_digest(config)},),
            )
            update_case(environment_case, cases_root)
        environment_case = load_case(cases_root, config.case_id)

    return EnvironmentWorkflowResult(
        config=config,
        config_path=config_path,
        environment_case=environment_case,
        case_directory=case_directory,
        action=config.mode,
    )
