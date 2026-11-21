from __future__ import annotations

from dataclasses import dataclass

from field_environment import EnvironmentCase

from ..herd_config import HerdSimulationConfig
from ..herd_simulator import simulate_herd
from ..routes import ResolvedRoute
from ..simulator import SimulationResult


@dataclass(frozen=True)
class FixedRouteHerdBehavior:
    config: HerdSimulationConfig

    def simulate(
        self,
        environment_case: EnvironmentCase,
        resolved_route: ResolvedRoute,
    ) -> SimulationResult:
        return simulate_herd(environment_case, resolved_route, self.config)

