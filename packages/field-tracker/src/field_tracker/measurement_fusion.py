from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from shepherd_contracts import AgeClass, Observation


@dataclass(frozen=True)
class FusedMeasurement:
    measurement_id: str
    timestamp_s: float
    position: np.ndarray
    age_class: AgeClass
    source_observation_ids: tuple[str, ...]
    source_camera_ids: tuple[str, ...]


# 複数カメラが同じ位置を観測したPerfect Observationを一測定へ統合する．
def fuse_observations(
    observations: tuple[Observation, ...],
    tolerance_m: float,
) -> tuple[FusedMeasurement, ...]:
    clusters: list[list[Observation]] = []
    for observation in sorted(observations, key=lambda item: item.observation_id):
        position = np.asarray((observation.position.x_m, observation.position.y_m))
        for cluster in clusters:
            center = np.mean(
                [(item.position.x_m, item.position.y_m) for item in cluster], axis=0
            )
            if float(np.linalg.norm(position - center)) <= tolerance_m:
                cluster.append(observation)
                break
        else:
            clusters.append([observation])
    measurements = []
    for index, cluster in enumerate(clusters):
        timestamp_s = cluster[0].timestamp_s
        if any(item.timestamp_s != timestamp_s for item in cluster):
            raise ValueError("observations from different timestamps cannot be fused")
        ages = {item.age_class for item in cluster if item.age_class is not AgeClass.UNKNOWN}
        age_class = ages.pop() if len(ages) == 1 else AgeClass.UNKNOWN
        measurements.append(
            FusedMeasurement(
                measurement_id=f"measurement-{timestamp_s:g}-{index:06d}",
                timestamp_s=timestamp_s,
                position=np.mean(
                    [(item.position.x_m, item.position.y_m) for item in cluster], axis=0
                ),
                age_class=age_class,
                source_observation_ids=tuple(item.observation_id for item in cluster),
                source_camera_ids=tuple(sorted({item.camera_id for item in cluster})),
            )
        )
    return tuple(measurements)

