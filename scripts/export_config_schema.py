"""Regenerate schemas/layer_config.schema.json from the Pydantic models.

Run via ``make schema`` after any change to datalab/framework/models.py.
The schema powers editor validation through the yaml-language-server header
comment in every config/<domain>/*.yml.
"""

from __future__ import annotations

import json
from pathlib import Path

from datalab.framework.models import LayerConfig

OUT = Path(__file__).resolve().parent.parent / "schemas" / "layer_config.schema.json"


def main() -> None:
    OUT.parent.mkdir(exist_ok=True)
    schema = LayerConfig.model_json_schema()
    OUT.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
