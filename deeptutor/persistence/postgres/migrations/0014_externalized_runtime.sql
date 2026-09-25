-- Production/Kubernetes externalized runtime metadata.
-- Files live in ObjectStore; PG is the visibility/lifecycle authority.
-- Settings/policy rows store desired/active state and Secret references only,
-- never Secret plaintext.
CREATE TABLE enterprise.resource_objects (
  tenant_id uuid NOT NULL,
  owner_id text NOT NULL,
  id uuid NOT NULL,
  resource_kind text NOT NULL DEFAULT '',
  resource_id text NOT NULL DEFAULT '',
  bucket text NOT NULL DEFAULT '',
  object_key text NOT NULL DEFAULT '',
  content_hash text NOT NULL DEFAULT '',
  size_bytes bigint NOT NULL DEFAULT 0,
  mime_type text NOT NULL DEFAULT '',
  state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','uploaded','ready','delete-pending','deleted','failed')),
  version bigint NOT NULL DEFAULT 1,
  retention text NOT NULL DEFAULT 'default' CHECK (retention IN ('default','temporary','retained','legal-hold')),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_by text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  cleanup_error text NOT NULL DEFAULT '',
  PRIMARY KEY (tenant_id, owner_id, id),
  UNIQUE (tenant_id, bucket, object_key),
  FOREIGN KEY (tenant_id, owner_id) REFERENCES enterprise.users(tenant_id, id),
  CHECK (length(resource_kind) > 0),
  CHECK (length(bucket) > 0),
  CHECK (length(object_key) > 0),
  CHECK ((content_hash = '') OR (length(content_hash) = 64)),
  CHECK (size_bytes >= 0),
  CHECK (version >= 1),
  CHECK (jsonb_typeof(metadata) = 'object')
);

CREATE TABLE enterprise.resource_cleanup_jobs (
  tenant_id uuid NOT NULL,
  owner_id text NOT NULL,
  object_id uuid NOT NULL,
  attempt bigint NOT NULL DEFAULT 0,
  state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','running','failed','done')),
  last_error text NOT NULL DEFAULT '',
  not_before timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, owner_id, object_id),
  FOREIGN KEY (tenant_id, owner_id, object_id)
    REFERENCES enterprise.resource_objects(tenant_id, owner_id, id) ON DELETE CASCADE,
  CHECK (attempt >= 0)
);

CREATE TABLE enterprise.runtime_settings (
  tenant_id uuid NOT NULL,
  scope_kind text NOT NULL DEFAULT 'tenant' CHECK (scope_kind IN ('platform','tenant','owner')),
  scope_id text NOT NULL DEFAULT '',
  key text NOT NULL,
  version bigint NOT NULL DEFAULT 1,
  desired jsonb NOT NULL DEFAULT '{}'::jsonb,
  active jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','saved','active','failed','draining')),
  updated_by text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, scope_kind, scope_id, key),
  FOREIGN KEY (tenant_id) REFERENCES enterprise.tenants(id),
  CHECK (length(key) > 0),
  CHECK (version >= 1),
  CHECK (jsonb_typeof(desired) = 'object'),
  CHECK (jsonb_typeof(active) = 'object')
);

CREATE TABLE enterprise.runtime_policies (
  tenant_id uuid NOT NULL,
  policy_kind text NOT NULL,
  subject_kind text NOT NULL DEFAULT 'tenant' CHECK (subject_kind IN ('tenant','owner','role','tool','model')),
  subject_id text NOT NULL DEFAULT '',
  version bigint NOT NULL DEFAULT 1,
  document jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','saved','active','failed','draining')),
  updated_by text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, policy_kind, subject_kind, subject_id),
  FOREIGN KEY (tenant_id) REFERENCES enterprise.tenants(id),
  CHECK (length(policy_kind) > 0),
  CHECK (version >= 1),
  CHECK (jsonb_typeof(document) = 'object')
);

