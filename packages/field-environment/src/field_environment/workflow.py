from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

import yaml
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform
from shepherd_contracts import FarmBoundarySpec

from .case.models import EnvironmentCase, SourceArtifact
from .case.writer import resolve_case_path, save_case, update_case
from .config import (
    CaseMode,
    EnvironmentConfig,
    EnvironmentFeaturesConfig,
    FeatureInputConfig,
    FileTerrainConfig,
    GeographicTerrainConfig,
    SyntheticTerrainConfig,
    config_digest,
    load_environment_config,
)
from .factory import create_case_from_terrain_source, create_synthetic_case
from .farm.boundary import FarmBoundary
from .features import (
    FeatureLayerStatus,
    PolygonFeatureLayer,
    create_feature_layer,
    generate_traversability,
    load_polygon_feature_layer,
)
from .repository import find_repository_root, resolve_repository_path
from .sources import acquire_alos_aw3d30, acquire_gsi_elevation, import_geotiff
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


def _build_created_case(
    config: EnvironmentConfig,
    *,
    working_directory: Path,
    repository_root: Path,
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
