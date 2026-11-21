from __future__ import annotations


def test_visualizer_import_does_not_require_rerun() -> None:
    import field_visualizer

    assert callable(field_visualizer.log_tracking_replay)
