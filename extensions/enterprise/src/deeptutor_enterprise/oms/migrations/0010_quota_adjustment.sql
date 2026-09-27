-- 保留授予的历史总承诺；负向调整只释放未用承诺，不覆盖已结算/在途事实。
ALTER TABLE oms.quota_grants
  ADD COLUMN adjustment_released numeric(30,6) NOT NULL DEFAULT 0;
ALTER TABLE oms.quota_grants
  ADD CONSTRAINT quota_grants_adjustment_released_valid
  CHECK (adjustment_released >= 0 AND adjustment_released < quantity);
