-- Per-owner course registry. Courses are user-authored runtime state and must
-- live in the same tenant/owner boundary as sessions, mastery and reading data.
CREATE TABLE enterprise.courses (
  tenant_id uuid NOT NULL,
  owner_id text NOT NULL DEFAULT '',
  id text NOT NULL DEFAULT '',
  name text NOT NULL DEFAULT '',
  description text NOT NULL DEFAULT '',
  color text NOT NULL DEFAULT '',
  instructions text NOT NULL DEFAULT '',
  agent_notes text NOT NULL DEFAULT '',
  default_capability text NOT NULL DEFAULT '',
  default_persona text NOT NULL DEFAULT '',
  resources jsonb NOT NULL DEFAULT '[]'::jsonb,
  syllabus jsonb NOT NULL DEFAULT '[]'::jsonb,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','archived')),
  archived_at double precision NOT NULL DEFAULT 0,
  created_at double precision NOT NULL DEFAULT extract(epoch FROM now()),
  updated_at double precision NOT NULL DEFAULT extract(epoch FROM now()),
  version bigint NOT NULL DEFAULT 1,
  PRIMARY KEY (tenant_id, owner_id, id),
  FOREIGN KEY (tenant_id, owner_id) REFERENCES enterprise.users(tenant_id, id),
  CHECK (jsonb_typeof(resources) = 'array'),
  CHECK (jsonb_typeof(syllabus) = 'array'),
  CHECK (length(id) > 0),
  CHECK (length(name) > 0),
  CHECK (version >= 1)
);

ALTER TABLE enterprise.courses ENABLE ROW LEVEL SECURITY;
ALTER TABLE enterprise.courses FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON enterprise.courses
  USING (tenant_id = nullif(current_setting('app.tenant_id', true),'')::uuid)
  WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true),'')::uuid);
CREATE POLICY owner_scope ON enterprise.courses AS RESTRICTIVE
  USING (owner_id = nullif(current_setting('app.user_id', true),''))
  WITH CHECK (owner_id = nullif(current_setting('app.user_id', true),''));

CREATE INDEX courses_recent ON enterprise.courses(tenant_id, owner_id, created_at, name);
GRANT SELECT,INSERT,UPDATE,DELETE ON enterprise.courses TO dt_enterprise_app;
