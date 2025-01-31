from pyspark.sql.functions import col

def filter_rows(df, column, value):
    return df.filter(col(column) == value)

def rename_columns(df, mappings):
    for old_col, new_col in mappings.items():
        df = df.withColumnRenamed(old_col, new_col)
    return df
