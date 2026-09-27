-- 过期与人工撤销是不同事实；旧 grant 不自动改写或推断结算结果。
ALTER TABLE oms.quota_grants
  DROP CONSTRAINT IF EXISTS quota_grants_status_check;
ALTER TABLE oms.quota_grants
  ADD CONSTRAINT quota_grants_status_check
  CHECK (status IN ('active','revoked','expired'));
