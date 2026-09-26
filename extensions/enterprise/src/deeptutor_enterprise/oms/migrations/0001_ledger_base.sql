-- OMS 业务总账基础结构。既有 core/eduplus2 表不可改写或自动推断历史用量。
-- 所有数量均为服务 descriptor 指定的原生单位，禁止跨单位算术。

CREATE TABLE oms.service_definitions (
  service_id text PRIMARY KEY,
  unit_code text NOT NULL,
  resource_category text NOT NULL,
  enabled boolean NOT NULL DEFAULT false,
  version bigint NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (length(service_id) > 0),
  CHECK (length(unit_code) > 0),
  CHECK (resource_category IN ('model_external','agent_capability','tool_integration','knowledge_content','runtime')),
  CHECK (version >= 1)
);

CREATE TABLE oms.supply_lots (
  id uuid PRIMARY KEY,
  service_id text NOT NULL REFERENCES oms.service_definitions(service_id),
  provider_id text NOT NULL,
  provider_account_id text NOT NULL DEFAULT '',
  pool_id text NOT NULL,
  unit_code text NOT NULL,
  evidence_ref text NOT NULL,
  hard_ceiling numeric(30,6),
  settled_lifetime numeric(30,6) NOT NULL DEFAULT 0,
  committed_unspent numeric(30,6) NOT NULL DEFAULT 0,
  reserved_inflight numeric(30,6) NOT NULL DEFAULT 0,
  starts_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  status text NOT NULL DEFAULT 'active',
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (length(provider_id) > 0 AND length(pool_id) > 0 AND length(unit_code) > 0),
  CHECK (length(evidence_ref) > 0),
  CHECK (hard_ceiling IS NULL OR hard_ceiling > 0),
  CHECK (settled_lifetime >= 0 AND committed_unspent >= 0 AND reserved_inflight >= 0),
  CHECK (hard_ceiling IS NULL OR settled_lifetime + committed_unspent + reserved_inflight <= hard_ceiling),
  CHECK (expires_at > starts_at),
  CHECK (status IN ('active','revoked'))
);
CREATE INDEX supply_lots_available
  ON oms.supply_lots(service_id,pool_id,unit_code,expires_at,id)
  WHERE status='active' AND hard_ceiling IS NOT NULL;

CREATE TABLE oms.tenant_service_entitlements (
  tenant_id uuid NOT NULL REFERENCES enterprise.tenants(id),
  service_id text NOT NULL REFERENCES oms.service_definitions(service_id),
  status text NOT NULL DEFAULT 'active',
  starts_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  version bigint NOT NULL DEFAULT 1,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id,service_id),
  CHECK (status IN ('active','revoked')),
  CHECK (expires_at > starts_at AND version >= 1),
  CHECK (length(created_by) > 0)
);

CREATE TABLE oms.quota_grants (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES enterprise.tenants(id),
  service_id text NOT NULL REFERENCES oms.service_definitions(service_id),
  unit_code text NOT NULL,
  acquisition_method text NOT NULL,
  quantity numeric(30,6) NOT NULL,
  starts_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  status text NOT NULL DEFAULT 'active',
  version bigint NOT NULL DEFAULT 1,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id,id),
  CHECK (unit_code <> '' AND quantity > 0),
  CHECK (acquisition_method IN ('gift','recharge')),
  CHECK (status IN ('active','revoked')),
  CHECK (expires_at > starts_at AND version >= 1),
  CHECK (length(created_by) > 0),
  FOREIGN KEY (tenant_id,service_id)
    REFERENCES oms.tenant_service_entitlements(tenant_id,service_id)
);
CREATE INDEX quota_grants_pick
  ON oms.quota_grants(tenant_id,service_id,acquisition_method,expires_at,created_at,id)
  WHERE status='active';

CREATE TABLE oms.grant_commitments (
  tenant_id uuid NOT NULL,
  grant_id uuid NOT NULL,
  lot_id uuid NOT NULL REFERENCES oms.supply_lots(id),
  committed_total numeric(30,6) NOT NULL,
  unspent numeric(30,6) NOT NULL,
  reserved numeric(30,6) NOT NULL DEFAULT 0,
  settled numeric(30,6) NOT NULL DEFAULT 0,
  released numeric(30,6) NOT NULL DEFAULT 0,
  PRIMARY KEY (tenant_id,grant_id,lot_id),
  FOREIGN KEY (tenant_id,grant_id) REFERENCES oms.quota_grants(tenant_id,id),
  CHECK (committed_total > 0),
  CHECK (unspent >= 0 AND reserved >= 0 AND settled >= 0 AND released >= 0),
  CHECK (unspent + reserved + settled + released = committed_total)
);

