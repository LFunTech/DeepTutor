-- 服务授权命令独立于额度授予命令，按真实目标学校 RLS 限定。
CREATE TABLE oms.entitlement_commands (
  actor_subject text NOT NULL,
  action text NOT NULL,
  idempotency_key text NOT NULL,
  target_tenant_id uuid NOT NULL REFERENCES enterprise.tenants(id),
  service_id text NOT NULL REFERENCES oms.service_definitions(service_id),
  payload_hash text NOT NULL,
  result_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  PRIMARY KEY (actor_subject,action,idempotency_key),
  CHECK (length(actor_subject) > 0 AND length(action) > 0 AND length(idempotency_key) > 0),
  CHECK (length(payload_hash) = 64),
  CHECK (jsonb_typeof(result_summary) = 'object')
);
CREATE INDEX entitlement_commands_target_time
  ON oms.entitlement_commands(target_tenant_id,created_at DESC);
ALTER TABLE oms.entitlement_commands ENABLE ROW LEVEL SECURITY;
ALTER TABLE oms.entitlement_commands FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON oms.entitlement_commands
  USING (target_tenant_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid)
  WITH CHECK (target_tenant_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid);
