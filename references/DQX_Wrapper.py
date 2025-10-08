# Databricks notebook source
pip install databricks-labs-dqx

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

from databricks.labs.dqx.profiler.dlt_generator import DQDltGenerator
from databricks.labs.dqx.profiler.generator import DQGenerator
from databricks.labs.dqx.profiler.profiler import DQProfiler
from concurrent.futures import ThreadPoolExecutor
from databricks.labs.dqx.engine import DQEngine
from pyspark.sql.utils import AnalysisException
from databricks.sdk import WorkspaceClient
from delta.tables import DeltaTable
from pyspark.sql.functions import *
from pyspark.sql.types import *
import concurrent.futures
import json

# COMMAND ----------

# DBTITLE 1,1. generate_dqx_rules_config : Generate and Validate data quality checks rules for given table.
from decimal import Decimal
from datetime import date

def default_serializer(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

def generate_dqx_rules_config(table_name, sample_size):
    """
    Generates and validates data quality checks rules for a given table.

    Args:
        table_name (str): The name of the table to generate checks for.
        sample_size (int): The number of rows to sample from the table for generating checks.

    Returns:
        dict: A dictionary containing the table name, generated checks, and validation status.
    """
    try:
        df = spark.read.table(table_name).limit(sample_size)
        ws = WorkspaceClient()
        profiler = DQProfiler(ws)
        summary_stats, profiles = profiler.profile(df)
        generator = DQGenerator(ws)
        checks = generator.generate_dq_rules(profiles)
        status = DQEngine.validate_checks(checks)
        generated_checks_statement_validated = ""
        if not status.has_errors:
            print("No Error Found in Generated Rules Config")
            generated_checks_statement_validated = status.to_string()
        else:
            generated_checks_statement_validated = status.to_string()
            
    except Exception as e:
        return_config = {"table_name": table_name, "data_profile": "", "data_quality_rule": "", "validate_check": f"Error generating DQX checks for table {table_name}: {e}"}
        return return_config
    
    return_config = {"table_name": table_name, "data_profile": summary_stats, "data_quality_rule": checks, "validate_check": generated_checks_statement_validated}

    return return_config

# COMMAND ----------

# DBTITLE 1,2. generate_dqx_rules: helper function for generates DQX checks for a given table in parallel.
def generate_dqx_rules(table, sample_size):
    """
    Generates DQX checks for a given table.

    Args:
        table (str): The name of the table for which to generate DQX checks.
        sample_size (int): The sample size to use for generating the DQX checks.

    Returns:
        str: A JSON string containing the generated DQX checks and validation status.
    """
    generated_check_statement = generate_dqx_rules_config(table, sample_size)
    output = json.dumps(generated_check_statement, default=default_serializer)
    return output

# COMMAND ----------

# DBTITLE 1,3. generate_dqx_rules_parallel: This function will help you to generate data quality rules in bulk for given database.
def generate_dqx_rules_parallel(catalog_name, schema_name, sample_size):
    """
    Generates DQX rules in parallel for all tables in the specified database.

    Args:
        schema_name (str): The name of the database containing the tables.
        sample_size (int): The sample size to be used for generating DQX rules.

    Returns:
        DataFrame: A Spark DataFrame containing the table name, generated checks statement, 
                   and validation status for each table in the database.
    """
    list_tables = spark.table("`system`.information_schema.tables").filter(f"table_catalog = '{catalog_name}' and table_schema = '{schema_name}'").collect()
    table_list = [f"{catalog_name}.{schema_name}.{table['table_name']}" for table in list_tables]

    schema = StructType([
               StructField('table_name', StringType(), True),
               StructField('generated_data_profile', StringType(), True),
               StructField('generated_data_quality_rule', StringType(), True),
               StructField('generated_checks_statement_validated', StringType(), True)
             ])
    
    # Create an empty DataFrame with the defined schema
    final_df = spark.createDataFrame([], schema)

    with ThreadPoolExecutor() as executor:
        sample_size_list = [sample_size] * len(table_list)
        #print(sample_size_list)
        results = list(executor.map(generate_dqx_rules, table_list, sample_size_list))
    
    for output in results:
        updated_output = json.loads(output)  # Parse the string into a dictionary
        table_name = updated_output.get('table_name')
        data_profile = str(updated_output.get('data_profile')).replace("'", '"')
        checks = str(updated_output.get('data_quality_rule')).replace("'", '"')
        generated_checks_statement_validated = updated_output.get('validate_check')

        df = spark.createDataFrame([(table_name, data_profile, checks, generated_checks_statement_validated)], schema=schema)
        final_df = final_df.union(df)
    
    return final_df

# COMMAND ----------

# DBTITLE 1,get_dqx_checks_config: Retrieves the DQX checks configuration for a specified table.
def get_dqx_checks_config(dq_table, table_name):
    """
    Retrieves the DQX checks configuration for a specified table.

    This function queries the Delta table containing DQX quality check configurations
    and retrieves the generated checks statement for the specified table, provided that
    no errors were found during validation.

    Args:
        table_name (str): The name of the table for which to retrieve the DQX checks configuration.

    Returns:
        str: The generated checks statement for the specified table if no errors are found.
    """
    config_table = spark.table(dq_table)
    table_profile = config_table.filter(f"table_name = '{table_name}' and generated_checks_statement_validated = 'No errors found'").collect()[0]["generated_data_profile"]
    table_checks = config_table.filter(f"table_name = '{table_name}' and generated_checks_statement_validated = 'No errors found'").collect()[0]["generated_data_quality_rule"]
    return table_profile, table_checks

# COMMAND ----------

def update_delta_table_of_dq_rules(dq_table, config_df):
    """
    Updates a Delta table with new configurations from a DataFrame.

    This function checks if a Delta table exists. If it does, it merges the new configurations
    from the provided DataFrame into the existing Delta table. If the table does not exist, it
    creates a new Delta table with the provided configurations.

    Args:
        config_df (DataFrame): A Spark DataFrame containing the new configurations to be merged
                               into the Delta table.

    Returns:
        None
    """

    # If the table does not exist or is not a Delta table, create it as a Delta table
    return config_df.write.format("delta").mode("overwrite").option("overWriteSchema", True).saveAsTable(dq_table)

# COMMAND ----------

from delta.tables import DeltaTable
from pyspark.sql.utils import AnalysisException
from pyspark.sql.functions import lit
import json

def update_dq_checks(dq_table, table_name, new_checks_json, config_df=None):
    """
    Updates dq_rule for the given table_name if exists; 
    Creates the dq_table only if it does not already exist.
    Does NOT insert new rows if table exists.

    Args:
        dq_table (str): Name of Delta table containing DQ rules.
        table_name (str): Table name whose dq_rule needs update.
        new_checks_json (dict/list or str): New DQ checks.
        config_df (DataFrame, optional): Initial DataFrame if table doesn't exist.

    Returns:
        None
    """
    # Serialize new_checks_json if necessary
    if isinstance(new_checks_json, (dict, list)):
        new_checks_json = json.dumps(new_checks_json)

    updates_df = spark.createDataFrame([
        {"table_name": table_name, "generated_data_quality_rule": new_checks_json}
    ])

    try:
        # Check if table exists
        delta_table = DeltaTable.forName(spark, dq_table)

        # Perform MERGE to only UPDATE existing records
        (delta_table.alias("target")
            .merge(
                updates_df.alias("source"),
                "target.table_name = source.table_name"
            )
            .whenMatchedUpdate(set={"generated_data_quality_rule": "source.generated_data_quality_rule"})
            .execute())

        print(f"Successfully updated dq_rule for table '{table_name}'.")

    except AnalysisException as e:
        if "not found" in str(e):
            if config_df is not None:
                # Create Delta table initially
                config_df.write.format("delta").mode("overwrite").option("overWriteSchema", True).saveAsTable(dq_table)
                print(f"Delta table '{dq_table}' created successfully.")
            else:
                print(f"Table '{dq_table}' doesn't exist. Provide 'config_df' for initial creation.")
        else:
            raise e

    except Exception as ex:
        print(f"Unexpected error: {str(ex)}")