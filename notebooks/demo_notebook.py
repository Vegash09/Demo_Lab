# %% Importing the required libraries
from databricks.connect import DatabricksSession

# COMMAND ----------
# Creating a Databricks session
spark = DatabricksSession.builder.profile("dev_diggi").getOrCreate()

# %% Checking the Spark session
df = spark.table("customer_sales._silver.customer")
df.show(5)
# COMMAND ----------
