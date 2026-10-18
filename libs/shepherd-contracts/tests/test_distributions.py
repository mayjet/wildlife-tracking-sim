from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from shepherd_contracts import (
    GaussianPositionDistribution,
    GridPositionDistribution,
    GridValueSemantics,
    Particle2D,
    ParticlePositionDistribution,
    Position2D,
    PositionDistribution,
)


def test_distribution_union_distinguishes_all_formats() -> None:
    adapter = TypeAdapter(PositionDistribution)
    gaussian = adapter.validate_python(
        {
            "kind": "gaussian",
            "mean": {"x_m": 0.0, "y_m": 1.0},
            "covariance_m2": ((2.0, 0.5), (0.5, 1.0)),
        }
    )
    particles = adapter.validate_python(
        {
            "kind": "particles",
            "particles": (
                {"position": {"x_m": 0.0, "y_m": 0.0}, "weight": 0.4},
                {"position": {"x_m": 1.0, "y_m": 1.0}, "weight": 0.6},
            ),
        }
    )
    grid = adapter.validate_python(
        {
            "kind": "grid",
            "cell_size_m": 5.0,
            "origin": {"x_m": 2.5, "y_m": 2.5},
            "value_semantics": "PROBABILITY_MASS",
            "values": ((0.25, 0.25), (0.25, 0.25)),
        }
    )
    assert isinstance(gaussian, GaussianPositionDistribution)
    assert isinstance(particles, ParticlePositionDistribution)
    assert isinstance(grid, GridPositionDistribution)


def test_gaussian_rejects_non_symmetric_covariance() -> None:
    with pytest.raises(ValidationError):
        GaussianPositionDistribution(
            mean=Position2D(x_m=0.0, y_m=0.0),
            covariance_m2=((1.0, 0.5), (0.2, 1.0)),
        )


def test_particles_require_normalized_weights() -> None:
    with pytest.raises(ValidationError):
        ParticlePositionDistribution(
            particles=(
                Particle2D(position=Position2D(x_m=0.0, y_m=0.0), weight=0.2),
                Particle2D(position=Position2D(x_m=1.0, y_m=1.0), weight=0.2),
            )
        )


@pytest.mark.parametrize("cell_size_m", [1.0, 5.0, 10.0])
def test_grid_supports_required_resolutions(cell_size_m: float) -> None:
    grid = GridPositionDistribution(
        cell_size_m=cell_size_m,
        origin=Position2D(x_m=cell_size_m / 2.0, y_m=cell_size_m / 2.0),
        value_semantics=GridValueSemantics.PROBABILITY_MASS,
        values=((0.5, 0.5),),
    )
    assert grid.cell_size_m == cell_size_m
    assert grid.axis_order.value == "YX"
    assert grid.origin_is_cell_center is True


def test_grid_rejects_non_rectangular_values() -> None:
    with pytest.raises(ValidationError):
        GridPositionDistribution(
            cell_size_m=5.0,
            origin=Position2D(x_m=2.5, y_m=2.5),
            value_semantics=GridValueSemantics.PROBABILITY_MASS,
            values=((0.25, 0.25), (0.5,)),
        )


def test_grid_rejects_non_positive_cell_size() -> None:
    with pytest.raises(ValidationError):
        GridPositionDistribution(
            cell_size_m=0.0,
            origin=Position2D(x_m=0.0, y_m=0.0),
            value_semantics=GridValueSemantics.PROBABILITY_MASS,
            values=((1.0,),),
        )

