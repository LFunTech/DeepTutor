-- EduPlus2 federated access extension schema.
-- Stores only client/app/user bindings, Secret references and redacted audit summaries.
CREATE TABLE eduplus2.provider_clients (
  tenant_id uuid NOT NULL REFERENCES enterprise.tenants(id),
  client_id text NOT NULL,
  secret_ref text NOT NULL,
  issuer text NOT NULL,
  base_url text NOT NULL,
  redirect_uri text NOT NULL,
  enabled boolean NOT NULL DEFAULT false,
  version bigint NOT NULL DEFAULT 1,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','rotating','revoked','disabled')),
  secret_fingerprint text NOT NULL DEFAULT '',
  installed_by text NOT NULL DEFAULT '',
  installed_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, client_id),
  CHECK (length(client_id) > 0),
  CHECK (length(secret_ref) > 0),
  CHECK (length(issuer) > 0),
  CHECK (version >= 1)
);

CREATE TABLE eduplus2.external_client_registrations (
  tenant_id uuid NOT NULL REFERENCES enterprise.tenants(id),
  id uuid NOT NULL,
  provider text NOT NULL DEFAULT 'eduplus2',
  client_id text NOT NULL,
  external_tenant_id text NOT NULL,
  external_tenant_name text NOT NULL DEFAULT '',
  external_app_id text NOT NULL,
  external_app_name text NOT NULL DEFAULT '',
  internal_tenant_id uuid NOT NULL,
  registered_by_surface text NOT NULL CHECK (registered_by_surface IN ('tms','oms','webhook','ops_cli','env_allowlist','auto_upsert','test_seed')),
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','revoked','suspended','pending_verification')),
  resolve_version text NOT NULL DEFAULT '',
  policy_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_by text NOT NULL DEFAULT '',
  updated_by text NOT NULL DEFAULT '',
  revoked_by text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  revoked_at timestamptz,
  PRIMARY KEY (tenant_id, id),
  CHECK (provider = 'eduplus2'),
  CHECK (tenant_id = internal_tenant_id),
  CHECK (length(client_id) > 0),
  CHECK (length(external_tenant_id) > 0),
  CHECK (length(external_app_id) > 0),
  CHECK (jsonb_typeof(policy_snapshot) = 'object')
);
CREATE UNIQUE INDEX eduplus2_active_client_id
  ON eduplus2.external_client_registrations(client_id)
  WHERE status = 'active';
CREATE UNIQUE INDEX eduplus2_active_tenant_app
  ON eduplus2.external_client_registrations(provider, external_tenant_id, external_app_id)
  WHERE status = 'active';
CREATE INDEX eduplus2_registrations_tenant_status
  ON eduplus2.external_client_registrations(tenant_id, status, updated_at DESC);

CREATE TABLE eduplus2.identity_bindings (
  tenant_id uuid NOT NULL REFERENCES enterprise.tenants(id),
  provider text NOT NULL DEFAULT 'eduplus2',
  external_tenant_id text NOT NULL,
  external_user_id text NOT NULL,
  external_subject text NOT NULL DEFAULT '',
  external_identity_type text NOT NULL DEFAULT '',
  internal_user_id text NOT NULL,
  last_client_registration_id uuid NOT NULL,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled','revoked')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, provider, external_tenant_id, external_user_id),
  UNIQUE (tenant_id, internal_user_id),
  FOREIGN KEY (tenant_id, internal_user_id) REFERENCES enterprise.users(tenant_id, id),
  FOREIGN KEY (tenant_id, last_client_registration_id)
    REFERENCES eduplus2.external_client_registrations(tenant_id, id),
  CHECK (provider = 'eduplus2'),
  CHECK (length(external_tenant_id) > 0),
  CHECK (length(external_user_id) > 0)
);

CREATE TABLE eduplus2.resolve_cache (
  tenant_id uuid NOT NULL REFERENCES enterprise.tenants(id),
  client_id text NOT NULL,
  resolved jsonb NOT NULL,
  resolve_version text NOT NULL DEFAULT '',
  expires_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, client_id),
  CHECK (length(client_id) > 0),
  CHECK (jsonb_typeof(resolved) = 'object')
);

CREATE TABLE eduplus2.audit_events (
  tenant_id uuid NOT NULL REFERENCES enterprise.tenants(id),
  id uuid NOT NULL,
  request_id text NOT NULL DEFAULT '',
  event_kind text NOT NULL,
  actor_id text NOT NULL DEFAULT '',
  client_id text NOT NULL DEFAULT '',
  external_tenant_id text NOT NULL DEFAULT '',
  external_app_id text NOT NULL DEFAULT '',
  external_user_id text NOT NULL DEFAULT '',
  internal_user_id text NOT NULL DEFAULT '',
  session_id text NOT NULL DEFAULT '',
  turn_id text NOT NULL DEFAULT '',
  result text NOT NULL CHECK (result IN ('success','denied','replayed','failed')),
  reason text NOT NULL DEFAULT '',
  policy_version text NOT NULL DEFAULT '',
  summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, id),
  CHECK (length(event_kind) > 0),
  CHECK (jsonb_typeof(summary) = 'object')
);
CREATE INDEX eduplus2_audit_kind_time ON eduplus2.audit_events(tenant_id, event_kind, created_at DESC);
CREATE INDEX eduplus2_audit_request ON eduplus2.audit_events(tenant_id, request_id) WHERE request_id <> '';

DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['provider_clients','external_client_registrations','identity_bindings','resolve_cache','audit_events'] LOOP
    EXECUTE format('ALTER TABLE eduplus2.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY tenant_scope ON eduplus2.%I USING (tenant_id = nullif(current_setting(''app.tenant_id'', true),'''')::uuid) WITH CHECK (tenant_id = nullif(current_setting(''app.tenant_id'', true),'''')::uuid)', t);
  END LOOP;
END $$;
