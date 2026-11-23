from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from shepherd_contracts import GroundTruthFrame, ObservationFrame, ObservationPointLayout, TrackingFrame

from field_environment import EnvironmentCase

from .rerun_2d import _feature_lines, _polygon_lines, _rerun


class RerunLiveSession:
    """Run単位のRerun記録をWeb ViewerとRRDへ同時配信する．"""

    def __init__(
        self,
        *,
        run_id: str,
        recording_path: str | Path,
        grpc_url: str | None = None,
        application_id: str = "wildlife-tracking-benchmark",
        rerun_module: Any | None = None,
    ) -> None:
        rr = rerun_module or _rerun()
        self.rr = rr
        file_recording = rr.new_recording(application_id, recording_id=run_id)
        self.warnings: list[str] = []
        rr.save(Path(recording_path), recording=file_recording)
        recordings = [file_recording]
        if grpc_url:
            try:
                live_recording = rr.new_recording(application_id, recording_id=run_id)
                rr.connect(grpc_url, recording=live_recording)
                recordings.append(live_recording)
            except Exception as error:
                self.warnings.append(
                    f"live connection failed: {type(error).__name__}: {error}"
                )
        self.recordings = tuple(recordings)
        self.truth_paths: dict[str, list[list[float]]] = defaultdict(list)
        self.track_paths: dict[str, list[list[float]]] = defaultdict(list)

    def log_environment(
        self,
        environment_case: EnvironmentCase,
        observation_point_layout: ObservationPointLayout | None = None,
    ) -> None:
        rr = self.rr
        bounds = environment_case.heightmap.bounds
        self._log(
            "world/terrain_extent",
            rr.LineStrips2D(
                [[
                    [bounds.min_x_m, bounds.min_y_m],
                    [bounds.max_x_m, bounds.min_y_m],
                    [bounds.max_x_m, bounds.max_y_m],
                    [bounds.min_x_m, bounds.max_y_m],
                    [bounds.min_x_m, bounds.min_y_m],
                ]],
                colors=[120, 120, 120],
                radii=1.0,
            ),
            static=True,
        )
        self._log(
            "world/farm_boundary",
            rr.LineStrips2D(
                _polygon_lines(environment_case.farm_boundary.polygon),
                colors=[255, 0, 0],
                radii=1.5,
            ),
            static=True,
        )
        for name, layer, color in (
            ("forest", environment_case.forest, [30, 120, 30]),
            ("buildings", environment_case.buildings, [230, 140, 40]),
        ):
            lines = _feature_lines(layer)
            if lines:
                self._log(
                    f"world/{name}",
                    rr.LineStrips2D(lines, colors=color, radii=0.8),
                    static=True,
                )
        if observation_point_layout is not None:
            self._log(
                "world/observation_points",
                rr.Points2D(
                    [[point.position.x_m, point.position.y_m] for point in observation_point_layout.points],
                    colors=[30, 80, 255],
                    radii=2.0,
                    labels=[point.point_id for point in observation_point_layout.points],
                ),
                static=True,
            )

    def log_frame(
        self,
        *,
        timestamp_s: float,
        ground_truth: GroundTruthFrame | None = None,
        observations: ObservationFrame | None = None,
        tracking: TrackingFrame | None = None,
    ) -> None:
        rr = self.rr
        for recording in self.recordings:
            recording.set_time_seconds("simulation_time", float(timestamp_s))
        if ground_truth is not None:
            self._log(
                "world/ground_truth/current",
                rr.Points2D(
                    [[state.position.x_m, state.position.y_m] for state in ground_truth.states],
                    colors=[0, 180, 255],
                    radii=2.5,
                    labels=[state.truth_id for state in ground_truth.states],
                ),
            )
            for state in ground_truth.states:
                self.truth_paths[state.truth_id].append(
                    [state.position.x_m, state.position.y_m]
                )
            self._log(
                "world/ground_truth/history",
                rr.LineStrips2D(list(self.truth_paths.values()), colors=[0, 150, 220], radii=0.7),
            )
            centers = []
            labels = []
            states_by_group: dict[str, list] = defaultdict(list)
            for state in ground_truth.states:
                if state.group_truth_id is not None:
                    states_by_group[state.group_truth_id].append(state)
            for group_truth_id, states in sorted(states_by_group.items()):
                centers.append(
                    [
                        sum(state.position.x_m for state in states) / len(states),
                        sum(state.position.y_m for state in states) / len(states),
                    ]
                )
                labels.append(group_truth_id)
            self._log(
                "world/ground_truth/group_centers",
                rr.Points2D(centers, colors=[0, 110, 255], radii=4.0, labels=labels),
            )
        if observations is not None:
            self._log(
                "world/observations",
                rr.Points2D(
                    [[item.position.x_m, item.position.y_m] for item in observations.observations],
                    colors=[255, 255, 0],
                    radii=1.8,
                ),
            )
        if tracking is not None:
            observed = [item for item in tracking.tracks if item.status.value == "OBSERVED"]
            predicted = [item for item in tracking.tracks if item.status.value != "OBSERVED"]
            self._log(
                "world/tracks/observed",
                rr.Points2D(
                    [[item.position.x_m, item.position.y_m] for item in observed],
                    colors=[50, 220, 80],
                    radii=2.5,
                    labels=[item.track_id for item in observed],
                ),
            )
            self._log(
                "world/tracks/predicted",
                rr.Points2D(
                    [[item.position.x_m, item.position.y_m] for item in predicted],
                    colors=[255, 0, 255],
                    radii=2.5,
                    labels=[item.track_id for item in predicted],
                ),
            )
            for item in tracking.tracks:
                self.track_paths[item.track_id].append([item.position.x_m, item.position.y_m])
            self._log(
                "world/tracks/history",
                rr.LineStrips2D(list(self.track_paths.values()), colors=[60, 200, 100], radii=0.8),
            )
            self._log(
                "world/tracks/group_centers",
                rr.Points2D(
                    [[item.center.x_m, item.center.y_m] for item in tracking.groups],
                    colors=[255, 130, 0],
                    radii=4.0,
                    labels=[item.group_track_id for item in tracking.groups],
                ),
            )

    def close(self) -> None:
        for recording in self.recordings:
            try:
                recording.flush()
                recording.disconnect()
            except Exception as error:
                self.warnings.append(
                    f"recording close failed: {type(error).__name__}: {error}"
                )

    def _log(self, entity_path: str, entity, *, static: bool = False) -> None:
        for recording in self.recordings:
            try:
                recording.log(entity_path, entity, static=static)
            except Exception as error:
                self.warnings.append(
                    f"log failed for {entity_path}: {type(error).__name__}: {error}"
                )

    def __enter__(self) -> "RerunLiveSession":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
