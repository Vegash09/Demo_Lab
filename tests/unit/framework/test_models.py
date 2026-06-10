"""Model validation: discriminated unions + cross-field rules. No Spark."""

import pytest
from pydantic import ValidationError

from datalab.framework.models import (
    CloudFilesSource,
    DatasetSpec,
    LayerConfig,
    MaterializedViewTarget,
    StreamingTableTarget,
)


def _dataset(**overrides):
    base = {
        "name": "customers",
        "source": {"kind": "table", "name": "customers_raw", "as_stream": True},
        "target": {"kind": "streaming_table"},
    }
    base.update(overrides)
    return base


def _layer(**overrides):
    base = {
        "domain": "sales",
        "layer": "silver",
        "defaults": {"schema_conf": "datalab.silver_schema"},
        "datasets": [_dataset()],
    }
    base.update(overrides)
    return base


def test_discriminated_unions_dispatch():
    cfg = LayerConfig.model_validate(_layer())
    ds = cfg.datasets[0]
    assert ds.is_streaming
    assert isinstance(ds.target, StreamingTableTarget)

    gold = LayerConfig.model_validate(
        _layer(
            layer="gold",
            datasets=[
                _dataset(
                    source={"kind": "table", "name": "customers"},
                    target={"kind": "materialized_view"},
                )
            ],
        )
    )
    assert isinstance(gold.datasets[0].target, MaterializedViewTarget)
    assert not gold.datasets[0].is_streaming

    bronze = LayerConfig.model_validate(
        _layer(
            layer="bronze",
            datasets=[
                _dataset(
                    name="customers_raw",
                    source={"kind": "cloud_files", "path_conf": "datalab.landing"},
                )
            ],
        )
    )
    assert isinstance(bronze.datasets[0].source, CloudFilesSource)


def test_unknown_keys_are_rejected():
    with pytest.raises(ValidationError, match="extra_forbidden|Extra inputs"):
        LayerConfig.model_validate(_layer(extra_key="oops"))


def test_cdc_requires_streaming_source():
    with pytest.raises(ValidationError, match="streaming"):
        DatasetSpec.model_validate(
            _dataset(
                source={"kind": "table", "name": "customers_raw"},  # batch
                target={
                    "kind": "streaming_table",
                    "cdc": {"keys": ["customer_id"], "sequence_by": "_ingest_ts"},
                },
            )
        )


def test_materialized_view_rejects_streaming_source():
    with pytest.raises(ValidationError, match="batch"):
        DatasetSpec.model_validate(_dataset(target={"kind": "materialized_view"}))


def test_temporary_view_rejects_quarantine():
    with pytest.raises(ValidationError, match="temporary_view"):
        DatasetSpec.model_validate(
            _dataset(
                target={"kind": "temporary_view"},
                quality={
                    "checks": [{"check": {"function": "is_not_null", "arguments": {"column": "x"}}}],
                    "quarantine": {},
                },
            )
        )


def test_quarantine_requires_an_error_rule():
    with pytest.raises(ValidationError, match="criticality=error"):
        DatasetSpec.model_validate(
            _dataset(
                quality={
                    "checks": [
                        {
                            "criticality": "warn",
                            "check": {"function": "is_not_null", "arguments": {"column": "x"}},
                        }
                    ],
                    "quarantine": {},
                }
            )
        )


def test_metrics_require_include_warnings():
    with pytest.raises(ValidationError, match="include_warnings"):
        DatasetSpec.model_validate(
            _dataset(
                quality={
                    "checks": [{"check": {"function": "is_not_null", "arguments": {"column": "x"}}}],
                    "quarantine": {"include_warnings": False},
                    "metrics": {"enabled": True},
                }
            )
        )


def test_name_collisions_rejected():
    with pytest.raises(ValidationError, match="collides"):
        LayerConfig.model_validate(
            _layer(
                datasets=[
                    _dataset(),
                    _dataset(
                        name="other",
                        quality={
                            "checks": [
                                {"check": {"function": "is_not_null", "arguments": {"column": "x"}}}
                            ],
                            "quarantine": {"name": "customers"},  # collides with dataset
                        },
                    ),
                ]
            )
        )


def test_dqx_rule_serializes_verbatim():
    cfg = LayerConfig.model_validate(
        _layer(
            datasets=[
                _dataset(
                    quality={
                        "checks": [
                            {
                                "name": "valid_id",
                                "criticality": "error",
                                "filter": "x > 0",
                                "check": {"function": "is_not_null", "arguments": {"column": "id"}},
                            }
                        ]
                    }
                )
            ]
        )
    )
    assert cfg.datasets[0].quality.checks[0].to_dqx() == {
        "name": "valid_id",
        "criticality": "error",
        "filter": "x > 0",
        "check": {"function": "is_not_null", "arguments": {"column": "id"}},
    }
