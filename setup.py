from setuptools import setup, find_packages

setup(
    name="pyspark_transformation_framework",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "pyspark",
        "pyyaml"
    ],
    entry_points={
        "console_scripts": [
            "run-transformations = main:main"
        ]
    },
    description="A framework for data transformations using PySpark",
    author="Your Name",
    license="MIT"
)
