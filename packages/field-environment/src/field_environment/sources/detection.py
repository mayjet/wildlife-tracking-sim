from __future__ import annotations

import json
import math
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import numpy as np
import rasterio
import requests
from PIL import Image
from pyproj import Transformer
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject
from rasterio.windows import from_bounds
from shapely.geometry import box, LineString, mapping, Polygon, shape
from shapely.ops import polygonize, transform, unary_union

from shepherd_contracts import LocalCoordinateSystem

from ..case.models import SourceArtifact, TerrainProvenance
from ..config import GsiImageryConfig, OsmBuildingConfig, WorldCoverConfig
from ..environment_detection import RasterLayer
from ..errors import TerrainAcquisitionError, TerrainDataUnavailableError
from ..features import FeatureLayerStatus, PolygonFeatureLayer
from ..terrain.heightmap import Heightmap, TerrainGridSpec
from .gsi import _tile_coordinates

GSI_IMAGERY_URL = "https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{z}/{x}/{y}.jpg"
GSI_VECTOR_URL = "https://cyberjapandata.gsi.go.jp/xyz/experimental_bvmap/{z}/{x}/{y}.pbf"
WORLD_COVER_URL = (
    "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
    "ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"
)
OVERPASS_FALLBACK_URLS = (
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)


@dataclass(frozen=True)
class DetectionSourceResult:
    imagery: RasterLayer
    landcover: RasterLayer
    buildings: PolygonFeatureLayer
    source_artifacts: tuple[SourceArtifact, ...]


def _require_geographic_case(
    coordinate_system: LocalCoordinateSystem,
    provenance: TerrainProvenance | None,
) -> tuple[tuple[float, float, float, float], str]:
    if provenance is None or provenance.geographic_bounds is None:
        raise ValueError("environment detection requires geographic Case bounds")
    if coordinate_system.projected_crs is None:
        raise ValueError("environment detection requires a projected Case CRS")
    return provenance.geographic_bounds, coordinate_system.projected_crs


def _write_rgb_source(path: Path, values_north_up: np.ndarray, transform_value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=values_north_up.shape[1],
        height=values_north_up.shape[0],
        count=3,
        dtype="uint8",
        crs="EPSG:3857",
        transform=transform_value,
        compress="jpeg",
        photometric="YCBCR",
    ) as dataset:
        dataset.write(np.moveaxis(values_north_up, 2, 0))


