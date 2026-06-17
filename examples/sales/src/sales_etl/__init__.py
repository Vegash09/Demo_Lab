"""sales_etl — the sales domain's adoption of the datalab framework.

Domain-owned code only: transforms/ (pure functions), checks/ (custom dqx
checks) and transformations/pipeline.py (the LDP entrypoint). The reusable
framework lives in ``datalab`` and is never edited from here. The five bronze
source tables (``sales.bronze.*``) are ingested upstream; this domain builds
the silver and gold layers from them.
"""
