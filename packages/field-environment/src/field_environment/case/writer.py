from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from uuid import uuid4

import rasterio
import yaml
from rasterio.transform import from_origin

from .models import EnvironmentCase
from .validator import validate_environment_case

_CASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def validate_case_id(case_id: str) -> str:
    if not _CASE_ID_PATTERN.fullmatch(case_id):
        raise ValueError("case_id must use 1-128 ASCII letters, numbers, dot, underscore, or hyphen")
    return case_id


def resolve_case_path(cases_root: str | Path, case_id: str) -> Path:
    validated_id = validate_case_id(case_id)
    resolved_root = Path(cases_root).resolve()
    target = (resolved_root / validated_id).resolve()
    if target.parent != resolved_root:
        raise ValueError("case_id resolves outside cases_root")
    return target


_safe_case_path = resolve_case_path


def _write_heightmap(environment_case: EnvironmentCase, destination: Path) -> None:
    heightmap = environment_case.heightmap
    bounds = heightmap.bounds
    transform = from_origin(
        bounds.min_x_m,
        bounds.max_y_m,
        heightmap.grid.cell_size_m,
        heightmap.grid.cell_size_m,
    )
    raster_options = {}
    if environment_case.case_spec.coordinate_system.projected_crs:
        raster_options["crs"] = environment_case.case_spec.coordinate_system.projected_crs
    with rasterio.open(
        destination,
        "w",
        driver="GTiff",
        width=heightmap.grid.width_cells,
        height=heightmap.grid.height_cells,
        count=1,
        dtype=str(heightmap.values.dtype),
        transform=transform,
        compress="deflate",
        **raster_options,
    ) as dataset:
        dataset.write(heightmap.values[::-1, :], 1)
        dataset.update_tags(
            coordinate_system=environment_case.case_spec.coordinate_system.name,
            memory_axis_order="YX",
            memory_origin="south-west-cell-center",
            units="m",
        )


def _write_traversability(environment_case: EnvironmentCase, destination: Path) -> None:
    traversability = environment_case.traversability
    if traversability is None:
        return
    bounds = traversability.grid.bounds
    transform = from_origin(
        bounds.min_x_m,
        bounds.max_y_m,
        traversability.grid.cell_size_m,
        traversability.grid.cell_size_m,
    )
    raster_options = {}
    if environment_case.case_spec.coordinate_system.projected_crs:
        raster_options["crs"] = environment_case.case_spec.coordinate_system.projected_crs
    with rasterio.open(
        destination,
        "w",
        driver="GTiff",
        width=traversability.grid.width_cells,
        height=traversability.grid.height_cells,
        count=1,
        dtype="uint8",
        transform=transform,
        compress="deflate",
        **raster_options,
    ) as dataset:
        dataset.write(traversability.values[::-1, :], 1)
        dataset.update_tags(
            categories="0=unknown,1=traversable,2=difficult,3=prohibited",
            difficult_slope_deg=(
                "unset"
                if traversability.difficult_slope_deg is None
                else traversability.difficult_slope_deg
            ),
        )


def _write_raster_layer(environment_case: EnvironmentCase, layer, destination: Path) -> None:
    bounds = layer.grid.bounds
    transform = from_origin(
        bounds.min_x_m,
        bounds.max_y_m,
        layer.grid.cell_size_m,
        layer.grid.cell_size_m,
    )
    raster_options = {}
    if environment_case.case_spec.coordinate_system.projected_crs:
        raster_options["crs"] = environment_case.case_spec.coordinate_system.projected_crs
    if layer.layer_type == "imagery":
        count = 3
        values = layer.values[::-1, :, :].transpose(2, 0, 1)
        options = {"photometric": "RGB", "compress": "deflate"}
    else:
        count = 1
        values = layer.values[::-1, :][None, :, :]
        options = {"compress": "deflate", "nodata": 0}
    with rasterio.open(
        destination,
        "w",
        driver="GTiff",
        width=layer.grid.width_cells,
        height=layer.grid.height_cells,
        count=count,
        dtype="uint8",
        transform=transform,
        **options,
        **raster_options,
    ) as dataset:
        dataset.write(values)
        dataset.update_tags(
            source=layer.source,
            attribution=layer.attribution,
            source_resolution_m=(
                "unknown" if layer.source_resolution_m is None else layer.source_resolution_m
            ),
            memory_origin="south-west-cell-center",
        )


