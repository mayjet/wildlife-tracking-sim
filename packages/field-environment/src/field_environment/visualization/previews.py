from __future__ import annotations

from pathlib import Path
from typing import Callable

from matplotlib import pyplot as plt
from matplotlib.figure import Figure

from ..case.models import EnvironmentCase
from .detection import (
    plot_building_footprints,
    plot_environment_detection,
    plot_experiment_environment,
    plot_farm_complex_candidates,
    plot_forest_classification,
    plot_landcover,
    plot_monitoring_boundary,
    plot_open_land_candidates,
    plot_satellite_imagery,
    plot_scene_crop,
    plot_selected_farm_complex,
)
from .quality import plot_elevation, plot_hillshade, plot_slope, plot_terrain_quality


# 取得地点と要求範囲を緯度経度で表示する．
def plot_source_location(environment_case: EnvironmentCase) -> tuple[Figure, object]:
    origin = environment_case.case_spec.coordinate_system.geodetic_origin
    provenance = environment_case.provenance
    if origin is None or provenance is None or provenance.geographic_bounds is None:
        raise ValueError("Case has no geographic source extent")
    west, south, east, north = provenance.geographic_bounds
    figure, axis = plt.subplots(figsize=(7, 6), constrained_layout=True)
    axis.plot([west, east, east, west, west], [south, south, north, north, south])
    axis.scatter(origin.longitude_deg, origin.latitude_deg, marker="+", color="red", s=100)
    axis.set_xlabel("Longitude (degrees)")
    axis.set_ylabel("Latitude (degrees)")
    axis.set_title(f"Requested source extent — {provenance.dataset}")
    return figure, axis


def _save_figure(
    factory: Callable[[EnvironmentCase], tuple[Figure, object]],
    environment_case: EnvironmentCase,
    destination: Path,
) -> Path:
    figure, _ = factory(environment_case)
    figure.savefig(destination, dpi=160)
    plt.close(figure)
    return destination


# 判定過程を研究記録用の独立画像として保存する．
def save_case_previews(
    environment_case: EnvironmentCase,
    case_directory: str | Path,
) -> tuple[Path, ...]:
    destination = Path(case_directory) / "previews"
    destination.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    if (
        environment_case.case_spec.coordinate_system.geodetic_origin is not None
        and environment_case.provenance is not None
        and environment_case.provenance.geographic_bounds is not None
    ):
        saved.append(
            _save_figure(
                plot_source_location,
                environment_case,
                destination / "01_acquisition_area.png",
            )
        )
    if environment_case.scene_crop is not None:
        saved.append(
            _save_figure(
                plot_scene_crop,
                environment_case,
                destination / "13_scene_crop.png",
            )
        )
    if environment_case.imagery is not None:
        saved.append(
            _save_figure(
                plot_satellite_imagery,
                environment_case,
                destination / "02_satellite_rgb.png",
            )
        )
    saved.append(
        _save_figure(plot_elevation, environment_case, destination / "03_elevation.png")
    )
    saved.append(_save_figure(plot_slope, environment_case, destination / "04_slope.png"))
    if environment_case.landcover is not None:
        for factory, filename in (
            (plot_landcover, "05_landcover.png"),
            (plot_forest_classification, "06_forest_classification.png"),
            (plot_open_land_candidates, "07_open_land_candidates.png"),
            (plot_building_footprints, "08_building_footprints.png"),
            (plot_farm_complex_candidates, "09_farm_complex_candidates.png"),
            (plot_selected_farm_complex, "10_selected_farm_complex.png"),
            (plot_monitoring_boundary, "11_monitoring_boundary.png"),
            (plot_experiment_environment, "12_experiment_environment.png"),
        ):
            saved.append(_save_figure(factory, environment_case, destination / filename))
        saved.append(
            _save_figure(
                plot_environment_detection,
                environment_case,
                destination / "environment_detection_summary.png",
            )
        )

    # 既存の参照名は互換性のため独立Figureとして残す．
    for factory, filename in (
        (plot_elevation, "elevation.png"),
        (plot_hillshade, "hillshade.png"),
        (plot_slope, "slope.png"),
        (plot_terrain_quality, "terrain_quality.png"),
    ):
        saved.append(_save_figure(factory, environment_case, destination / filename))
    if environment_case.landcover is not None:
        saved.append(
            _save_figure(
                plot_environment_detection,
                environment_case,
                destination / "environment_detection.png",
            )
        )
    return tuple(saved)
