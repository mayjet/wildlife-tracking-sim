from __future__ import annotations

import pytest
from pydantic import ValidationError

from shepherd_contracts import (
    GroupTrackEstimate,
    Position2D,
    TrackEstimate,
    TrackingFrame,
    TrackStatus,
)


def test_individual_and_group_tracks_are_separate() -> None:
    track = TrackEstimate(
        track_id="track-1",
        timestamp_s=5.0,
        position=Position2D(x_m=10.0, y_m=20.0),
        status=TrackStatus.PREDICTED,
    )
    group = GroupTrackEstimate(
        group_track_id="group-1",
        timestamp_s=5.0,
        center=Position2D(x_m=12.0, y_m=21.0),
        estimated_member_count=3,
        observed_member_count=1,
        member_track_ids=("track-1",),
        status=TrackStatus.OBSERVED,
    )
    frame = TrackingFrame(timestamp_s=5.0, tracks=(track,), groups=(group,))
    assert isinstance(frame.tracks[0], TrackEstimate)
    assert isinstance(frame.groups[0], GroupTrackEstimate)
    assert frame.groups[0].center != frame.tracks[0].position


def test_group_observed_count_cannot_exceed_estimate() -> None:
    with pytest.raises(ValidationError):
        GroupTrackEstimate(
            group_track_id="group-1",
            timestamp_s=5.0,
            center=Position2D(x_m=12.0, y_m=21.0),
            estimated_member_count=1,
            observed_member_count=2,
            status=TrackStatus.OBSERVED,
        )

