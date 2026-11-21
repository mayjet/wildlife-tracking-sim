from __future__ import annotations

import numpy as np


def initial_state(position: np.ndarray, measurement_variance: float) -> tuple[np.ndarray, np.ndarray]:
    state = np.asarray((position[0], position[1], 0.0, 0.0), dtype=np.float64)
    covariance = np.diag((measurement_variance, measurement_variance, 10.0, 10.0))
    return state, covariance


def predict_constant_velocity(
    state: np.ndarray,
    covariance: np.ndarray,
    delta_s: float,
    process_variance: float,
) -> tuple[np.ndarray, np.ndarray]:
    transition = np.asarray(
        (
            (1.0, 0.0, delta_s, 0.0),
            (0.0, 1.0, 0.0, delta_s),
            (0.0, 0.0, 1.0, 0.0),
            (0.0, 0.0, 0.0, 1.0),
        )
    )
    process = np.eye(4) * process_variance * max(delta_s, 1.0e-6)
    return transition @ state, transition @ covariance @ transition.T + process


def update_position(
    state: np.ndarray,
    covariance: np.ndarray,
    measurement: np.ndarray,
    measurement_variance: float,
) -> tuple[np.ndarray, np.ndarray]:
    observation = np.asarray(((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0)))
    noise = np.eye(2) * measurement_variance
    residual = measurement - observation @ state
    residual_covariance = observation @ covariance @ observation.T + noise
    gain = covariance @ observation.T @ np.linalg.inv(residual_covariance)
    updated = state + gain @ residual
    updated_covariance = (np.eye(4) - gain @ observation) @ covariance
    return updated, updated_covariance

