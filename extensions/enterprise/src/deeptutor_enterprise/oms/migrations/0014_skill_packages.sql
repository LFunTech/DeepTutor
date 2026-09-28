-- Skill 内容版本不可变；仅元数据/授权在 PG，完整 ZIP 在 S3-compatible ObjectStore。
-- global 与学校 owner 分开，初始无 publication、grant 或 builtin 自动授权。
CREATE TABLE oms.skill_revisions (
  id uuid PRIMARY KEY,
  owner_kind text NOT NULL,
  owner_school_id uuid REFERENCES enterprise.tenants(id),
  name text NOT NULL CHECK (name ~ '^[a-z0-9][a-z0-9-]{0,63}$'),
  version bigint NOT NULL CHECK (version > 0),
  source text NOT NULL,
  content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
  object_key text NOT NULL UNIQUE CHECK (length(trim(object_key)) > 0),
  content_bytes bigint NOT NULL CHECK (content_bytes > 0 AND content_bytes <= 20000000),
  metadata jsonb NOT NULL CHECK (jsonb_typeof(metadata)='object'),
  created_by text NOT NULL CHECK (length(trim(created_by)) > 0),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX skill_global_revision_version
  ON oms.skill_revisions(name,version) WHERE owner_kind='global';
CREATE UNIQUE INDEX skill_tenant_revision_version
  ON oms.skill_revisions(owner_school_id,name,version) WHERE owner_kind='tenant';

CREATE TABLE oms.skill_publications (
  id uuid PRIMARY KEY,
  owner_kind text NOT NULL,
  owner_school_id uuid REFERENCES enterprise.tenants(id),
  name text NOT NULL,
  revision_id uuid NOT NULL REFERENCES oms.skill_revisions(id),
  version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
  published_by text NOT NULL CHECK (length(trim(published_by)) > 0),
  published_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX skill_global_publication
  ON oms.skill_publications(name) WHERE owner_kind='global';
CREATE UNIQUE INDEX skill_tenant_publication
  ON oms.skill_publications(owner_school_id,name) WHERE owner_kind='tenant';

CREATE TABLE oms.skill_grants (
  tenant_id uuid NOT NULL REFERENCES enterprise.tenants(id),
  name text NOT NULL,
  revision_id uuid NOT NULL REFERENCES oms.skill_revisions(id),
  status text NOT NULL DEFAULT 'active',
  version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
  expires_at timestamptz NOT NULL,
  granted_by text NOT NULL CHECK (length(trim(granted_by)) > 0),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id,name)
);

ALTER TABLE oms.skill_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE oms.skill_revisions FORCE ROW LEVEL SECURITY;
CREATE POLICY skill_owner_scope ON oms.skill_revisions
  USING (owner_kind='global' OR owner_school_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid)
  WITH CHECK (owner_kind='global' OR owner_school_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid);
ALTER TABLE oms.skill_publications ENABLE ROW LEVEL SECURITY;
ALTER TABLE oms.skill_publications FORCE ROW LEVEL SECURITY;
CREATE POLICY skill_owner_scope ON oms.skill_publications
  USING (owner_kind='global' OR owner_school_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid)
  WITH CHECK (owner_kind='global' OR owner_school_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid);
ALTER TABLE oms.skill_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE oms.skill_grants FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON oms.skill_grants
  USING (tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid)
  WITH CHECK (tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid);
