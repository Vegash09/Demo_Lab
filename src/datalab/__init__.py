"""datalab — the reusable, config-driven lakehouse framework.

The only package under ``src/``; zero domain code, lifts into any project
untouched. ``datalab.framework`` turns per-table YAML artifacts into Lakeflow
SDP datasets (see ``docs/FRAMEWORK.md``); ``datalab.config`` /
``datalab.params`` carry the parameterization contracts for the pipeline and
job lanes. Domain business logic lives in domain packages
(``src/<domain>_etl/`` in adopter repos, ``examples/<domain>/src/`` here),
declared to the framework via each ``domain.yml``'s ``imports:`` list — and
everything is unit-testable with a local SparkSession.
"""

__version__ = "0.3.0"
