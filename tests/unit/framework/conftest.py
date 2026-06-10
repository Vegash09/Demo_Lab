"""Shared fixture: write a domain config tree (domain.yml + layer folders)."""

import pytest

DOMAIN_YML = """
schema_version: 1
domain: sales
imports:
  - sales_etl.transforms.sales
catalog_conf: datalab.catalog
layers:
  bronze: {schema_conf: datalab.bronze_schema}
  silver: {schema_conf: datalab.silver_schema}
  gold: {schema_conf: datalab.gold_schema}
"""


@pytest.fixture()
def write_domain(tmp_path):
    """write_domain({'silver/customers.yml': '...'}) -> domain config dir."""

    def _write(tables: dict[str, str], domain_yml: str = DOMAIN_YML):
        (tmp_path / "domain.yml").write_text(domain_yml)
        for rel, text in tables.items():
            path = tmp_path / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        return tmp_path

    return _write
