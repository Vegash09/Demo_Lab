from pyspark.sql.functions import upper, col

def uppercase_column(df, column):
    """
    Custom transformation that converts a specified column to uppercase.
    """
    return df.withColumn(column, upper(col(column)))
