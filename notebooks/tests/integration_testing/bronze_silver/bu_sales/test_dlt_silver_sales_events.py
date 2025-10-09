import pytest


@pytest.mark.dbconnect_only
def test_placeholder_dlt_dbconnect():
    # DLT runs inside the DLT engine; presence/marker-only check for CI wiring
    assert True

