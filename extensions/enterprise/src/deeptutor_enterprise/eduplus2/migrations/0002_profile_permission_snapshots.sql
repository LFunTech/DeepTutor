-- EduPlus2 profile/permission snapshots.
-- Stores only minimum authorization snapshots; raw profile/API payloads and tokens are not persisted.

CREATE TABLE eduplus2.profile_snapshots (
  tenant_id uuid NOT NULL REFERENCES enterprise.tenants(id),
  provider text NOT NULL DEFAULT 'eduplus2',
  external_tenant_id text NOT NULL,
  external_user_id text NOT NULL,
  external_subject text NOT NULL DEFAULT '',
  external_identity_type text NOT NULL DEFAULT '',
  display_name text NOT NULL DEFAULT '',
  status text NOT NULL CHECK (status IN ('active','enabled','allowed','disabled','deleted','inactive','revoked')),
  profile_version text NOT NULL DEFAULT '',
  profile_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
  fetched_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, provider, external_tenant_id, external_user_id),
  CHECK (provider = 'eduplus2'),
  CHECK (length(external_tenant_id) > 0),
  CHECK (length(external_user_id) > 0),
  CHECK (jsonb_typeof(profile_snapshot) = 'object')
);
CREATE INDEX eduplus2_profile_status
  ON eduplus2.profile_snapshots(tenant_id, status, updated_at DESC);

CREATE TABLE eduplus2.permission_snapshots (
  tenant_id uuid NOT NULL REFERENCES enterprise.tenants(id),
  provider text NOT NULL DEFAULT 'eduplus2',
  client_registration_id uuid NOT NULL,
  external_tenant_id text NOT NULL,
  external_user_id text NOT NULL,
  external_subject text NOT NULL DEFAULT '',
  client_id text NOT NULL,
  external_app_id text NOT NULL,
  allowed boolean NOT NULL,
  reason text NOT NULL DEFAULT '',
  allowed_usages text[] NOT NULL DEFAULT ARRAY[]::text[],
  scopes text[] NOT NULL DEFAULT ARRAY[]::text[],
  permission_version text NOT NULL DEFAULT '',
  permission_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
  expires_at timestamptz,
  fetched_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, provider, external_tenant_id, external_user_id, client_registration_id),
  FOREIGN KEY (tenant_id, client_registration_id)
    REFERENCES eduplus2.external_client_registrations(tenant_id, id),
  CHECK (provider = 'eduplus2'),
  CHECK (length(external_tenant_id) > 0),
  CHECK (length(external_user_id) > 0),
  CHECK (length(client_id) > 0),
  CHECK (length(external_app_id) > 0),
  CHECK (jsonb_typeof(permission_snapshot) = 'object')
);
CREATE INDEX eduplus2_permission_user_time
  ON eduplus2.permission_snapshots(tenant_id, external_tenant_id, external_user_id, updated_at DESC);
CREATE INDEX eduplus2_permission_allowed_expiry
  ON eduplus2.permission_snapshots(tenant_id, allowed, expires_at);

DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['profile_snapshots','permission_snapshots'] LOOP
    EXECUTE format('ALTER TABLE eduplus2.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE eduplus2.%I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY tenant_scope ON eduplus2.%I USING (tenant_id = nullif(current_setting(''app.tenant_id'', true),'''')::uuid) WITH CHECK (tenant_id = nullif(current_setting(''app.tenant_id'', true),'''')::uuid)', t);
  END LOOP;
END $$;

GRANT SELECT,INSERT,UPDATE,DELETE ON eduplus2.profile_snapshots TO dt_enterprise_app;
GRANT SELECT,INSERT,UPDATE,DELETE ON eduplus2.permission_snapshots TO dt_enterprise_app;