CREATE TABLE enterprise.secret_references (
  tenant_id uuid NOT NULL,
  scope_kind text NOT NULL DEFAULT 'tenant' CHECK (scope_kind IN ('platform','tenant','owner')),
  scope_id text NOT NULL DEFAULT '',
  name text NOT NULL,
  provider text NOT NULL DEFAULT 'env',
  reference text NOT NULL,
  version bigint NOT NULL DEFAULT 1,
  status text NOT NULL DEFAULT 'saved' CHECK (status IN ('saved','active','failed','draining','missing')),
  redacted_summary text NOT NULL DEFAULT '',
  updated_by text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, scope_kind, scope_id, name),
  FOREIGN KEY (tenant_id) REFERENCES enterprise.tenants(id),
  CHECK (length(name) > 0),
  CHECK (length(provider) > 0),
  CHECK (length(reference) > 0),
  CHECK (version >= 1)
);

CREATE TABLE enterprise.runtime_audit_events (
  tenant_id uuid NOT NULL,
  id uuid NOT NULL,
  event_kind text NOT NULL,
  actor_id text NOT NULL DEFAULT '',
  scope_kind text NOT NULL DEFAULT 'tenant' CHECK (scope_kind IN ('platform','tenant','owner','resource')),
  scope_id text NOT NULL DEFAULT '',
  resource_kind text NOT NULL DEFAULT '',
  resource_id text NOT NULL DEFAULT '',
  summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id) REFERENCES enterprise.tenants(id),
  CHECK (length(event_kind) > 0),
  CHECK (jsonb_typeof(summary) = 'object')
);

ALTER TABLE enterprise.resource_objects ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON enterprise.resource_objects
  USING (tenant_id = nullif(current_setting('app.tenant_id', true),'')::uuid)
  WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true),'')::uuid);
CREATE POLICY owner_scope ON enterprise.resource_objects AS RESTRICTIVE
  USING (owner_id = nullif(current_setting('app.user_id', true),''))
  WITH CHECK (owner_id = nullif(current_setting('app.user_id', true),''));

ALTER TABLE enterprise.resource_cleanup_jobs ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON enterprise.resource_cleanup_jobs
  USING (tenant_id = nullif(current_setting('app.tenant_id', true),'')::uuid)
  WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true),'')::uuid);
CREATE POLICY owner_scope ON enterprise.resource_cleanup_jobs AS RESTRICTIVE
  USING (owner_id = nullif(current_setting('app.user_id', true),''))
  WITH CHECK (owner_id = nullif(current_setting('app.user_id', true),''));

ALTER TABLE enterprise.runtime_settings ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON enterprise.runtime_settings
  USING (tenant_id = nullif(current_setting('app.tenant_id', true),'')::uuid)
  WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true),'')::uuid);

ALTER TABLE enterprise.runtime_policies ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON enterprise.runtime_policies
  USING (tenant_id = nullif(current_setting('app.tenant_id', true),'')::uuid)
  WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true),'')::uuid);

ALTER TABLE enterprise.secret_references ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON enterprise.secret_references
  USING (tenant_id = nullif(current_setting('app.tenant_id', true),'')::uuid)
  WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true),'')::uuid);

ALTER TABLE enterprise.runtime_audit_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON enterprise.runtime_audit_events
  USING (tenant_id = nullif(current_setting('app.tenant_id', true),'')::uuid)
  WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true),'')::uuid);

CREATE INDEX resource_objects_kind_state
  ON enterprise.resource_objects(tenant_id, owner_id, resource_kind, state, updated_at);
CREATE INDEX resource_cleanup_jobs_state
  ON enterprise.resource_cleanup_jobs(tenant_id, owner_id, state, not_before);
CREATE INDEX runtime_settings_status
  ON enterprise.runtime_settings(tenant_id, status, updated_at);
CREATE INDEX runtime_policies_status
  ON enterprise.runtime_policies(tenant_id, status, updated_at);
CREATE INDEX secret_references_status
  ON enterprise.secret_references(tenant_id, status, updated_at);
CREATE INDEX runtime_audit_events_kind_time
  ON enterprise.runtime_audit_events(tenant_id, event_kind, created_at DESC);
