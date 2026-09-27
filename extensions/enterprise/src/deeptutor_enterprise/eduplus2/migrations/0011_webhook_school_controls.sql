-- 独立于外部生命周期投影的本地人工冻结；后续 Webhook 不得覆盖。
CREATE TABLE eduplus2.webhook_school_controls (
  tenant_id uuid NOT NULL REFERENCES enterprise.tenants(id),
  school_id uuid NOT NULL REFERENCES enterprise.tenants(id),
  external_app_id bigint NOT NULL CHECK (external_app_id > 0),
  frozen boolean NOT NULL DEFAULT false,
  version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
  reason text NOT NULL DEFAULT '',
  updated_by text NOT NULL DEFAULT '@signed-webhook',
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (tenant_id,school_id,external_app_id),
  CHECK (length(reason) <= 1000 AND length(updated_by) BETWEEN 1 AND 255)
);
-- 仅为已有已完成 PG onboarding 的签名投影建立默认未冻结控制行；不推断旧 proof。
INSERT INTO eduplus2.webhook_school_controls(tenant_id,school_id,external_app_id)
  SELECT tenant_id,school_id,external_app_id
  FROM eduplus2.webhook_school_state
  WHERE onboarding_event_id IS NOT NULL AND onboarding_completed_at IS NOT NULL;
ALTER TABLE eduplus2.webhook_school_controls ENABLE ROW LEVEL SECURITY;
ALTER TABLE eduplus2.webhook_school_controls FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON eduplus2.webhook_school_controls
  USING (tenant_id = nullif(current_setting('app.tenant_id',true),'')::uuid)
  WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id',true),'')::uuid);
CREATE POLICY school_control_read ON eduplus2.webhook_school_controls
  FOR SELECT
  USING (school_id = nullif(current_setting('app.tenant_id',true),'')::uuid);

CREATE TABLE eduplus2.webhook_school_control_commands (
  tenant_id uuid NOT NULL REFERENCES enterprise.tenants(id),
  command_id uuid NOT NULL,
  school_id uuid NOT NULL REFERENCES enterprise.tenants(id),
  external_app_id bigint NOT NULL CHECK (external_app_id > 0),
  actor_issuer text NOT NULL,
  actor_subject text NOT NULL,
  frozen boolean NOT NULL,
  expected_version bigint NOT NULL CHECK (expected_version > 0),
  result_version bigint NOT NULL CHECK (result_version > 0),
  reason text NOT NULL,
  request_id text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (tenant_id,command_id),
  CHECK (length(actor_issuer) BETWEEN 1 AND 255 AND
         length(actor_subject) BETWEEN 1 AND 255 AND
         length(reason) BETWEEN 1 AND 1000 AND
         length(request_id) BETWEEN 1 AND 128)
);
ALTER TABLE eduplus2.webhook_school_control_commands ENABLE ROW LEVEL SECURITY;
ALTER TABLE eduplus2.webhook_school_control_commands FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON eduplus2.webhook_school_control_commands
  USING (tenant_id = nullif(current_setting('app.tenant_id',true),'')::uuid)
  WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id',true),'')::uuid);
