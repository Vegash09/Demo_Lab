from pyspark.sql import SparkSession
from utils.config_reader import load_config
from transformations.basic_transformations import filter_rows, rename_columns

def apply_transformations(df, transformations):
    for transformation in transformations:
        if transformation["type"] == "filter":
            df = filter_rows(df, transformation["column"], transformation["value"])
        elif transformation["type"] == "rename":
            df = rename_columns(df, transformation["mappings"])
    return df

if __name__ == "__main__":
    spark = SparkSession.builder.appName("PySparkTransformationFramework").getOrCreate()
    
    config = load_config("config/config.json")
    
    df = spark.read.csv(config["input_path"], header=True, inferSchema=True)
    
    transformed_df = apply_transformations(df, config["transformations"])
    
    transformed_df.write.parquet(config["output_path"], mode="overwrite")
    
    print("Data transformation completed.")
