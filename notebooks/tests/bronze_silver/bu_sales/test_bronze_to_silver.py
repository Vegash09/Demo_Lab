# Minimal presence test notebook for bu_sales/bronze_to_silver
from datalab_etl import read_dataset, write_dataset, process_batch


def test_imports_available():
    assert callable(read_dataset)
    assert callable(write_dataset)
    assert callable(process_batch)


