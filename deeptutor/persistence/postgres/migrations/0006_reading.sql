-- 阅读目录：同 scope 会员、延迟排序约束与 typed 题库来源。
CREATE TABLE enterprise.reading_materials (
 tenant_id uuid NOT NULL,
 owner_id text NOT NULL,
 material_id text NOT NULL,
 content_id text NOT NULL,
 filename text NOT NULL,
 title text NOT NULL,
 source_kind text NOT NULL,
 source_url text NOT NULL,
 mime text NOT NULL,
 render_mode text NOT NULL,
 cover_url text NOT NULL,
 duration_seconds double precision NOT NULL,
 status text NOT NULL,
 progress integer NOT NULL,
 error_code text NOT NULL,
 error_detail text NOT NULL,
 last_opened_at double precision NOT NULL,
 version bigint NOT NULL,
 created_at double precision NOT NULL,
 updated_at double precision NOT NULL,
 PRIMARY KEY (tenant_id, owner_id, material_id),
 FOREIGN KEY (tenant_id, owner_id) REFERENCES enterprise.users(tenant_id, id),
 CHECK ((material_id ~ '^[A-Za-z0-9_-]{1,128}$'::text)),
 CHECK ((source_kind = ANY (ARRAY['file'::text, 'web'::text, 'video'::text, 'youtube'::text, 'bilibili'::text, 'audio'::text]))),
 CHECK ((status = ANY (ARRAY['queued'::text, 'processing'::text, 'ready'::text, 'failed'::text]))),
 CHECK ((version > 0)),
 CHECK (((progress >= 0) AND (progress <= 100))),
 CHECK (((status = 'ready'::text) = (progress = 100))),
 CHECK ((duration_seconds >= (0)::double precision))
);
CREATE TABLE enterprise.reading_workspaces (
 tenant_id uuid NOT NULL,
 owner_id text NOT NULL,
 workspace_id text NOT NULL,
 title text NOT NULL,
 description text NOT NULL,
 active_material_id text,
 version bigint NOT NULL,
 created_at double precision NOT NULL,
 updated_at double precision NOT NULL,
 PRIMARY KEY (tenant_id, owner_id, workspace_id),
 FOREIGN KEY (tenant_id, owner_id) REFERENCES enterprise.users(tenant_id, id),
 CHECK ((workspace_id ~ '^[A-Za-z0-9_-]{1,128}$'::text)),
 CHECK ((version > 0))
);
CREATE TABLE enterprise.reading_workspace_materials (
 tenant_id uuid NOT NULL,
 owner_id text NOT NULL,
 workspace_id text NOT NULL,
 material_id text NOT NULL,
 tab_order integer NOT NULL,
 pinned boolean NOT NULL,
 opened boolean NOT NULL,
 added_at double precision NOT NULL,
 PRIMARY KEY (tenant_id, owner_id, workspace_id, material_id),
 UNIQUE (tenant_id, owner_id, workspace_id, tab_order) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY (tenant_id, owner_id, workspace_id) REFERENCES enterprise.reading_workspaces(tenant_id, owner_id, workspace_id) ON DELETE CASCADE,
 FOREIGN KEY (tenant_id, owner_id, material_id) REFERENCES enterprise.reading_materials(tenant_id, owner_id, material_id) ON DELETE CASCADE,
 CHECK ((tab_order >= 0))
);
ALTER TABLE enterprise.reading_workspaces ADD FOREIGN KEY (tenant_id, owner_id, workspace_id, active_material_id) REFERENCES enterprise.reading_workspace_materials(tenant_id, owner_id, workspace_id, material_id) ON DELETE SET NULL (active_material_id) DEFERRABLE INITIALLY DEFERRED;
CREATE TABLE enterprise.reading_workspace_sessions (
 tenant_id uuid NOT NULL,
 owner_id text NOT NULL,
 workspace_id text NOT NULL,
 session_id text NOT NULL,
 title text NOT NULL,
 active_material_id text,
 version bigint NOT NULL,
 created_at double precision NOT NULL,
 updated_at double precision NOT NULL,
 PRIMARY KEY (tenant_id, owner_id, session_id),
 UNIQUE (tenant_id, owner_id, workspace_id, session_id),
 CHECK ((session_id ~ '^[A-Za-z0-9_-]{1,128}$'::text)),
 CHECK ((version > 0)),
 FOREIGN KEY (tenant_id, owner_id, workspace_id) REFERENCES enterprise.reading_workspaces(tenant_id, owner_id, workspace_id) ON DELETE CASCADE,
 FOREIGN KEY (tenant_id, owner_id, session_id) REFERENCES enterprise.sessions(tenant_id, owner_id, id) ON DELETE CASCADE,
 FOREIGN KEY (tenant_id, owner_id, workspace_id, active_material_id) REFERENCES enterprise.reading_workspace_materials(tenant_id, owner_id, workspace_id, material_id) ON DELETE SET NULL (active_material_id) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE enterprise.reading_session_links (
 tenant_id uuid NOT NULL,
 owner_id text NOT NULL,
 workspace_id text NOT NULL,
 source_session_id text NOT NULL,
 target_session_id text NOT NULL,
 created_at double precision NOT NULL,
 PRIMARY KEY (tenant_id, owner_id, workspace_id, source_session_id, target_session_id),
 CHECK ((source_session_id <> target_session_id)),
 FOREIGN KEY (tenant_id, owner_id, workspace_id, source_session_id) REFERENCES enterprise.reading_workspace_sessions(tenant_id, owner_id, workspace_id, session_id) ON DELETE CASCADE,
 FOREIGN KEY (tenant_id, owner_id, workspace_id, target_session_id) REFERENCES enterprise.reading_workspace_sessions(tenant_id, owner_id, workspace_id, session_id) ON DELETE CASCADE
);
ALTER TABLE enterprise.notebook_entries ADD COLUMN reading_material_ref text GENERATED ALWAYS AS (CASE WHEN source='immersive_reading' THEN nullif(material_id,'') END) STORED, ADD FOREIGN KEY (tenant_id, owner_id, reading_material_ref) REFERENCES enterprise.reading_materials(tenant_id, owner_id, material_id), ADD CHECK (((source <> 'immersive_reading'::text) OR (material_id <> ''::text)));
CREATE INDEX reading_materials_recent ON enterprise.reading_materials USING btree (tenant_id, owner_id, updated_at DESC, material_id DESC);
CREATE INDEX reading_materials_content ON enterprise.reading_materials USING btree (tenant_id, owner_id, content_id, created_at, material_id);
CREATE INDEX reading_materials_filename ON enterprise.reading_materials USING btree (tenant_id, owner_id, translate(filename, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'::text, 'abcdefghijklmnopqrstuvwxyz'::text), status, updated_at DESC, material_id);
CREATE INDEX reading_workspaces_recent ON enterprise.reading_workspaces USING btree (tenant_id, owner_id, updated_at DESC, workspace_id DESC);
CREATE INDEX reading_tabs_material ON enterprise.reading_workspace_materials USING btree (tenant_id, owner_id, material_id, workspace_id);
CREATE INDEX reading_sessions_recent ON enterprise.reading_workspace_sessions USING btree (tenant_id, owner_id, workspace_id, updated_at DESC, session_id DESC);
CREATE INDEX reading_links_recent ON enterprise.reading_session_links USING btree (tenant_id, owner_id, workspace_id, source_session_id, created_at, target_session_id);
CREATE INDEX reading_links_target ON enterprise.reading_session_links USING btree (tenant_id, owner_id, workspace_id, target_session_id);
CREATE INDEX reading_workspace_active ON enterprise.reading_workspaces USING btree (tenant_id, owner_id, workspace_id, active_material_id);
CREATE INDEX reading_session_active ON enterprise.reading_workspace_sessions USING btree (tenant_id, owner_id, workspace_id, active_material_id);
CREATE INDEX notebook_reading_material ON enterprise.notebook_entries USING btree (tenant_id, owner_id, reading_material_ref);
ALTER TABLE enterprise.reading_materials ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON enterprise.reading_materials USING (tenant_id = nullif(current_setting('app.tenant_id',true),'')::uuid) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id',true),'')::uuid);
CREATE POLICY owner_scope ON enterprise.reading_materials AS RESTRICTIVE USING (owner_id = nullif(current_setting('app.user_id',true),'')) WITH CHECK (owner_id = nullif(current_setting('app.user_id',true),''));
ALTER TABLE enterprise.reading_workspaces ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON enterprise.reading_workspaces USING (tenant_id = nullif(current_setting('app.tenant_id',true),'')::uuid) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id',true),'')::uuid);
CREATE POLICY owner_scope ON enterprise.reading_workspaces AS RESTRICTIVE USING (owner_id = nullif(current_setting('app.user_id',true),'')) WITH CHECK (owner_id = nullif(current_setting('app.user_id',true),''));
ALTER TABLE enterprise.reading_workspace_materials ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON enterprise.reading_workspace_materials USING (tenant_id = nullif(current_setting('app.tenant_id',true),'')::uuid) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id',true),'')::uuid);
CREATE POLICY owner_scope ON enterprise.reading_workspace_materials AS RESTRICTIVE USING (owner_id = nullif(current_setting('app.user_id',true),'')) WITH CHECK (owner_id = nullif(current_setting('app.user_id',true),''));
ALTER TABLE enterprise.reading_workspace_sessions ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON enterprise.reading_workspace_sessions USING (tenant_id = nullif(current_setting('app.tenant_id',true),'')::uuid) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id',true),'')::uuid);
CREATE POLICY owner_scope ON enterprise.reading_workspace_sessions AS RESTRICTIVE USING (owner_id = nullif(current_setting('app.user_id',true),'')) WITH CHECK (owner_id = nullif(current_setting('app.user_id',true),''));
ALTER TABLE enterprise.reading_session_links ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON enterprise.reading_session_links USING (tenant_id = nullif(current_setting('app.tenant_id',true),'')::uuid) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id',true),'')::uuid);
CREATE POLICY owner_scope ON enterprise.reading_session_links AS RESTRICTIVE USING (owner_id = nullif(current_setting('app.user_id',true),'')) WITH CHECK (owner_id = nullif(current_setting('app.user_id',true),''));
