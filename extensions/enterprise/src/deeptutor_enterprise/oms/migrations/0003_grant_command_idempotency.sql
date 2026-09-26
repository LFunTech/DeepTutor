-- 平台授予命令以操作者/动作/键去重；结果与账务写入同一事务提交。
-- 只保存 payload 指纹及目标对象，不保存原始凭据、Secret 或请求正文。
CREATE TABLE oms.grant_commands (
  actor_subject text NOT NULL,
  action text NOT NULL,
  idempotency_key text NOT NULL,
  target_tenant_id uuid NOT NULL REFERENCES enterprise.tenants(id),
  payload_hash text NOT NULL,
  grant_id uuid NOT NULL,
  result text NOT NULL DEFAULT 'pending',
  created_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  PRIMARY KEY (actor_subject,action,idempotency_key),
  CHECK (length(actor_subject) > 0 AND length(action) > 0 AND length(idempotency_key) > 0),
  CHECK (length(payload_hash) = 64),
  CHECK (result IN ('pending','success','denied'))
);
