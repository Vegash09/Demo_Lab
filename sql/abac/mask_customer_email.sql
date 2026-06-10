-- ABAC worked example: mask silver.customers.email for everyone except
-- data stewards. Conventions (see docs/ARCHITECTURE.md "Access governance"):
--
--   * DISPLAY-ONLY: agents and CI never execute these — an admin reviews and
--     applies them manually (SQL editor / `make bootstrap-uc`-style session).
--   * Re-runnable: CREATE OR REPLACE FUNCTION before ALTER TABLE.
--   * Allowed constructs only: CREATE FUNCTION ... RETURN,
--     ALTER TABLE ... SET MASK / SET ROW FILTER,
--     is_account_group_member(), current_user().
--   * Names: dl_mask_<purpose> for column masks, dl_rf_<purpose> for row
--     filters, created in the schema of the table they protect.
--
-- Replace <catalog> with the target catalog (customer_sales / _stage / _prod).

CREATE OR REPLACE FUNCTION `<catalog>`.`silver`.dl_mask_email(email STRING)
RETURN CASE
  WHEN is_account_group_member('dl_data_stewards') THEN email
  ELSE regexp_replace(email, '^[^@]+', '***')
END;

ALTER TABLE `<catalog>`.`silver`.`customers`
  ALTER COLUMN email SET MASK `<catalog>`.`silver`.dl_mask_email;
