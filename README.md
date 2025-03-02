# PySpark Transformation Framework

## Overview
The **PySpark Transformation Framework** is a scalable and configurable data processing solution designed for **Apache Spark** in **Databricks** or any distributed Spark environment. It allows organizations to define data transformations dynamically using **YAML** or **JSON** configurations, reducing the need for manual Spark programming.

### Key Features
✔ **Config-Driven Architecture** – No need to modify code for different transformations.  
✔ **Built-in & Custom Transformations** – Supports filters, renaming, and user-defined transformations.  
✔ **Seamless Databricks Integration** – Runs as a scheduled job or interactive notebook.  
✔ **Scalable & Distributed** – Utilizes Apache Spark for high-performance data processing.  
✔ **Automated Workflow Deployment** – YAML-based configuration for defining **Databricks Job settings**.  

---

## 1️⃣ Installation
To install the framework on your **Databricks cluster** or local Spark environment:

```sh
pip install pyspark
pip install pyyaml
```
or install from the package:
```sh
pip install dist/pyspark_transformation_framework-1.0.0-py3-none-any.whl
```

---

## 2️⃣ Usage
### Running a Transformation Job
Once installed, execute the transformation job using:

```sh
run-transformations config/config.yaml
```

or manually using:

```sh
python main.py config/config.yaml
```

The framework reads the transformation rules from the **config.yaml** file and applies them to the dataset.

---

## 3️⃣ Configuration File (`config.yaml`)
All transformations and job settings are defined in a **YAML configuration file**.

### Example `config/config.yaml`
```yaml
job_name: "pyspark_transformation_job"
input_path: "dbfs:/mnt/raw_data/input.csv"
output_path: "dbfs:/mnt/processed_data/output.parquet"
cluster:
  name: "MyCluster"
  spark_version: "10.4.x-scala2.12"
  node_type: "Standard_DS3_v2"
  num_workers: 2
transformations:
  - type: "filter"
    column: "status"
    value: "active"

  - type: "rename"
    mappings:
      old_name: "new_name"

  - type: "custom"
    module: "custom_transformations"
    function: "apply_transformation"
    params:
      transformation_type: "uppercase"
      column: "name"
```

---

## 4️⃣ Deploying a Databricks Workflow Job
To automate execution, define a **Databricks Job JSON/YAML configuration** and upload it to **Databricks Workflows**.

### Example Job JSON
```json
{
  "name": "PySpark Transformation Job",
  "new_cluster": {
    "spark_version": "10.4.x-scala2.12",
    "node_type_id": "Standard_DS3_v2",
    "num_workers": 2
  },
  "notebook_task": {
    "notebook_path": "/Workspace/Jobs/pyspark_transformation_notebook"
  },
  "libraries": [
    { "pypi": { "package": "pyspark" } },
    { "pypi": { "package": "pyyaml" } }
  ],
  "email_notifications": {
    "on_failure": ["alerts@example.com"]
  },
  "schedule": {
    "quartz_cron_expression": "0 0 12 * * ?",
    "timezone_id": "UTC"
  }
}
```

---

## 5️⃣ Future Enhancements
- Integration with **Delta Lake** for advanced data processing.
- More built-in transformations (aggregations, joins).
- **CI/CD Pipeline Support** for automated deployments.

---

## ✅ Conclusion
This **PySpark Transformation Framework** simplifies data processing workflows in **Databricks**, ensuring efficiency, scalability, and flexibility.
