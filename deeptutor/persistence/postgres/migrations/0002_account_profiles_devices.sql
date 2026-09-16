-- 默认账号附属面；身份与会话沿用唯一 users/auth_sessions，不接管其它资源域。
ALTER TABLE enterprise.users
  ADD COLUMN deleted_at timestamptz,
  ADD COLUMN avatar text NOT NULL DEFAULT '',
  ADD COLUMN avatar_object text NOT NULL DEFAULT '',
  ADD COLUMN preset text NOT NULL DEFAULT 'standard' CHECK (preset IN ('standard','learner','custom')),
  ADD COLUMN learner_profile jsonb,
  ADD COLUMN learning_policy jsonb;
CREATE TABLE enterprise.device_credentials (
  tenant_id uuid NOT NULL, user_id text NOT NULL, id text NOT NULL,
  device_name text NOT NULL, pairing_code_hash text NOT NULL, pin_hash text NOT NULL,
  auth_version bigint NOT NULL, auth_epoch text NOT NULL, generation bigint NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL,
  daily_limit_minutes integer NOT NULL CHECK (daily_limit_minutes BETWEEN 5 AND 1440),
  last_login_at timestamptz, last_heartbeat_at timestamptz, usage_day date,
  used_seconds integer NOT NULL DEFAULT 0 CHECK (used_seconds >= 0),
  failed_pin_attempts integer NOT NULL DEFAULT 0 CHECK (failed_pin_attempts >= 0),
  pin_locked_until timestamptz, revoked_at timestamptz, revoked_by text NOT NULL DEFAULT '',
  PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,user_id,id), UNIQUE (tenant_id,pairing_code_hash),
  FOREIGN KEY (tenant_id,user_id) REFERENCES enterprise.users(tenant_id,id)
);
ALTER TABLE enterprise.auth_sessions
  ADD COLUMN device_credential_id text,
  ADD COLUMN device_generation bigint,
  ADD FOREIGN KEY (tenant_id,user_id,device_credential_id)
    REFERENCES enterprise.device_credentials(tenant_id,user_id,id),
  ADD CHECK ((device_credential_id IS NULL AND device_generation IS NULL)
    OR (device_credential_id IS NOT NULL AND device_generation IS NOT NULL));
ALTER TABLE enterprise.device_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE enterprise.device_credentials FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON enterprise.device_credentials
  USING (tenant_id = nullif(current_setting('app.tenant_id',true),'')::uuid)
  WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id',true),'')::uuid);
GRANT SELECT,INSERT,UPDATE,DELETE ON enterprise.device_credentials TO dt_enterprise_app;
