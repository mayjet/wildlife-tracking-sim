class EnvironmentConfigurationError(ValueError):
    pass


class TerrainAcquisitionError(RuntimeError):
    pass


class TerrainDataUnavailableError(TerrainAcquisitionError):
    pass


class TerrainMissingDataError(TerrainAcquisitionError):
    pass