# 国土地理院のシームレス画像を取得し，Case座標へ変換する．
def acquire_gsi_imagery(
    config: GsiImageryConfig,
    *,
    heightmap: Heightmap,
    coordinate_system: LocalCoordinateSystem,
    provenance: TerrainProvenance | None,
    working_directory: str | Path,
    session: requests.Session | None = None,
) -> tuple[RasterLayer, tuple[SourceArtifact, ...]]:
    bounds, projected_crs = _require_geographic_case(coordinate_system, provenance)
    west, south, east, north = bounds
    corner_lon = np.array([west, east, west, east])
    corner_lat = np.array([south, south, north, north])
    tile_x, tile_y, _, _ = _tile_coordinates(corner_lon, corner_lat, config.zoom)
    min_x, max_x = int(tile_x.min()), int(tile_x.max())
    min_y, max_y = int(tile_y.min()), int(tile_y.max())
    working = Path(working_directory)
    tile_root = working / ".download-cache" / "gsi-seamlessphoto"
    client = session or requests.Session()
    client.headers.update({"User-Agent": "wildlife-tracking-sim/0.1"})
    earth_radius_m = 6378137.0
    world_half_m = math.pi * earth_radius_m
    pixel_size_m = 2.0 * world_half_m / (256 * 2**config.zoom)
    source_path = working / "source" / "gsi" / "seamlessphoto_mosaic.tif"
    if source_path.is_file():
        with rasterio.open(source_path) as source:
            mosaic = source.read().transpose(1, 2, 0)
            mosaic_transform = source.transform
    else:
        mosaic = np.empty(
            ((max_y - min_y + 1) * 256, (max_x - min_x + 1) * 256, 3),
            dtype=np.uint8,
        )
        for current_y in range(min_y, max_y + 1):
            for current_x in range(min_x, max_x + 1):
                tile_path = tile_root / str(config.zoom) / str(current_x) / f"{current_y}.jpg"
                if tile_path.is_file():
                    content = tile_path.read_bytes()
                elif config.offline:
                    raise TerrainDataUnavailableError(
                        f"cached GSI imagery tile not found: {tile_path}"
                    )
                else:
                    url = GSI_IMAGERY_URL.format(z=config.zoom, x=current_x, y=current_y)
                    try:
                        response = client.get(url, timeout=30)
                        response.raise_for_status()
                    except requests.RequestException as error:
                        raise TerrainAcquisitionError(
                            f"GSI imagery request failed for {url}: {error}"
                        ) from error
                    content = response.content
                    tile_path.parent.mkdir(parents=True, exist_ok=True)
                    tile_path.write_bytes(content)
                tile = np.asarray(Image.open(BytesIO(content)).convert("RGB"), dtype=np.uint8)
                row = (current_y - min_y) * 256
                column = (current_x - min_x) * 256
                mosaic[row : row + 256, column : column + 256] = tile
        mosaic_transform = from_origin(
            min_x * 256 * pixel_size_m - world_half_m,
            world_half_m - min_y * 256 * pixel_size_m,
            pixel_size_m,
            pixel_size_m,
        )
        _write_rgb_source(source_path, mosaic, mosaic_transform)

    terrain_bounds = heightmap.bounds
    image_grid = TerrainGridSpec.from_extent(
        terrain_bounds.max_x_m - terrain_bounds.min_x_m,
        terrain_bounds.max_y_m - terrain_bounds.min_y_m,
        config.output_cell_size_m,
        min_x_m=terrain_bounds.min_x_m,
        min_y_m=terrain_bounds.min_y_m,
    )
    destination_transform = from_origin(
        image_grid.bounds.min_x_m,
        image_grid.bounds.max_y_m,
        image_grid.cell_size_m,
        image_grid.cell_size_m,
    )
    destination = np.zeros((3, image_grid.height_cells, image_grid.width_cells), dtype=np.uint8)
    source_bands = np.moveaxis(mosaic, 2, 0)
    for band_index in range(3):
        reproject(
            source=source_bands[band_index],
            destination=destination[band_index],
            src_transform=mosaic_transform,
            src_crs="EPSG:3857",
            dst_transform=destination_transform,
            dst_crs=projected_crs,
            resampling=Resampling.bilinear,
        )
    request_path = working / "source" / "gsi" / "seamlessphoto_request.json"
    request_path.write_text(
        json.dumps(
            {
                "source": "GSI seamlessphoto",
                "zoom": config.zoom,
                "tile_bounds": [min_x, min_y, max_x, max_y],
                "geographic_bounds": bounds,
                "output_cell_size_m": config.output_cell_size_m,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    artifacts = tuple(
        SourceArtifact(source_path=path, case_relative_path=path.relative_to(working).as_posix())
        for path in (source_path, request_path)
    )
    return (
        RasterLayer(
            layer_type="imagery",
            values=np.moveaxis(destination, 0, 2)[::-1, :, :],
            grid=image_grid,
            source="GSI seamlessphoto",
            attribution="Geospatial Information Authority of Japan seamless aerial/satellite imagery",
            source_resolution_m=pixel_size_m,
        ),
        artifacts,
    )


def _worldcover_tile_name(longitude: float, latitude: float) -> str:
    tile_lon = math.floor(longitude / 3.0) * 3
    tile_lat = math.floor(latitude / 3.0) * 3
    return f"{'N' if tile_lat >= 0 else 'S'}{abs(tile_lat):02d}{'E' if tile_lon >= 0 else 'W'}{abs(tile_lon):03d}"


# ESA WorldCoverを取得し，Caseの地形グリッドへ変換する．
def acquire_worldcover(
    config: WorldCoverConfig,
    *,
    heightmap: Heightmap,
    coordinate_system: LocalCoordinateSystem,
    provenance: TerrainProvenance | None,
    working_directory: str | Path,
) -> tuple[RasterLayer, tuple[SourceArtifact, ...]]:
    bounds, projected_crs = _require_geographic_case(coordinate_system, provenance)
    west, south, east, north = bounds
    tile_names = {
        _worldcover_tile_name(longitude, latitude)
        for longitude in (west, east)
        for latitude in (south, north)
    }
    if len(tile_names) != 1:
        raise TerrainDataUnavailableError("WorldCover extent crosses a 3-degree tile boundary")
    tile_name = next(iter(tile_names))
    url = WORLD_COVER_URL.format(tile=tile_name)
    working = Path(working_directory)
    source_path = working / "source" / "esa_worldcover" / f"{tile_name}_crop.tif"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    if not source_path.is_file():
        if config.offline:
            raise TerrainDataUnavailableError(f"cached WorldCover crop not found: {source_path}")
        try:
            with rasterio.Env(
                CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
                GDAL_HTTP_MULTIRANGE="YES",
            ):
                with rasterio.open(url) as source:
                    window = from_bounds(west, south, east, north, source.transform)
                    window = window.round_offsets().round_lengths()
                    values = source.read(1, window=window, boundless=True, fill_value=0)
                    crop_transform = source.window_transform(window)
                    with rasterio.open(
                        source_path,
                        "w",
                        driver="GTiff",
                        width=values.shape[1],
                        height=values.shape[0],
                        count=1,
                        dtype="uint8",
                        crs=source.crs,
                        transform=crop_transform,
                        nodata=0,
                        compress="deflate",
                    ) as crop:
                        crop.write(values, 1)
        except rasterio.errors.RasterioError as error:
            raise TerrainAcquisitionError(f"WorldCover request failed for {url}: {error}") from error

    destination_transform = from_origin(
        heightmap.bounds.min_x_m,
        heightmap.bounds.max_y_m,
        heightmap.grid.cell_size_m,
        heightmap.grid.cell_size_m,
    )
    destination = np.zeros(heightmap.values.shape, dtype=np.uint8)
    with rasterio.open(source_path) as source:
        reproject(
            source=rasterio.band(source, 1),
            destination=destination,
            src_transform=source.transform,
            src_crs=source.crs,
            src_nodata=0,
            dst_transform=destination_transform,
            dst_crs=projected_crs,
            dst_nodata=0,
            resampling=Resampling.nearest,
        )
    if not np.any(destination):
        raise TerrainDataUnavailableError("WorldCover returned no classified cells for the Case")
    request_path = source_path.parent / "request.json"
    request_path.write_text(
        json.dumps({"url": url, "tile": tile_name, "geographic_bounds": bounds}, indent=2),
        encoding="utf-8",
    )
    artifacts = tuple(
        SourceArtifact(source_path=path, case_relative_path=path.relative_to(working).as_posix())
        for path in (source_path, request_path)
    )
    return (
        RasterLayer(
            layer_type="landcover",
            values=destination[::-1, :],
            grid=heightmap.grid,
            source="ESA WorldCover 2021 v200",
            attribution="ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data",
            source_resolution_m=10.0,
        ),
        artifacts,
    )


def _parse_height(tags: dict[str, str]) -> float | None:
    raw = tags.get("height")
    if raw:
        try:
            return float(raw.lower().replace("m", "").strip())
        except ValueError:
            pass
    levels = tags.get("building:levels")
    if levels:
        try:
            return float(levels) * 3.0
        except ValueError:
            pass
    return None


# OpenStreetMapから建物外周と取得可能な高さを読み込む．
def acquire_osm_buildings(
    config: OsmBuildingConfig,
    *,
    heightmap: Heightmap,
    coordinate_system: LocalCoordinateSystem,
    provenance: TerrainProvenance | None,
    working_directory: str | Path,
    session: requests.Session | None = None,
) -> tuple[PolygonFeatureLayer, tuple[SourceArtifact, ...]]:
    bounds, projected_crs = _require_geographic_case(coordinate_system, provenance)
    west, south, east, north = bounds
    query = (
        f"[out:json][timeout:90];(way[\"building\"]({south},{west},{north},{east});"
        f"relation[\"building\"]({south},{west},{north},{east}););out geom;"
    )
    working = Path(working_directory)
    response_path = working / "source" / "osm" / "buildings_overpass.json"
    response_path.parent.mkdir(parents=True, exist_ok=True)
    if response_path.is_file():
        document = json.loads(response_path.read_text(encoding="utf-8"))
    elif config.offline:
        raise TerrainDataUnavailableError(f"cached OSM response not found: {response_path}")
    else:
        client = session or requests.Session()
        client.headers.update({"User-Agent": "wildlife-tracking-sim/0.1"})
        errors = []
        endpoint_used = None
        endpoints = tuple(dict.fromkeys((config.overpass_url,) + OVERPASS_FALLBACK_URLS))
        for endpoint in endpoints:
            try:
                response = client.post(endpoint, data={"data": query}, timeout=120)
                response.raise_for_status()
                document = response.json()
                endpoint_used = endpoint
                break
            except (requests.RequestException, ValueError) as error:
                errors.append(f"{endpoint}: {error}")
        else:
            raise TerrainAcquisitionError(
                "OSM Overpass requests failed: " + " | ".join(errors)
            )
        response_path.write_text(json.dumps(document), encoding="utf-8")
    if response_path.is_file() and "endpoint_used" not in locals():
        endpoint_used = config.overpass_url

    transformer = Transformer.from_crs("EPSG:4326", projected_crs, always_xy=True)
    case_bounds = box(
        heightmap.bounds.min_x_m,
        heightmap.bounds.min_y_m,
        heightmap.bounds.max_x_m,
        heightmap.bounds.max_y_m,
    )
    features = []
    geometries: list[tuple[list[dict[str, float]], dict[str, str], int]] = []
    for element in document.get("elements", []):
        tags = dict(element.get("tags") or {})
        if element.get("type") == "way" and element.get("geometry"):
            geometries.append((element["geometry"], tags, int(element["id"])))
        elif element.get("type") == "relation":
            for member in element.get("members", []):
                if member.get("role") == "outer" and member.get("geometry"):
                    geometries.append((member["geometry"], tags, int(element["id"])))
    for geometry_nodes, tags, osm_id in geometries:
        coordinates = [(node["lon"], node["lat"]) for node in geometry_nodes]
        if len(coordinates) < 3:
            continue
        if coordinates[0] != coordinates[-1]:
            coordinates.append(coordinates[0])
        geometry = transform(transformer.transform, Polygon(coordinates))
        if not geometry.is_valid:
            geometry = geometry.buffer(0)
        geometry = geometry.intersection(case_bounds)
        if geometry.is_empty or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            continue
        properties = {
            "osm_id": osm_id,
            "building": tags.get("building"),
            "name": tags.get("name"),
            "height_m": _parse_height(tags),
        }
        if properties["height_m"] is None and config.assumed_height_m is not None:
            properties["assumed_height_m"] = config.assumed_height_m
        features.append({"type": "Feature", "geometry": mapping(geometry), "properties": properties})
    layer = PolygonFeatureLayer(
        layer_type="buildings",
        status=FeatureLayerStatus.AVAILABLE if features else FeatureLayerStatus.EMPTY,
        coordinate_system_name=coordinate_system.name,
        features=tuple(features),
        source="OpenStreetMap via Overpass API",
        assumed_height_m=config.assumed_height_m,
    )
    request_path = response_path.parent / "request.json"
    request_path.write_text(
        json.dumps(
            {
                "endpoint_requested": config.overpass_url,
                "endpoint_used": endpoint_used,
                "query": query,
                "geographic_bounds": bounds,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    artifacts = tuple(
        SourceArtifact(source_path=path, case_relative_path=path.relative_to(working).as_posix())
        for path in (response_path, request_path)
    )
    return layer, artifacts


def _vector_tile_coordinate(
    tile_x: int,
    tile_y: int,
    local_x: float,
    local_y: float,
    *,
    zoom: int,
    extent: int,
) -> tuple[float, float]:
    tile_count = 2**zoom
    longitude = (tile_x + local_x / extent) / tile_count * 360.0 - 180.0
    slippy_y = tile_y + (extent - local_y) / extent
    latitude = math.degrees(
        math.atan(math.sinh(math.pi * (1.0 - 2.0 * slippy_y / tile_count)))
    )
    return longitude, latitude


# 国土地理院ベクトルタイルから詳細な建物外周を取得する．
def acquire_gsi_vector_buildings(
    config: OsmBuildingConfig,
    *,
    heightmap: Heightmap,
    coordinate_system: LocalCoordinateSystem,
    provenance: TerrainProvenance | None,
    working_directory: str | Path,
    session: requests.Session | None = None,
) -> tuple[PolygonFeatureLayer, tuple[SourceArtifact, ...]]:
    try:
        import mapbox_vector_tile
    except ImportError as error:
        raise TerrainAcquisitionError(
            "mapbox-vector-tile is required for GSI building vector tiles"
        ) from error

    bounds, projected_crs = _require_geographic_case(coordinate_system, provenance)
    west, south, east, north = bounds
    corner_lon = np.array([west, east, west, east])
    corner_lat = np.array([south, south, north, north])
    tile_x, tile_y, _, _ = _tile_coordinates(corner_lon, corner_lat, config.gsi_zoom)
    min_x, max_x = int(tile_x.min()), int(tile_x.max())
    min_y, max_y = int(tile_y.min()), int(tile_y.max())
    working = Path(working_directory)
    tile_root = working / "source" / "gsi" / "building_vector"
    client = session or requests.Session()
    client.headers.update({"User-Agent": "wildlife-tracking-sim/0.1"})
    transformer = Transformer.from_crs("EPSG:4326", projected_crs, always_xy=True)
    linework = []
    tile_paths = []
    for current_y in range(min_y, max_y + 1):
        for current_x in range(min_x, max_x + 1):
            tile_path = (
                tile_root / str(config.gsi_zoom) / str(current_x) / f"{current_y}.pbf"
            )
            if tile_path.is_file():
                content = tile_path.read_bytes()
            elif config.offline:
                raise TerrainDataUnavailableError(
                    f"cached GSI building tile not found: {tile_path}"
                )
            else:
                url = GSI_VECTOR_URL.format(
                    z=config.gsi_zoom,
                    x=current_x,
                    y=current_y,
                )
                try:
                    response = client.get(url, timeout=30)
                    response.raise_for_status()
                except requests.RequestException as error:
                    raise TerrainAcquisitionError(
                        f"GSI building vector request failed for {url}: {error}"
                    ) from error
                content = response.content
                tile_path.parent.mkdir(parents=True, exist_ok=True)
                tile_path.write_bytes(content)
            tile_paths.append(tile_path)
            document = mapbox_vector_tile.decode(content)
            layer = document.get("building")
            if not layer:
                continue
            extent = int(layer.get("extent", 4096))
            for feature in layer.get("features", []):
                geometry = feature.get("geometry") or {}
                geometry_type = geometry.get("type")
                coordinates = geometry.get("coordinates") or []
                parts = coordinates if geometry_type == "MultiLineString" else (coordinates,)
                if geometry_type not in {"LineString", "MultiLineString"}:
                    continue
                for part in parts:
                    if len(part) < 2:
                        continue
                    geographic = [
                        _vector_tile_coordinate(
                            current_x,
                            current_y,
                            float(point[0]),
                            float(point[1]),
                            zoom=config.gsi_zoom,
                            extent=extent,
                        )
                        for point in part
                    ]
                    projected = [transformer.transform(*point) for point in geographic]
                    linework.append(LineString(projected))

    case_bounds = box(
        heightmap.bounds.min_x_m,
        heightmap.bounds.min_y_m,
        heightmap.bounds.max_x_m,
        heightmap.bounds.max_y_m,
    )
    polygons = list(polygonize(unary_union(linework))) if linework else []
    features = []
    for feature_id, polygon in enumerate(polygons, start=1):
        geometry = polygon.intersection(case_bounds)
        if geometry.is_empty or geometry.area < 4.0:
            continue
        if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": mapping(geometry),
                "properties": {
                    "gsi_feature_id": feature_id,
                    "height_m": None,
                    "assumed_height_m": config.assumed_height_m,
                    "footprint_source": "GSI experimental_bvmap",
                },
            }
        )
    layer = PolygonFeatureLayer(
        layer_type="buildings",
        status=FeatureLayerStatus.AVAILABLE if features else FeatureLayerStatus.EMPTY,
        coordinate_system_name=coordinate_system.name,
        features=tuple(features),
        source="GSI Vector experimental_bvmap",
        assumed_height_m=config.assumed_height_m,
    )
    request_path = tile_root / "request.json"
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text(
        json.dumps(
            {
                "source": "GSI experimental_bvmap",
                "zoom": config.gsi_zoom,
                "tile_bounds": [min_x, min_y, max_x, max_y],
                "geographic_bounds": bounds,
                "building_count": len(features),
                "height_note": "tile does not contain actual height; assumed_height_m is used",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    artifacts = tuple(
        SourceArtifact(source_path=path, case_relative_path=path.relative_to(working).as_posix())
        for path in (*tile_paths, request_path)
    )
    return layer, artifacts


def _merge_building_layers(
    primary: PolygonFeatureLayer,
    supplemental: PolygonFeatureLayer,
) -> PolygonFeatureLayer:
    merged = []
    supplemental_geometries = [shape(feature["geometry"]) for feature in supplemental.features]
    supplemental_used: set[int] = set()
    for feature in primary.features:
        geometry = shape(feature["geometry"])
        properties = dict(feature.get("properties") or {})
        overlaps = [
            (geometry.intersection(candidate).area, index)
            for index, candidate in enumerate(supplemental_geometries)
            if geometry.intersects(candidate)
        ]
        if overlaps:
            _, best_index = max(overlaps)
            supplemental_used.add(best_index)
            supplemental_properties = dict(
                supplemental.features[best_index].get("properties") or {}
            )
            for key in ("osm_id", "name", "building", "height_m"):
                if supplemental_properties.get(key) is not None:
                    properties[key] = supplemental_properties[key]
            properties["supplemented_by_osm"] = True
        merged.append(
            {"type": "Feature", "geometry": feature["geometry"], "properties": properties}
        )
    for index, feature in enumerate(supplemental.features):
        if index not in supplemental_used:
            merged.append(feature)
    return PolygonFeatureLayer(
        layer_type="buildings",
        status=FeatureLayerStatus.AVAILABLE if merged else FeatureLayerStatus.EMPTY,
        coordinate_system_name=primary.coordinate_system_name,
        features=tuple(merged),
        source="GSI Vector building footprints supplemented by OpenStreetMap",
        assumed_height_m=primary.assumed_height_m,
    )


def _acquire_buildings(
    config: OsmBuildingConfig,
    *,
    heightmap: Heightmap,
    coordinate_system: LocalCoordinateSystem,
    provenance: TerrainProvenance | None,
    working_directory: str | Path,
) -> tuple[PolygonFeatureLayer, tuple[SourceArtifact, ...]]:
    common = {
        "heightmap": heightmap,
        "coordinate_system": coordinate_system,
        "provenance": provenance,
        "working_directory": working_directory,
    }
    if config.source == "osm":
        return acquire_osm_buildings(config, **common)
    gsi_layer, gsi_artifacts = acquire_gsi_vector_buildings(config, **common)
    if config.source == "gsi_vector":
        return gsi_layer, gsi_artifacts
    try:
        osm_layer, osm_artifacts = acquire_osm_buildings(config, **common)
    except TerrainAcquisitionError as error:
        working = Path(working_directory)
        error_path = working / "source" / "osm" / "request_error.json"
        error_path.parent.mkdir(parents=True, exist_ok=True)
        error_path.write_text(
            json.dumps({"error": str(error), "fallback": "GSI Vector buildings"}, indent=2),
            encoding="utf-8",
        )
        return gsi_layer, gsi_artifacts + (
            SourceArtifact(
                source_path=error_path,
                case_relative_path=error_path.relative_to(working).as_posix(),
            ),
        )
    return _merge_building_layers(gsi_layer, osm_layer), gsi_artifacts + osm_artifacts


# 環境判定に必要な画像，土地被覆，建物をまとめて取得する．
def acquire_detection_sources(
    *,
    imagery_config: GsiImageryConfig,
    landcover_config: WorldCoverConfig,
    building_config: OsmBuildingConfig,
    heightmap: Heightmap,
    coordinate_system: LocalCoordinateSystem,
    provenance: TerrainProvenance | None,
    working_directory: str | Path,
) -> DetectionSourceResult:
    imagery, imagery_artifacts = acquire_gsi_imagery(
        imagery_config,
        heightmap=heightmap,
        coordinate_system=coordinate_system,
        provenance=provenance,
        working_directory=working_directory,
    )
    landcover, landcover_artifacts = acquire_worldcover(
        landcover_config,
        heightmap=heightmap,
        coordinate_system=coordinate_system,
        provenance=provenance,
        working_directory=working_directory,
    )
    buildings, building_artifacts = _acquire_buildings(
        building_config,
        heightmap=heightmap,
        coordinate_system=coordinate_system,
        provenance=provenance,
        working_directory=working_directory,
    )
    return DetectionSourceResult(
        imagery=imagery,
        landcover=landcover,
        buildings=buildings,
        source_artifacts=imagery_artifacts + landcover_artifacts + building_artifacts,
    )
