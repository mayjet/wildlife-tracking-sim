from .constant_velocity import ConstantVelocityTracker


class LastObservationTracker(ConstantVelocityTracker):
    def __init__(self):
        super().__init__(preserve_velocity=False)