CREATE TABLE oms.usage_attempts (
  tenant_id uuid NOT NULL REFERENCES enterprise.tenants(id),
  attempt_id uuid NOT NULL,
  operation_id uuid NOT NULL,
  service_id text NOT NULL REFERENCES oms.service_definitions(service_id),
  unit_code text NOT NULL,
  provider_id text NOT NULL,
  provider_account_id text NOT NULL DEFAULT '',
  model_id text NOT NULL DEFAULT '',
  config_version bigint NOT NULL,
  subject_kind text NOT NULL,
  subject_id text NOT NULL,
  user_id text NOT NULL DEFAULT '',
  app_id text NOT NULL DEFAULT '',
  provider_request_id text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'reserved',
  reserved_units numeric(30,6) NOT NULL,
  settled_units numeric(30,6) NOT NULL DEFAULT 0,
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  started_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id,attempt_id),
  CHECK (length(unit_code) > 0 AND length(provider_id) > 0),
  CHECK (length(subject_id) > 0),
  CHECK (subject_kind IN ('user','delegated_user','app','service')),
  CHECK (status IN ('reserved','remote_unknown','reconcile_required','settled','released')),
  CHECK (config_version >= 1 AND reserved_units > 0),
  CHECK (settled_units >= 0 AND settled_units <= reserved_units),
  CHECK (jsonb_typeof(evidence) = 'object')
);
CREATE INDEX usage_attempts_operation
  ON oms.usage_attempts(tenant_id,operation_id,started_at,attempt_id);
CREATE INDEX usage_attempts_reconcile
  ON oms.usage_attempts(status,updated_at,tenant_id,attempt_id)
  WHERE status IN ('remote_unknown','reconcile_required');
CREATE UNIQUE INDEX usage_attempts_provider_receipt
  ON oms.usage_attempts(provider_id,provider_account_id,provider_request_id)
  WHERE provider_request_id <> '';

CREATE TABLE oms.attempt_allocations (
  tenant_id uuid NOT NULL,
  attempt_id uuid NOT NULL,
  grant_id uuid NOT NULL,
  lot_id uuid NOT NULL,
  allocated_units numeric(30,6) NOT NULL,
  reserved_units numeric(30,6) NOT NULL,
  settled_units numeric(30,6) NOT NULL DEFAULT 0,
  released_units numeric(30,6) NOT NULL DEFAULT 0,
  PRIMARY KEY (tenant_id,attempt_id,grant_id,lot_id),
  FOREIGN KEY (tenant_id,attempt_id) REFERENCES oms.usage_attempts(tenant_id,attempt_id),
  FOREIGN KEY (tenant_id,grant_id,lot_id) REFERENCES oms.grant_commitments(tenant_id,grant_id,lot_id),
  CHECK (allocated_units > 0),
  CHECK (reserved_units >= 0 AND settled_units >= 0 AND released_units >= 0),
  CHECK (reserved_units + settled_units + released_units = allocated_units)
);

CREATE TABLE oms.audit_events (
  id uuid PRIMARY KEY,
  actor_subject text NOT NULL,
  action text NOT NULL,
  target_tenant_id uuid,
  object_kind text NOT NULL,
  object_id text NOT NULL,
  request_id text NOT NULL,
  result text NOT NULL,
  reason text NOT NULL,
  safe_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (length(actor_subject) > 0 AND length(action) > 0),
  CHECK (result IN ('success','denied','conflict','failed')),
  CHECK (jsonb_typeof(safe_summary) = 'object')
);
CREATE INDEX audit_events_target_time
  ON oms.audit_events(target_tenant_id,created_at DESC,id);

ALTER TABLE oms.tenant_service_entitlements ENABLE ROW LEVEL SECURITY;
ALTER TABLE oms.quota_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE oms.grant_commitments ENABLE ROW LEVEL SECURITY;
ALTER TABLE oms.usage_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE oms.attempt_allocations ENABLE ROW LEVEL SECURITY;
ALTER TABLE oms.tenant_service_entitlements FORCE ROW LEVEL SECURITY;
ALTER TABLE oms.quota_grants FORCE ROW LEVEL SECURITY;
ALTER TABLE oms.grant_commitments FORCE ROW LEVEL SECURITY;
ALTER TABLE oms.usage_attempts FORCE ROW LEVEL SECURITY;
ALTER TABLE oms.attempt_allocations FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_scope ON oms.tenant_service_entitlements
  USING (tenant_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid);
CREATE POLICY tenant_scope ON oms.quota_grants
  USING (tenant_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid);
CREATE POLICY tenant_scope ON oms.grant_commitments
  USING (tenant_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid);
CREATE POLICY tenant_scope ON oms.usage_attempts
  USING (tenant_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid);
CREATE POLICY tenant_scope ON oms.attempt_allocations
  USING (tenant_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid);
