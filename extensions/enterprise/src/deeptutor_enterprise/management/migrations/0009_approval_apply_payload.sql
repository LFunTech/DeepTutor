-- 审批通过后的受控 apply 需要不可变目标载荷；不使用数据库枚举、CHECK、
-- trigger 或存储过程表达业务规则，全部值域与组合关系由应用层校验。
ALTER TABLE management.approval_requests
  ADD COLUMN IF NOT EXISTS target_role_key text,
  ADD COLUMN IF NOT EXISTS target_role_version bigint,
  ADD COLUMN IF NOT EXISTS target_action_keys text[] NOT NULL DEFAULT ARRAY[]::text[],
  ADD COLUMN IF NOT EXISTS target_expires_at timestamptz,
  ADD COLUMN IF NOT EXISTS confirmed_role_version bigint;
