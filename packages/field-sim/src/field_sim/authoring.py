from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import yaml

from field_campost import CameraMountDefinition, PlacementDefinition
from field_environment import validate_case_id

from .experiment import LoadedExperimentPlan, load_experiment_plan
from .herd_config import HerdProfile
from .routes import RouteDefinition
from .waypoints import WaypointSet

PlacementRequest = tuple[str, float | int | str]


@dataclass(frozen=True)
class AuthoredExperiment:
    directory: Path
    plan_path: Path
    loaded_plan: LoadedExperimentPlan
    placement_definitions: tuple[PlacementDefinition, ...]
    route_definitions: tuple[RouteDefinition, ...]
    waypoint_sets: tuple[WaypointSet, ...]


def _number_token(value: float | int) -> str:
    number = float(value)
    return f"{number:g}".replace("-", "minus").replace(".", "p")


def _identifier_token(value: object) -> str:
    token = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value)).strip("-")
    if not token:
        raise ValueError("placement value cannot produce an empty identifier")
    return token


def _write_commented_yaml(
    path: Path,
    payload: Mapping[str, object],
    comments: Mapping[tuple[int, str], str],
) -> None:
    dumped = yaml.safe_dump(
        dict(payload),
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    output = []
    for line in dumped.splitlines():
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        content = stripped[2:] if stripped.startswith("- ") else stripped
        effective_indent = indent + 2 if stripped.startswith("- ") else indent
        key = content.split(":", 1)[0] if ":" in content else ""
        comment = comments.get((effective_indent, key))
        if comment:
            line = f"{line}  # {comment}"
        output.append(line)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def _placement_definition(
    request: PlacementRequest,
    *,
    camera_count: int,
    camera_settings: Mapping[str, object],
    placement_seed: int,
    version: str,
) -> PlacementDefinition:
    method, value = request
    method = str(method).strip()
    if not method:
        raise ValueError("placement method cannot be empty")
    module = None
    parameters: dict[str, object]
    if method == "grid":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("grid placement value must be spacing in metres")
        spacing_m = float(value)
        if spacing_m <= 0.0:
            raise ValueError("grid spacing must be positive")
        variant = f"grid-{_number_token(spacing_m)}m"
        parameters = {"spacing_m": spacing_m}
    elif method == "uniform":
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("uniform placement value must be an integer point count")
        if value <= 0:
            raise ValueError("uniform point count must be positive")
        variant = f"uniform-{value}points"
        parameters = {"point_count": value}
    else:
        variant = f"{method}-{_identifier_token(value)}"
        module = f"workspace.placement.{method}"
        parameters = {"value": value}
    layout_id = f"{variant}-cam{camera_count}-{version}"
    validate_case_id(layout_id)
    mount = CameraMountDefinition.model_validate(
        {**camera_settings, "camera_count": camera_count}
    )
    return PlacementDefinition(
        layout_id=layout_id,
        method=method,
        module=module,
        seed=placement_seed,
        mount=mount,
        parameters=parameters,
    )


def build_placement_definitions(
    camera_placements: Sequence[PlacementRequest],
    camera_counts: Sequence[int],
    *,
    camera_settings: Mapping[str, object] | None = None,
    placement_seed: int = 42,
    version: str = "v1",
) -> tuple[PlacementDefinition, ...]:
    if not camera_placements:
        raise ValueError("at least one camera placement is required")
    if not camera_counts:
        raise ValueError("at least one camera count is required")
    definitions = []
    seen = set()
    for request in camera_placements:
        if len(request) != 2:
            raise ValueError("camera placement must be a (method, value) pair")
        for camera_count in camera_counts:
            if isinstance(camera_count, bool) or not isinstance(camera_count, int):
                raise TypeError("camera count must be an integer")
            definition = _placement_definition(
                request,
                camera_count=camera_count,
                camera_settings=camera_settings or {},
                placement_seed=placement_seed,
                version=version,
            )
            if definition.layout_id in seen:
                raise ValueError(f"duplicate generated layout_id: {definition.layout_id}")
            seen.add(definition.layout_id)
            definitions.append(definition)
    return tuple(definitions)


def build_route_definitions(
    route_methods: Sequence[str],
    waypoint_set: WaypointSet,
    *,
    route_settings: Mapping[str, Mapping[str, object]] | None = None,
    route_seed: int = 42,
    version: str = "v1",
) -> tuple[RouteDefinition, ...]:
    if not route_methods:
        raise ValueError("at least one route method is required")
    settings = route_settings or {}
    definitions = []
    seen = set()
    for method_value in route_methods:
        method = str(method_value).strip()
        if not method:
            raise ValueError("route method cannot be empty")
        parameters = dict(settings.get(method, {}))
        parameters.setdefault("point_spacing_m", 1.0)
        if method in {"smooth", "meandering"}:
            parameters.setdefault("smoothing_tension", 0.0)
            parameters.setdefault("auto_avoid_prohibited", True)
            parameters.setdefault("snap_waypoints", True)
            parameters.setdefault("snap_radius_m", 30.0)
            parameters.setdefault("obstacle_clearance_m", 2.0)
            parameters.setdefault("difficult_cost_multiplier", 4.0)
            parameters.setdefault("unknown_cost_multiplier", 1.0)
        if method == "meandering":
            parameters.setdefault("max_lateral_offset_m", 15.0)
            parameters.setdefault("meander_interval_m", 30.0)
        module = None
        if method not in {"direct", "smooth", "meandering"}:
            module = f"workspace.behavior.routes.{method}"
        seed = int(parameters.pop("seed", route_seed))
        route_id = f"{waypoint_set.waypoint_set_id}-{method}-{version}"
        validate_case_id(route_id)
        if route_id in seen:
            raise ValueError(f"duplicate generated route_id: {route_id}")
        seen.add(route_id)
        definitions.append(
            RouteDefinition(
                route_id=route_id,
                route_group_id=waypoint_set.waypoint_set_id,
                method=method,
                module=module,
                waypoint_set=f"../waypoint_sets/{waypoint_set.waypoint_set_id}.yaml",
                seed=seed,
                parameters=parameters,
            )
        )
    return tuple(definitions)


def _placement_payload(definition: PlacementDefinition) -> dict[str, object]:
    payload = definition.model_dump(mode="json", exclude_none=True)
    payload["mount"] = definition.mount.model_dump(mode="json")
    return payload


def author_experiment(
    output_root: str | Path,
    *,
    experiment_id: str,
    case_id: str,
    camera_placements: Sequence[PlacementRequest],
    camera_counts: Sequence[int],
    route_methods: Sequence[str],
    waypoint_set: WaypointSet | None = None,
    waypoint_sets: Sequence[WaypointSet] | None = None,
    seeds: Sequence[int] = (42,),
    camera_settings: Mapping[str, object] | None = None,
    route_settings: Mapping[str, Mapping[str, object]] | None = None,
    placement_seed: int = 42,
    route_seed: int = 42,
    version: str = "v1",
    visibility: Mapping[str, object] | None = None,
    simulation: Mapping[str, object] | None = None,
    herd_profiles: Sequence[HerdProfile | Mapping[str, object]] = (),
    include_single_individual: bool = True,
    tracker_methods: Sequence[str] = ("last_observation", "constant_velocity"),
    tracker_seed: int = 42,
    overwrite: bool = True,
) -> AuthoredExperiment:
    validate_case_id(experiment_id)
    validate_case_id(case_id)
    if waypoint_set is not None and waypoint_sets is not None:
        raise ValueError("declare waypoint_set or waypoint_sets, not both")
    resolved_waypoint_sets = tuple(waypoint_sets or (() if waypoint_set is None else (waypoint_set,)))
    if not resolved_waypoint_sets:
        raise ValueError("at least one WaypointSet is required")
    waypoint_set_ids = [item.waypoint_set_id for item in resolved_waypoint_sets]
    if len(waypoint_set_ids) != len(set(waypoint_set_ids)):
        raise ValueError("waypoint_set_id values must be unique")
    if any(item.case_id != case_id for item in resolved_waypoint_sets):
        raise ValueError("every WaypointSet.case_id must match case_id")
    if not seeds:
        raise ValueError("at least one experiment seed is required")
    placement_definitions = build_placement_definitions(
        camera_placements,
        camera_counts,
        camera_settings=camera_settings,
        placement_seed=placement_seed,
        version=version,
    )
    route_definitions = tuple(
        definition
        for item in resolved_waypoint_sets
        for definition in build_route_definitions(
            route_methods,
            item,
            route_settings=route_settings,
            route_seed=route_seed,
            version=version,
        )
    )
    destination = Path(output_root).expanduser().resolve() / experiment_id
    temporary = destination.with_name(f".{destination.name}.tmp")
    if temporary.exists():
        shutil.rmtree(temporary)
    if destination.exists() and not overwrite:
        raise FileExistsError(f"generated experiment already exists: {destination}")
    temporary.mkdir(parents=True)
    try:
        placement_paths = []
        for definition in placement_definitions:
            relative = Path("placements") / f"{definition.layout_id}.yaml"
            placement_paths.append(relative.as_posix())
            _write_commented_yaml(
                temporary / relative,
                _placement_payload(definition),
                {
                    (0, "layout_id"): "保存する配置ID",
                    (0, "method"): "使用する配置方式",
                    (0, "module"): "自作方式のPython module",
                    (0, "seed"): "配置を再現するseed",
                    (0, "mount"): "観測ポールとカメラの条件",
                    (2, "pole_height_m"): "地表からのポール高さm",
                    (2, "camera_count"): "1観測点のカメラ台数",
                    (2, "horizontal_fov_deg"): "水平視野角degree",
                    (2, "vertical_fov_deg"): "垂直視野角degree",
                    (2, "max_observation_distance_m"): "最大視認距離m",
                    (2, "observation_interval_s"): "観測する時間間隔s",
                    (2, "first_yaw_deg"): "1台目の水平方向degree",
                    (2, "pitch_deg"): "固定俯角．nullなら自動計算",
                    (2, "pitch_target_height_m"): "俯角計算で見る地表高m",
                    (2, "pitch_reference_distance_m"): "俯角計算の基準距離m",
                    (0, "parameters"): "配置方式固有の設定",
                    (2, "spacing_m"): "格子の間隔m",
                    (2, "point_count"): "等分散する観測点数",
                    (2, "value"): "自作方式へ渡す値",
                },
            )
        for item in resolved_waypoint_sets:
            waypoint_relative = Path("waypoint_sets") / f"{item.waypoint_set_id}.yaml"
            _write_commented_yaml(
                temporary / waypoint_relative,
                item.model_dump(mode="json", by_alias=True),
                {
                    (0, "waypoint_set_id"): "Waypoint集合のID",
                    (0, "case_id"): "使用する農場Case",
                    (0, "waypoints"): "必ず通過させる地点",
                    (2, "id"): "Waypointの識別子",
                    (2, "x_m"): "Case原点から東方向m",
                    (2, "y_m"): "Case原点から北方向m",
                    (2, "dwell_s"): "この地点で停止する秒数",
                },
            )
        route_paths = []
        for definition in route_definitions:
            relative = Path("routes") / f"{definition.route_id}.yaml"
            route_paths.append(relative.as_posix())
            _write_commented_yaml(
                temporary / relative,
                definition.model_dump(mode="json", exclude_none=True),
                {
                    (0, "route_id"): "保存する確定ルートID",
                    (0, "route_group_id"): "入力Waypoint集合のID",
                    (0, "method"): "使用するルート生成方式",
                    (0, "module"): "自作方式のPython module",
                    (0, "waypoint_set"): "入力Waypointの保存先",
                    (0, "seed"): "ルート形状を再現するseed",
                    (0, "parameters"): "ルート方式固有の設定",
                    (2, "point_spacing_m"): "詳細経路点の間隔m",
                    (2, "smoothing_tension"): "曲線の張り具合0から1",
                    (2, "auto_avoid_prohibited"): "禁止領域を自動迂回するか",
                    (2, "snap_waypoints"): "禁止地点を近傍へ補正するか",
                    (2, "snap_radius_m"): "Waypoint補正の探索半径m",
                    (2, "obstacle_clearance_m"): "障害物から確保する距離m",
                    (2, "difficult_cost_multiplier"): "移動困難セルの経路コスト倍率",
                    (2, "unknown_cost_multiplier"): "未分類セルの経路コスト倍率",
                    (2, "max_lateral_offset_m"): "蛇行の最大横幅m",
                    (2, "meander_interval_m"): "蛇行周期の目安m",
                },
            )
        plan_payload: dict[str, object] = {
            "experiment_id": experiment_id,
            "case_id": case_id,
            "placements": placement_paths,
            "routes": route_paths,
            "seeds": list(seeds),
            "matrix": {"mode": "cartesian"},
        }
        if visibility is not None:
            plan_payload["visibility"] = dict(visibility)
        if simulation is not None:
            plan_payload["simulation"] = dict(simulation)
        if herd_profiles:
            plan_payload["herd_profiles"] = [
                (
                    item.model_dump(mode="json")
                    if isinstance(item, HerdProfile)
                    else HerdProfile.model_validate(item).model_dump(mode="json")
                )
                for item in herd_profiles
            ]
        plan_payload["include_single_individual"] = include_single_individual
        plan_payload["tracker_methods"] = list(tracker_methods)
        plan_payload["tracker_seed"] = tracker_seed
        plan_path = temporary / "experiment.yaml"
        _write_commented_yaml(
            plan_path,
            plan_payload,
            {
                (0, "experiment_id"): "実験条件一式のID",
                (0, "case_id"): "使用する農場Case",
                (0, "placements"): "全て試すカメラ配置",
                (0, "routes"): "全て試す鹿ルート",
                (0, "seeds"): "全て試す実験seed",
                (0, "matrix"): "配置とルートの組合せ方法",
                (0, "visibility"): "可視判定の条件",
                (0, "simulation"): "鹿の速度と時間刻み",
                (0, "herd_profiles"): "全て試す群れ構成",
                (0, "include_single_individual"): "従来の単独個体も実験するか",
                (0, "tracker_methods"): "全て実行するTracker方式",
                (0, "tracker_seed"): "Trackerの再現用seed",
                (2, "preview_cell_size_m"): "高速確認の評価間隔m",
                (2, "intermediate_cell_size_m"): "中間確認の評価間隔m",
                (2, "evaluation_cell_size_m"): "正式評価の間隔m",
                (2, "deer_height_m"): "評価する鹿の高さm",
                (2, "sample_heights_m"): "足元・胴・頭の評価高m",
                (2, "observation_position_error"): "任意の観測位置誤差．標準は無効",
                (4, "enabled"): "観測位置誤差を有効にするか",
                (4, "model"): "uniform_diskまたはgaussian",
                (4, "radius_m"): "円内一様誤差の最大半径m",
                (4, "standard_deviation_m"): "正規分布誤差の標準偏差m",
                (4, "seed"): "観測誤差を再現するseed",
                (2, "speed_mps"): "鹿の移動速度m/s",
                (2, "step_s"): "シミュレーション時間刻みs",
            },
        )
        if destination.exists():
            shutil.rmtree(destination)
        temporary.replace(destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    final_plan = destination / "experiment.yaml"
    loaded = load_experiment_plan(final_plan)
    return AuthoredExperiment(
        directory=destination,
        plan_path=final_plan,
        loaded_plan=loaded,
        placement_definitions=placement_definitions,
        route_definitions=route_definitions,
        waypoint_sets=resolved_waypoint_sets,
    )
