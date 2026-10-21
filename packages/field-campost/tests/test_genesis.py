from field_campost import inspect_genesis


def test_genesis_status_is_reportable_without_optional_dependency():
    status = inspect_genesis()

    assert isinstance(status.installed, bool)
    assert isinstance(status.usd_support_available, bool)
    assert status.reason
