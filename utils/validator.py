def validate_schema(df, expected_schema):
    actual_columns = set(df.columns)
    expected_columns = set(expected_schema)
    return expected_columns.issubset(actual_columns)