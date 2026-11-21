from __future__ import annotations

from dataclasses import dataclass
from math import cos, pi, sin, sqrt

import numpy as np
from shepherd_contracts import AgeClass

from .herd_config import HerdProfile


@dataclass(frozen=True)
class HerdMember:
    truth_id: str
    age_class: AgeClass
    is_leader: bool
    longitudinal_offset_m: float
    lateral_offset_m: float
    speed_offset_mps: float


# seedから再現可能な群れ内配置と個体属性を生成する．
def create_herd_members(
    herd_id: str,
    profile: HerdProfile,
    seed: int,
) -> tuple[HerdMember, ...]:
    rng = np.random.default_rng(seed)
    ages = [AgeClass.ADULT] * profile.adult_count + [
        AgeClass.JUVENILE
    ] * profile.juvenile_count
    if ages:
        leader_age = AgeClass.ADULT if profile.adult_count else ages[0]
        ages.remove(leader_age)
        rng.shuffle(ages)
        ages.insert(0, leader_age)
    members = []
    golden_angle = pi * (3.0 - sqrt(5.0))
    for index in range(profile.deer_count):
        if index == 0:
            longitudinal = 0.0
            lateral = 0.0
        else:
            fraction = index / max(1, profile.deer_count - 1)
            radius = profile.minimum_separation_m + (
                profile.group_radius_m - profile.minimum_separation_m
            ) * sqrt(fraction)
            angle = index * golden_angle + float(rng.uniform(-0.15, 0.15))
            longitudinal = -abs(radius * cos(angle))
            lateral = radius * sin(angle)
        members.append(
            HerdMember(
                truth_id=f"{herd_id}-deer-{index + 1:03d}",
                age_class=ages[index],
                is_leader=index == 0,
                longitudinal_offset_m=float(longitudinal),
                lateral_offset_m=float(lateral),
                speed_offset_mps=(
                    0.0
                    if index == 0
                    else float(
                        rng.uniform(
                            -profile.speed_variation_mps,
                            profile.speed_variation_mps,
                        )
                    )
                ),
            )
        )
    return tuple(members)

