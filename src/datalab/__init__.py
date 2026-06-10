"""datalab — shared, unit-testable building blocks for the SDP medallion pipelines.

Everything in this package is plain PySpark: pure DataFrame-in/DataFrame-out
functions plus small helpers. No `pyspark.pipelines` imports, no I/O, no side
effects — that is what makes it testable with a local SparkSession.

Pipeline source files under ``src/<pipeline>/transformations/`` import from
here and wire the functions into `@dp.table` / `@dp.materialized_view`
definitions.
"""

__version__ = "0.2.0"
