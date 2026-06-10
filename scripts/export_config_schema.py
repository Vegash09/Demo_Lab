"""Regenerate the JSON schemas under schemas/ from the Pydantic models.

Run via ``make schema`` after any change to datalab/framework/models.py.
The schemas power editor validation through the yaml-language-server header
comment in every config file:

    config/<domain>/domain.yml          -> domain_config.schema.json
    config/<domain>/<layer>/<table>.yml -> table_config.schema.json
"""

from __future__ import annotations

import json
from pathlib import Path

from datalab.framework.models import DomainConfig, TableFile

OUT_DIR = Path(__file__).resolve().parent.parent / "schemas"

EXPORTS = {
    "domain_config.schema.json": DomainConfig,
    "table_config.schema.json": TableFile,
}


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    for filename, model in EXPORTS.items():
        out = OUT_DIR / filename
        out.write_text(json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n")
        print(f"wrote {out}")


if __name__ == "__main__":
    main()
