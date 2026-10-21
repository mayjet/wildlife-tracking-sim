from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
import rasterio
from PIL import Image
from pyproj import CRS
from rasterio.transform import from_origin

from field_environment import (
    FileTerrainConfig,
    GeographicTerrainConfig,
    acquire_alos_aw3d30,
    acquire_gsi_elevation,
    decode_gsi_elevation_png,
    geographic_bounds_for_square,
    import_geotiff,
)
from field_environment.sources import alos as alos_module
from field_environment.sources import gsi as gsi_module
from field_environment.sources.common import write_source_geotiff


def _png_with_encoded_values(values: np.ndarray) -> bytes:
    encoded = np.asarray(values, dtype=np.int64)
    rgb = np.stack(
        ((encoded >> 16) & 255, (encoded >> 8) & 255, encoded & 255), axis=-1
    ).astype(np.uint8)
    output = BytesIO()
    Image.fromarray(rgb, mode="RGB").save(output, format="PNG")
    return output.getvalue()


def test_geographic_bounds_use_metres_not_degrees() -> None:
    west, south, east, north = geographic_bounds_for_square(35.0, 139.0, 3000.0)
    assert 0.02 < east - west < 0.04
    assert 0.02 < north - south < 0.04


def test_gsi_png_decoder_handles_positive_negative_and_nodata() -> None:
    encoded = np.array([[12345, 2**24 - 250, 2**23]], dtype=np.int64)
    decoded = decode_gsi_elevation_png(_png_with_encoded_values(encoded))
    np.testing.assert_allclose(decoded[0, :2], [123.45, -2.5], atol=1e-6)
    assert np.isnan(decoded[0, 2])


def test_gsi_adapter_uses_common_south_to_north_grid(tmp_path, monkeypatch) -> None:
    tile = np.repeat(np.arange(256, dtype=np.float32)[:, None], 256, axis=1)

    def fake_tile(dataset, zoom, tile_x, tile_y, *, cache_root, offline, session):
        path = cache_root / dataset / str(zoom) / str(tile_x) / f"{tile_y}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_png_with_encoded_values((tile * 100).astype(np.int64)))
        return tile, path

    monkeypatch.setattr(gsi_module, "_read_or_download_tile", fake_tile)
    result = acquire_gsi_elevation(
        GeographicTerrainConfig(
            source="gsi",
            center_lat=35.0,
            center_lon=139.0,
            size_m=100.0,
            cell_size_m=20.0,
            gsi_datasets=("dem_png",),
        ),
        case_id="gsi-test",
        working_directory=tmp_path,
    )
    assert result.heightmap.values.shape == (5, 5)
    assert np.isfinite(result.heightmap.values).all()
    assert result.provenance.source == "gsi"


def test_alos_adapter_reprojects_downloaded_dsm(tmp_path, monkeypatch) -> None:
    def fake_download(bounds, output_path):
        values = np.arange(400, dtype=np.float32).reshape(20, 20)
        transform = from_origin(138.99, 35.01, 0.001, 0.001)
        write_source_geotiff(
            output_path, values, transform=transform, crs="EPSG:4326", nodata=np.nan
        )
        return values, transform, (138.99, 34.99, 139.01, 35.01)

    monkeypatch.setattr(alos_module, "_download_aw3d30", fake_download)
    result = acquire_alos_aw3d30(
        GeographicTerrainConfig(
            source="alos",
            center_lat=35.0,
            center_lon=139.0,
            size_m=100.0,
            cell_size_m=20.0,
        ),
        case_id="alos-test",
        working_directory=tmp_path,
    )
    assert result.heightmap.values.shape == (5, 5)
    assert result.provenance.elevation_type == "DSM"
    assert (tmp_path / "source/jaxa/request.json").is_file()


def test_geotiff_import_converts_north_up_to_internal_south_up(tmp_path) -> None:
    source_path = tmp_path / "input.tif"
    source_crs = CRS.from_proj4(
        "+proj=aeqd +lat_0=35 +lon_0=139 +datum=WGS84 +units=m +no_defs"
    )
    north_up = np.repeat(np.arange(10, 0, -1, dtype=np.float32)[:, None], 10, axis=1)
    with rasterio.open(
        source_path,
        "w",
        driver="GTiff",
        width=10,
        height=10,
        count=1,
        dtype="float32",
        crs=source_crs,
        transform=from_origin(-100.0, 100.0, 20.0, 20.0),
    ) as dataset:
        dataset.write(north_up, 1)
    result = import_geotiff(
        FileTerrainConfig(source="file", path=str(source_path), cell_size_m=20, size_m=160),
        case_id="file-test",
        working_directory=tmp_path / "working",
    )
    assert result.heightmap.values[-1].mean() > result.heightmap.values[0].mean()
    assert result.provenance.source_crs is not None


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("RUN_EXTERNAL_TERRAIN_TESTS") != "1",
    reason="set RUN_EXTERNAL_TERRAIN_TESTS=1 for official service integration",
)
@pytest.mark.parametrize("source", ["alos", "gsi"])
def test_official_elevation_service(source: str, tmp_path: Path) -> None:
    result = (
        acquire_alos_aw3d30 if source == "alos" else acquire_gsi_elevation
    )(
        GeographicTerrainConfig(
            source=source,
            center_lat=35.685,
            center_lon=139.77,
            size_m=300.0,
            cell_size_m=30.0,
            gsi_datasets=("dem5a_png", "dem5b_png", "dem5c_png", "dem_png"),
        ),
        case_id=f"{source}-external",
        working_directory=tmp_path,
    )
    assert np.isfinite(result.heightmap.values).all()
