# Databricks notebook source
# MAGIC %run /Workspace/Users/nivethan.venkatachalam@diggibyte.com/DQX_Demo/DQX_Wrapper

# COMMAND ----------

dbutils.widgets.text("bronze_table", "", "bronze_table")
dbutils.widgets.text("silver_table", "", "silver_table")
dbutils.widgets.text("silver_table_quarantine", "", "silver_table_quarantine")
dbutils.widgets.text("dq_table", "", "dq_table")

bronze_table            = dbutils.widgets.get("bronze_table")
silver_table            = dbutils.widgets.get("silver_table")
silver_table_quarantine = dbutils.widgets.get("silver_table_quarantine")
dq_table                = dbutils.widgets.get("dq_table")

# COMMAND ----------

silver_table_valid_quarantine = silver_table + "_valid" + "_quarantine"
print(silver_table_valid_quarantine)

# COMMAND ----------

profile     = get_dqx_checks_config(dq_table, bronze_table)[0]
dq_rule     = get_dqx_checks_config(dq_table, bronze_table)[1]

# COMMAND ----------

df        = spark.read.table(bronze_table)
dq_engine = DQEngine(WorkspaceClient())

# Option 1: apply quality rules on the dataframe and provide valid and invalid (quarantined) dataframes 
valid_df, quarantined_df = dq_engine.apply_checks_by_metadata_and_split(df, json.loads(dq_rule))

# Option 2: apply quality rules on the dataframe and report issues as additional columns (`_warning` and `_error`)
valid_and_quarantined_df = dq_engine.apply_checks_by_metadata(df, json.loads(dq_rule))
# print("valid_and_quarantined_df")
display(valid_and_quarantined_df)

# COMMAND ----------

valid_df.write.format("delta").mode("overwrite").option("overWriteSchema", True).saveAsTable(silver_table)

# COMMAND ----------

quarantined_df.write.format("delta").mode("overwrite").option("overWriteSchema", True).saveAsTable(silver_table_quarantine)

# COMMAND ----------

valid_and_quarantined_df.write.format("delta").mode("overwrite").option("overWriteSchema", True).saveAsTable(silver_table_valid_quarantine)