-- 离线导入 staging / 批次账本 / 维护门禁。
-- 运行角色只能读取 enterprise.maintenance_locks 以 fail-closed，
-- 不得访问 migration_stage schema 中的源数据、映射或进度。
CREATE SCHEMA migration_stage;
REVOKE ALL ON SCHEMA migration_stage FROM PUBLIC;

CREATE TABLE enterprise.maintenance_locks (
 tenant_id uuid PRIMARY KEY,
 batch_id uuid NOT NULL,
 active boolean NOT NULL DEFAULT true,
 reason text NOT NULL DEFAULT '',
 entered_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 released_at timestamptz,
 generation bigint NOT NULL DEFAULT 1,
 FOREIGN KEY (tenant_id) REFERENCES enterprise.tenants(id),
 CHECK (generation >= 1)
);
ALTER TABLE enterprise.maintenance_locks ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON enterprise.maintenance_locks
 USING (tenant_id = nullif(current_setting('app.tenant_id', true),'')::uuid)
 WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true),'')::uuid);

CREATE TABLE migration_stage.batches (
 batch_id uuid PRIMARY KEY,
 target_tenant_id uuid NOT NULL,
 manifest_sha256 text NOT NULL,
 source_manifest jsonb NOT NULL DEFAULT '{}'::jsonb,
 verify_report jsonb NOT NULL DEFAULT '{}'::jsonb,
 status text NOT NULL DEFAULT 'planned',
 operator text NOT NULL DEFAULT '',
 error text NOT NULL DEFAULT '',
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 CHECK (length(manifest_sha256) = 64),
 CHECK (jsonb_typeof(source_manifest) = 'object'),
 CHECK (jsonb_typeof(verify_report) = 'object'),
 CHECK (status IN ('planned','importing','verified','promoting','published','cancelled','failed'))
);
CREATE TABLE migration_stage.sources (
 batch_id uuid NOT NULL REFERENCES migration_stage.batches(batch_id) ON DELETE CASCADE,
 source_id text NOT NULL,
 source_type text NOT NULL,
 source_version text NOT NULL,
 source_owner_id text NOT NULL,
 target_owner_id text NOT NULL,
 fingerprint text NOT NULL,
 manifest jsonb NOT NULL DEFAULT '{}'::jsonb,
 status text NOT NULL DEFAULT 'planned',
 rows_total bigint NOT NULL DEFAULT 0,
 rows_done bigint NOT NULL DEFAULT 0,
 PRIMARY KEY (batch_id, source_id),
 CHECK (length(source_id) > 0),
 CHECK (length(fingerprint) = 64),
 CHECK (jsonb_typeof(manifest) = 'object'),
 CHECK (rows_total >= 0),
 CHECK (rows_done >= 0),
 CHECK (status IN ('planned','importing','imported','verified','failed','cancelled'))
);
CREATE TABLE migration_stage.id_mappings (
 batch_id uuid NOT NULL REFERENCES migration_stage.batches(batch_id) ON DELETE CASCADE,
 domain text NOT NULL,
 source_id text NOT NULL,
 source_owner_id text NOT NULL,
 source_key text NOT NULL,
 target_key text,
 target_int bigint,
 metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
 PRIMARY KEY (batch_id, domain, source_id, source_owner_id, source_key),
 CHECK ((target_key IS NOT NULL) OR (target_int IS NOT NULL)),
 CHECK (jsonb_typeof(metadata) = 'object')
);
CREATE TABLE migration_stage.progress (
 batch_id uuid NOT NULL REFERENCES migration_stage.batches(batch_id) ON DELETE CASCADE,
 domain text NOT NULL,
 chunk_key text NOT NULL,
 status text NOT NULL,
 rows_done bigint NOT NULL DEFAULT 0,
 resume_cursor jsonb NOT NULL DEFAULT '{}'::jsonb,
 checksum text NOT NULL DEFAULT '',
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (batch_id, domain, chunk_key),
 CHECK (rows_done >= 0),
 CHECK (jsonb_typeof(resume_cursor) = 'object'),
 CHECK (status IN ('planned','importing','imported','verified','failed','cancelled'))
);
CREATE TABLE migration_stage.promotion_items (
 batch_id uuid NOT NULL REFERENCES migration_stage.batches(batch_id) ON DELETE CASCADE,
 domain text NOT NULL,
 item_key text NOT NULL,
 payload jsonb NOT NULL DEFAULT '{}'::jsonb,
 status text NOT NULL DEFAULT 'staged',
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (batch_id, domain, item_key),
 CHECK (jsonb_typeof(payload) = 'object'),
 CHECK (status IN ('staged','promoted','failed','cancelled'))
);
CREATE INDEX migration_stage_sources_version
 ON migration_stage.sources(batch_id, source_version, source_id);
CREATE INDEX migration_stage_mappings_target_key
 ON migration_stage.id_mappings(batch_id, domain, target_key)
 WHERE target_key IS NOT NULL;
CREATE INDEX migration_stage_mappings_target_int
 ON migration_stage.id_mappings(batch_id, domain, target_int)
 WHERE target_int IS NOT NULL;
CREATE INDEX migration_stage_progress_status
 ON migration_stage.progress(batch_id, status, updated_at);
CREATE INDEX migration_stage_promotion_status
 ON migration_stage.promotion_items(batch_id, status, updated_at);
