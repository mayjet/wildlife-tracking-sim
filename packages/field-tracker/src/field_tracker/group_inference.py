from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np
from shepherd_contracts import GroupTrackEstimate, Position2D, TrackStatus

from .config import TrackerConfig
from .lifecycle import TrackRecord, TrackerLifecycleState


@dataclass(frozen=True)
class GroupLifecycleEvent:
    timestamp_s: float
    event_type: str
    group_track_id: str
    related_group_track_ids: tuple[str, ...]
    member_track_ids: tuple[str, ...]


class GroupInferer:
    def __init__(self, config: TrackerConfig):
        self.config = config
        self._join_durations: dict[tuple[str, str], float] = defaultdict(float)
        self._leave_durations: dict[tuple[str, str], float] = defaultdict(float)
        self._active_pairs: set[tuple[str, str]] = set()
        self._last_timestamp_s: float | None = None
        self._groups: dict[str, frozenset[str]] = {}
        self._next_group_number = 1
        self.events: list[GroupLifecycleEvent] = []

    def _update_pairs(
        self, active: tuple[TrackRecord, ...], delta_s: float
    ) -> None:
        active_ids = {record.track_id for record in active}
        self._active_pairs = {
            pair for pair in self._active_pairs if set(pair) <= active_ids
        }
        for first_index, first in enumerate(active):
            for second in active[first_index + 1 :]:
                key = tuple(sorted((first.track_id, second.track_id)))
                distance_m = float(np.linalg.norm(first.position - second.position))
                velocity_difference_mps = float(
                    np.linalg.norm(first.velocity - second.velocity)
                )
                similar_velocity = (
                    velocity_difference_mps
                    <= self.config.group_velocity_difference_mps
                )
                within_join = distance_m <= self.config.group_distance_m
                within_leave = (
                    distance_m <= self.config.resolved_group_leave_distance_m
                )
                if key in self._active_pairs:
                    if within_leave and similar_velocity:
                        self._leave_durations[key] = 0.0
                    else:
                        self._leave_durations[key] += max(delta_s, 0.0)
                        if (
                            self._leave_durations[key]
                            >= self.config.group_leave_confirmation_s
                        ):
                            self._active_pairs.discard(key)
                            self._join_durations[key] = 0.0
                            self._leave_durations[key] = 0.0
                elif within_join and similar_velocity:
                    self._join_durations[key] += max(delta_s, 0.0)
                    if self._join_durations[key] >= self.config.group_confirmation_s:
                        self._active_pairs.add(key)
                        self._leave_durations[key] = 0.0
                else:
                    self._join_durations[key] = 0.0

    def _components(self, active: tuple[TrackRecord, ...]) -> list[frozenset[str]]:
        adjacency = {record.track_id: set() for record in active}
        for first, second in self._active_pairs:
            if first in adjacency and second in adjacency:
                adjacency[first].add(second)
                adjacency[second].add(first)
        components: list[frozenset[str]] = []
        visited: set[str] = set()
        for track_id in sorted(adjacency):
            if track_id in visited:
                continue
            stack = [track_id]
            component: set[str] = set()
            while stack:
                current = stack.pop()
                if current in visited:
                    continue
                visited.add(current)
                component.add(current)
                stack.extend(adjacency[current] - visited)
            if len(component) >= 2:
                components.append(frozenset(component))
        return components

    @staticmethod
    def _overlap(first: frozenset[str], second: frozenset[str]) -> float:
        union = first | second
        return len(first & second) / len(union) if union else 0.0

    def _assign_group_ids(
        self, timestamp_s: float, components: list[frozenset[str]]
    ) -> dict[str, frozenset[str]]:
        candidates = sorted(
            (
                (self._overlap(previous, component), group_id, index)
                for group_id, previous in self._groups.items()
                for index, component in enumerate(components)
                if previous & component
            ),
            reverse=True,
        )
        assigned_groups: set[str] = set()
        assigned_components: set[int] = set()
        resolved: dict[str, frozenset[str]] = {}
        for overlap, group_id, component_index in candidates:
            if overlap <= 0.0:
                continue
            if group_id in assigned_groups or component_index in assigned_components:
                continue
            resolved[group_id] = components[component_index]
            assigned_groups.add(group_id)
            assigned_components.add(component_index)
        for component_index, component in enumerate(components):
            if component_index in assigned_components:
                continue
            group_id = f"group-{self._next_group_number:06d}"
            self._next_group_number += 1
            resolved[group_id] = component
            self.events.append(
                GroupLifecycleEvent(
                    timestamp_s,
                    "CREATED",
                    group_id,
                    (),
                    tuple(sorted(component)),
                )
            )

        for old_group_id, old_members in self._groups.items():
            overlaps = tuple(
                sorted(
                    group_id
                    for group_id, members in resolved.items()
                    if old_members & members
                )
            )
            if len(overlaps) > 1:
                self.events.append(
                    GroupLifecycleEvent(
                        timestamp_s,
                        "SPLIT",
                        old_group_id,
                        overlaps,
                        tuple(sorted(old_members)),
                    )
                )
            elif old_group_id not in resolved:
                merged_into = bool(overlaps) and (
                    sum(
                        1
                        for source_members in self._groups.values()
                        if source_members & resolved[overlaps[0]]
                    )
                    > 1
                )
                self.events.append(
                    GroupLifecycleEvent(
                        timestamp_s,
                        "MERGED_INTO" if merged_into else "RETIRED",
                        old_group_id,
                        overlaps,
                        tuple(sorted(old_members)),
                    )
                )
        for group_id, members in resolved.items():
            sources = tuple(
                sorted(
                    old_group_id
                    for old_group_id, old_members in self._groups.items()
                    if old_members & members
                )
            )
            if len(sources) > 1:
                self.events.append(
                    GroupLifecycleEvent(
                        timestamp_s,
                        "MERGED",
                        group_id,
                        sources,
                        tuple(sorted(members)),
                    )
                )
        self._groups = resolved
        return resolved

    def infer(
        self,
        timestamp_s: float,
        records: tuple[TrackRecord, ...],
    ) -> tuple[GroupTrackEstimate, ...]:
        active = tuple(
            record
            for record in records
            if record.lifecycle_state
            in {
                TrackerLifecycleState.TRACKED,
                TrackerLifecycleState.LOST,
                TrackerLifecycleState.AMBIGUOUS,
            }
        )
        delta_s = (
            0.0
            if self._last_timestamp_s is None
            else timestamp_s - self._last_timestamp_s
        )
        if delta_s < 0.0:
            raise ValueError("group inference timestamps must be monotonic")
        self._last_timestamp_s = timestamp_s
        self._update_pairs(active, delta_s)
        groups = self._assign_group_ids(timestamp_s, self._components(active))
        by_id = {record.track_id: record for record in active}
        estimates = []
        for group_id, component in sorted(groups.items()):
            members = [by_id[track_id] for track_id in sorted(component)]
            center = np.mean([record.position for record in members], axis=0)
            observed_count = sum(
                np.isclose(record.last_observed_timestamp_s, timestamp_s)
                for record in members
            )
            estimates.append(
                GroupTrackEstimate(
                    group_track_id=group_id,
                    timestamp_s=timestamp_s,
                    center=Position2D(x_m=float(center[0]), y_m=float(center[1])),
                    estimated_member_count=len(members),
                    observed_member_count=observed_count,
                    member_track_ids=tuple(sorted(component)),
                    status=(
                        TrackStatus.OBSERVED
                        if observed_count
                        else TrackStatus.PREDICTED
                    ),
                )
            )
        return tuple(estimates)
