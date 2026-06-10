"""Framework exceptions — user-facing, always actionable."""


class ConfigError(Exception):
    """A layer YAML file failed validation. The message lists every problem
    with its dotted config path and the file it came from."""


class FrameworkRuntimeError(Exception):
    """A dataset needs a Databricks-only LDP capability not available in the
    current (local/OSS) runtime. The message names the missing symbol and the
    supported alternative (usually ``devtools.run_dataset``)."""
