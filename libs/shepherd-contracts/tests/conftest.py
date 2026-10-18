from __future__ import annotations

import pytest

from shepherd_contracts import (
    AxisAlignedBounds2D,
    CaseSpec,
    EnvironmentDataRefs,
    FarmBoundarySpec,
    LocalCoordinateSystem,
)


@pytest.fixture
def case_spec() -> CaseSpec:
    return CaseSpec(
        schema_version="1.0",
        case_id="farm-a",
        coordinate_system=LocalCoordinateSystem(
            name="farm-a-local",
            origin_description="South-west survey marker",
            vertical_datum="local ground datum",
            geographic_conversion="Translate from EPSG:6677 then rotate to local ENU",
            geographic_crs="EPSG:4326",
            projected_crs="EPSG:6677",
        ),
        environment=EnvironmentDataRefs(
            terrain="terrain.tif",
            landcover="landcover.tif",
            traversability="traversability.tif",
            environment_usd="environment.usd",
            source_directory="source",
        ),
        farm_boundary=FarmBoundarySpec(
            data_ref="farm_boundary.geojson",
            bounds=AxisAlignedBounds2D(
                min_x_m=0.0,
                min_y_m=0.0,
                max_x_m=500.0,
                max_y_m=300.0,
            ),
        ),
    )

