# CI/CD Testing Setup

This document explains how notebook tests are executed in the CI/CD pipeline.

## CI/CD Overview

Your GitHub Actions workflows automatically run tests when:
- **Pull Requests** are created or updated
- **Pushes** to `main` or `development/**` branches
- **Manual triggers** via workflow_dispatch

## Test Execution Flow

### 1. Pull Request Workflow

**File:** `.github/workflows/pr-verify-notebooks.yml`

```yaml
steps:
  - Run verification script
    → python scripts/verify_notebook_tests.py
```

**What it checks:**
- ✅ Every notebook has a corresponding test file
- ✅ Every test file contains at least one `def test_*()` function
- ✅ Every notebook has a JSON config file
- ✅ Every notebook is referenced in a pipeline YAML

### 2. Common CI Workflow

**File:** `.github/workflows/common-ci-steps.yml`

#### Job 1: PySpark Unit Tests

```yaml
steps:
  - Setup Python 3.12
  - Install: pip install -e ".[pyspark]" pytest
  - Run: pytest -m "not dbconnect_only" notebooks/tests/unit_testing -q
```

**Runs:**
- All unit tests in `notebooks/tests/unit_testing/`
- Excludes tests marked with `@pytest.mark.dbconnect_only`
- Uses local Spark (fast)

#### Job 2: Databricks Connect Integration Tests

```yaml
steps:
  - Setup Python 3.11
  - Install: pip install -e ".[dbconnect]" pytest
  - Setup Databricks credentials
  - Run: pytest -m dbconnect_only notebooks/tests/integration_testing -q
```

**Runs:**
- All integration tests in `notebooks/tests/integration_testing/`
- Only tests marked with `@pytest.mark.dbconnect_only`
- Uses real Databricks cluster

## Your Test Files

### Unit Tests
**File:** `notebooks/tests/unit_testing/bronze_silver/bu_sales/test_bronze_to_silver_unit.py`

**Runs in CI:** ✅ Yes (pyspark-tests job)
- Fast local Spark tests
- No Databricks credentials needed

### Integration Tests
**File:** `notebooks/tests/integration_testing/bronze_silver/bu_sales/test_bronze_to_silver_integration.py`

**Runs in CI:** ✅ Yes (dbconnect-tests job)
- Uses Databricks Connect
- Requires cluster and credentials (from GitHub secrets)

## CI/CD Test Commands

The CI/CD runs these exact commands:

```bash
# Unit tests (on every PR/push)
pytest -m "not dbconnect_only" notebooks/tests/unit_testing -q

# Integration tests (on every PR/push, after unit tests pass)
pytest -m dbconnect_only notebooks/tests/integration_testing -q

# Verification (on every PR)
python scripts/verify_notebook_tests.py
```

## Required GitHub Secrets

For integration tests to run, these secrets must be configured in GitHub:

- `AZURE_CLIENT_ID` - Service principal client ID
- `AZURE_TENANT_ID` - Azure tenant ID
- `DATABRICKS_HOST` - Databricks workspace URL
- `DATABRICKS_CLUSTER_ID` - Cluster ID for tests
- `DATABRICKS_TOKEN` - Authentication token (if using token auth)

## Test Naming Convention

To avoid pytest import conflicts between unit and integration tests, use unique names:

| Type | Naming Pattern | Example |
|------|----------------|---------|
| **Unit** | `test_<name>_unit.py` | `test_bronze_to_silver_unit.py` |
| **Integration** | `test_<name>_integration.py` | `test_bronze_to_silver_integration.py` |

## When Tests Run

| Event | Verification | Unit Tests | Integration Tests |
|-------|--------------|------------|-------------------|
| **Pull Request** | ✅ Yes | ✅ Yes | ✅ Yes |
| **Push to main** | ✅ Yes | ✅ Yes | ✅ Yes |
| **Push to development/** | ✅ Yes | ✅ Yes | ✅ Yes |
| **Manual Trigger** | ❌ No | Optional | Optional |

## Test Failure Behavior

### If Verification Fails
- ❌ PR check fails
- ❌ Cannot merge until fixed
- **Fix:** Add missing test files or config files

### If Unit Tests Fail
- ❌ PR check fails
- ❌ Integration tests don't run
- **Fix:** Fix the transformation logic

### If Integration Tests Fail
- ❌ PR check fails
- ✅ Unit tests still passed
- **Fix:** Check Databricks connectivity or data issues

## Local Testing Before CI

Always test locally before pushing:

```bash
# 1. Verify notebooks
python scripts/verify_notebook_tests.py

# 2. Run integration tests (if you have Databricks Connect)
export DATABRICKS_CONFIG_PROFILE="dev_diggi"
pytest notebooks/tests/integration_testing/ -v

# 3. Check all tests will pass
pytest notebooks/tests/ -v
```

## CI/CD Workflow Files

1. **`.github/workflows/common-ci-steps.yml`** - Main test execution
2. **`.github/workflows/pr-verify-notebooks.yml`** - Notebook verification
3. **`.github/workflows/ci-cd-dev.yml`** - Dev environment workflow
4. **`.github/workflows/ci-cd-stage.yml`** - Staging environment workflow
5. **`.github/workflows/ci-cd-prod.yml`** - Production environment workflow

## Skipping Tests in CI

Tests are automatically skipped when appropriate:

- **Unit tests** skip if marked `@pytest.mark.dbconnect_only`
- **Integration tests** skip if:
  - Databricks Connect not available
  - Bronze table doesn't exist
  - Table is empty

This is intentional and allows tests to be resilient.

## Summary

✅ **Your tests WILL run in CI/CD automatically**

- Every PR triggers verification + unit tests + integration tests
- Tests are run in parallel jobs for speed
- Integration tests use real Databricks cluster
- Failures block PR merges
- Test files use `_unit.py` and `_integration.py` suffixes to avoid conflicts

**No additional setup needed!** Your tests are ready for CI/CD. 🎉

