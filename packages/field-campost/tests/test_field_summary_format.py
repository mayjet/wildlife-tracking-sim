from field_campost import format_field_summary_japanese


def test_field_summary_is_formatted_for_researcher_reading():
    summary = {
        "case_id": "sample-case",
        "scene": {
            "width_m": 2005.0,
            "height_m": 2005.0,
            "horizontal_area_m2": 4_020_025.0,
            "terrain_surface_area_m2": 4_259_165.0,
            "source_area_reduction_ratio": 0.553,
        },
        "terrain": {
            "cell_size_m": 5.0,
            "width_cells": 401,
            "height_cells": 401,
            "elevation_min_m": 935.89,
            "elevation_max_m": 1300.18,
            "elevation_mean_m": 1107.62,
            "relief_m": 364.29,
            "slope_mean_deg": 16.52,
            "slope_max_deg": 62.82,
            "missing_cell_count": 0,
        },
        "regions": {
            "farm_area_m2": 738_301.0,
            "monitoring": {"feature_count": 1, "area_m2": 738_301.0},
            "forest": {"feature_count": 9, "area_m2": 2_911_850.0},
            "open_land": {"feature_count": 27, "area_m2": 882_650.0},
            "buildings": {"feature_count": 140, "area_m2": 15_453.0},
            "facility_buildings": {"feature_count": 56, "area_m2": 8_412.0},
        },
        "mesh": {
            "vertex_count": 160_801,
            "triangle_count": 320_000,
            "usd_size_bytes": 77_303_195,
        },
    }

    rendered = format_field_summary_japanese(summary)

    assert "東西距離: 2,005 m" in rendered
    assert "高低差: 364.29 m" in rendered
    assert "建物: 140棟" in rendered
    assert "USDファイルサイズ:" in rendered
