-- 撤销/调整命令的幂等结果必须固定，后续结算不能改变重放响应。
ALTER TABLE oms.grant_commands
  ADD COLUMN result_summary jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE oms.grant_commands
  ADD CONSTRAINT grant_commands_result_summary_object
  CHECK (jsonb_typeof(result_summary) = 'object');
