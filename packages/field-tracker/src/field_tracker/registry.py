from __future__ import annotations

from importlib import import_module

from shepherd_contracts import Tracker

from .trackers import ConstantVelocityTracker, LastObservationTracker


def available_tracker_methods() -> tuple[str, ...]:
    return ("last_observation", "constant_velocity")


def create_tracker(method: str, *, module: str | None = None) -> Tracker:
    if method == "last_observation":
        return LastObservationTracker()
    if method == "constant_velocity":
        return ConstantVelocityTracker()
    module_name = module or f"workspace.tracking.{method}"
    imported = import_module(module_name)
    factory = getattr(imported, "create_tracker", None)
    if factory is None:
        raise AttributeError(f"custom tracker module must define create_tracker(): {module_name}")
    tracker = factory()
    if not isinstance(tracker, Tracker):
        raise TypeError(f"create_tracker() did not return Tracker Protocol: {module_name}")
    return tracker

