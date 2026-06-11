"""Custom dqx check functions for the customer_sales domain.

Declared to the framework through the layer YAML's ``imports:`` list
(``imports: [customer_sales_etl.checks]``). A check function returns a dqx condition
Column via ``make_condition``; YAML references it by function name exactly
like a built-in dqx check:

    - name: email_has_corporate_domain
      criticality: warn
      check:
        function: ends_with_suffix
        arguments: {column: email, suffix: "@example.com"}
"""

from pyspark.sql import Column
from pyspark.sql import functions as F

from datalab.framework.registry import check_function


@check_function
def ends_with_suffix(column: str, suffix: str) -> Column:
    """Documented example of a custom row-level check."""
    from databricks.labs.dqx.check_funcs import make_condition

    col = F.col(column)
    return make_condition(
        ~col.endswith(suffix),
        F.concat_ws("", F.lit(f"column {column} does not end with {suffix}: "), col),
        f"{column}_ends_with_{suffix.strip('@').replace('.', '_')}",
    )
