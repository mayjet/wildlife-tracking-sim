from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from field_environment import (
    EnvironmentCase,
    crop_heightmap,
    scene_crop_geometry,
    slope_degrees,
)
from shapely.geometry import shape
from shapely.ops import unary_union

from .mesh import TerrainMesh


def _layer_geometry(layer, crop):
    if layer is None or layer.status.value != "available":
        return None
    return unary_union([shape(feature["geometry"]) for feature in layer.features]).intersection(crop)


def _layer_metrics(layer, crop) -> dict[str, float | int | str]:
    geometry = _layer_geometry(layer, crop)
    return {
        "status": "unavailable" if layer is None else layer.status.value,
        "feature_count": 0
        if layer is None or layer.status.value != "available"
        else sum(shape(feature["geometry"]).intersects(crop) for feature in layer.features),
        "area_m2": 0.0 if geometry is None or geometry.is_empty else float(geometry.area),
    }


# クロップ後の寸法・標高・地物・Mesh規模を研究記録として保存する．
def build_field_summary(
    environment_case: EnvironmentCase,
    mesh: TerrainMesh,
    *,
    usd_path: str | Path | None = None,
) -> dict:
    crop = scene_crop_geometry(environment_case)
    heightmap = crop_heightmap(environment_case.heightmap, crop)
    min_x, min_y, max_x, max_y = crop.bounds
    elevations = heightmap.values
    slopes = slope_degrees(elevations, heightmap.grid.cell_size_m)
    triangle_vertices = mesh.vertices[mesh.faces]
    terrain_surface_area = float(
        np.sum(
            np.linalg.norm(
                np.cross(
                    triangle_vertices[:, 1] - triangle_vertices[:, 0],
                    triangle_vertices[:, 2] - triangle_vertices[:, 0],
                ),
                axis=1,
            )
            * 0.5
        )
    )
    source = environment_case.provenance
    summary = {
        "case_id": environment_case.case_spec.case_id,
        "scene": {
            "width_m": float(max_x - min_x),
            "height_m": float(max_y - min_y),
            "horizontal_area_m2": float(crop.area),
            "terrain_surface_area_m2": terrain_surface_area,
            "source_terrain_width_m": environment_case.heightmap.width_m,
            "source_terrain_height_m": environment_case.heightmap.height_m,
            "source_area_reduction_ratio": 1.0
            - float(crop.area)
            / (environment_case.heightmap.width_m * environment_case.heightmap.height_m),
        },
        "terrain": {
            "cell_size_m": heightmap.grid.cell_size_m,
            "width_cells": heightmap.grid.width_cells,
            "height_cells": heightmap.grid.height_cells,
            "elevation_min_m": float(np.min(elevations)),
            "elevation_max_m": float(np.max(elevations)),
            "elevation_mean_m": float(np.mean(elevations)),
            "relief_m": float(np.max(elevations) - np.min(elevations)),
            "slope_mean_deg": float(np.mean(slopes)),
            "slope_max_deg": float(np.max(slopes)),
            "missing_cell_count": int(np.count_nonzero(~np.isfinite(elevations))),
        },
        "regions": {
            "farm_area_m2": float(environment_case.farm_boundary.polygon.intersection(crop).area),
            "monitoring": _layer_metrics(environment_case.monitoring_area, crop),
            "forest": _layer_metrics(environment_case.forest, crop),
            "open_land": _layer_metrics(environment_case.pasture_candidates, crop),
            "buildings": _layer_metrics(environment_case.buildings, crop),
            "facility_buildings": _layer_metrics(environment_case.facility_buildings, crop),
        },
        "mesh": {
            "vertex_count": int(len(mesh.vertices)),
            "triangle_count": int(len(mesh.faces)),
            "usd_size_bytes": (
                int(Path(usd_path).stat().st_size)
                if usd_path is not None and Path(usd_path).is_file()
                else None
            ),
        },
        "source": {
            "terrain_source": environment_case.generation.source,
            "dataset": None if source is None else source.dataset,
            "effective_resolution_m": None if source is None else source.effective_resolution_m,
            "output_cell_size_m": None if source is None else source.output_cell_size_m,
            "vertical_datum": None if source is None else source.vertical_datum,
            "imagery_source": None if environment_case.imagery is None else environment_case.imagery.source,
            "landcover_source": None if environment_case.landcover is None else environment_case.landcover.source,
        },
    }
    return summary


def save_field_summary(summary: dict, path: str | Path) -> Path:
    destination = Path(path)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(destination)
    return destination


def format_field_summary_japanese(summary: dict) -> str:
    scene = summary["scene"]
    terrain = summary["terrain"]
    regions = summary["regions"]
    mesh = summary["mesh"]

    def area_text(area_m2: float) -> str:
        return f"{area_m2:,.0f} m²（{area_m2 / 10_000.0:,.2f} ha）"

    usd_size = mesh.get("usd_size_bytes")
    usd_size_text = "未生成" if usd_size is None else f"{usd_size / (1024**2):,.1f} MiB"
    return "\n".join(
        (
            "実験環境の概要",
            f"Case ID: {summary['case_id']}",
            "",
            "実験範囲",
            f"- 東西距離: {scene['width_m']:,.0f} m",
            f"- 南北距離: {scene['height_m']:,.0f} m",
            f"- 水平面積: {area_text(scene['horizontal_area_m2'])}",
            f"- 地表面積: {area_text(scene['terrain_surface_area_m2'])}",
            f"- 元の取得範囲からの面積削減率: {scene['source_area_reduction_ratio'] * 100.0:,.1f} %",
            "",
            "地形",
            f"- 地形セルサイズ: {terrain['cell_size_m']:g} m",
            f"- 地形セル数: 東西{terrain['width_cells']:,} × 南北{terrain['height_cells']:,}",
            f"- 標高: 最低{terrain['elevation_min_m']:,.2f} m，最高{terrain['elevation_max_m']:,.2f} m",
            f"- 平均標高: {terrain['elevation_mean_m']:,.2f} m",
            f"- 高低差: {terrain['relief_m']:,.2f} m",
            f"- 傾斜: 平均{terrain['slope_mean_deg']:,.2f}°，最大{terrain['slope_max_deg']:,.2f}°",
            f"- 欠損セル数: {terrain['missing_cell_count']:,}",
            "",
            "地物",
            f"- 牧場面積: {area_text(regions['farm_area_m2'])}",
            f"- 監視範囲: {area_text(regions['monitoring']['area_m2'])}",
            f"- 森林面積: {area_text(regions['forest']['area_m2'])}",
            f"- 開放地面積: {area_text(regions['open_land']['area_m2'])}",
            f"- 建物: {regions['buildings']['feature_count']:,}棟，{area_text(regions['buildings']['area_m2'])}",
            f"- 牧場施設候補: {regions['facility_buildings']['feature_count']:,}棟，{area_text(regions['facility_buildings']['area_m2'])}",
            "",
            "3Dデータ",
            f"- 地形頂点数: {mesh['vertex_count']:,}",
            f"- 三角形数: {mesh['triangle_count']:,}",
            f"- USDファイルサイズ: {usd_size_text}",
        )
    )