def _write_case_contents(environment_case: EnvironmentCase, destination: Path) -> None:
    _write_heightmap(environment_case, destination / "terrain.tif")
    (destination / "farm_boundary.geojson").write_text(
        json.dumps(environment_case.farm_boundary.to_geojson(), indent=2),
        encoding="utf-8",
    )
    for layer, filename in (
        (environment_case.buildings, "buildings.geojson"),
        (environment_case.forest, "forest.geojson"),
        (environment_case.pasture_candidates, "pasture_candidates.geojson"),
        (environment_case.farm_complex_candidates, "farm_complex_candidates.geojson"),
        (environment_case.monitoring_area, "monitoring_area.geojson"),
        (environment_case.facility_buildings, "facility_buildings.geojson"),
        (environment_case.excluded_buildings, "excluded_buildings.geojson"),
        (environment_case.scene_crop, "scene_crop.geojson"),
    ):
        target = destination / filename
        if layer is not None and layer.status.value != "unavailable":
            target.write_text(json.dumps(layer.to_geojson(), indent=2), encoding="utf-8")
        else:
            target.unlink(missing_ok=True)
    for layer, filename in (
        (environment_case.imagery, "imagery_rgb.tif"),
        (environment_case.landcover, "landcover.tif"),
    ):
        target = destination / filename
        if layer is not None:
            _write_raster_layer(environment_case, layer, target)
        else:
            target.unlink(missing_ok=True)
    if environment_case.traversability is not None:
        _write_traversability(environment_case, destination / "traversability.tif")
    else:
        (destination / "traversability.tif").unlink(missing_ok=True)
    for artifact in environment_case.source_artifacts:
        relative = Path(artifact.case_relative_path)
        if relative.is_absolute() or ".." in relative.parts or relative.parts[:1] != ("source",):
            raise ValueError("source artifact path must stay below source/")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(artifact.source_path, target)
    (destination / "case.yaml").write_text(
        yaml.safe_dump(
            environment_case.document.model_dump(mode="json"),
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )


def save_case(
    environment_case: EnvironmentCase,
    cases_root: str | Path,
    *,
    overwrite: bool = False,
) -> Path:
    validate_environment_case(environment_case)
    root = Path(cases_root)
    root.mkdir(parents=True, exist_ok=True)
    destination = resolve_case_path(root, environment_case.case_spec.case_id)
    if destination.exists() and not overwrite:
        raise FileExistsError(f"Case already exists: {destination}")

    temporary = destination.parent / f".{destination.name}.tmp-{uuid4().hex}"
    temporary.mkdir()
    try:
        _write_case_contents(environment_case, temporary)
        (temporary / "datasets").mkdir()
        (temporary / "runs").mkdir()
        if destination.exists():
            shutil.rmtree(destination)
        temporary.replace(destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return destination


def update_case(environment_case: EnvironmentCase, cases_root: str | Path) -> Path:
    validate_environment_case(environment_case)
    destination = resolve_case_path(cases_root, environment_case.case_spec.case_id)
    if not destination.is_dir():
        raise FileNotFoundError(f"Case does not exist: {destination}")
    temporary = destination.parent / f".{destination.name}.tmp-{uuid4().hex}"
    backup = destination.parent / f".{destination.name}.backup-{uuid4().hex}"
    shutil.copytree(destination, temporary)
    try:
        _write_case_contents(environment_case, temporary)
        destination.replace(backup)
        temporary.replace(destination)
        shutil.rmtree(backup)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        if backup.exists() and not destination.exists():
            backup.replace(destination)
        raise
    return destination
