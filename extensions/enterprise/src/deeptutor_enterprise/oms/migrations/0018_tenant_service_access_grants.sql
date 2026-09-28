-- TMS 服务访问 grant：仅表示成员/应用/服务主体调用资格，不是额度授予。
-- 状态、主体类型和同步状态均由应用层校验；数据库不使用 ENUM 或枚举 CHECK。

CREATE TABLE oms.tenant_service_access_grants (
  tenant_id uuid NOT NULL,
  id uuid NOT NULL,
  service_id text NOT NULL,
  subject_kind text NOT NULL,
  subject_id text NOT NULL,
  entitlement_version bigint NOT NULL,
  starts_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  status text NOT NULL,
  sync_status text NOT NULL,
  version bigint NOT NULL,
  revoked_at timestamptz,
  command_id uuid NOT NULL,
  created_by text NOT NULL,
  reason text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id,id)
);

CREATE INDEX tenant_service_access_subject
  ON oms.tenant_service_access_grants(tenant_id,service_id,subject_kind,subject_id);

ALTER TABLE oms.tenant_service_access_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE oms.tenant_service_access_grants FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_scope ON oms.tenant_service_access_grants
  USING (tenant_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid);
