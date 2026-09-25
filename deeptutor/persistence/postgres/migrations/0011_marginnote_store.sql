-- MarginNote 4 store：按 tenant/owner/KB/device 隔离对象、设备、游标与 tombstone。
CREATE TABLE enterprise.marginnote_devices (
 tenant_id uuid NOT NULL,
 owner_id text NOT NULL,
 kb_id text NOT NULL,
 device_id text NOT NULL,
 device_name text NOT NULL DEFAULT '',
 device_kind text NOT NULL DEFAULT 'macos',
 token_hash text NOT NULL,
 paired_at text NOT NULL DEFAULT '',
 last_seen text NOT NULL DEFAULT '',
 active boolean NOT NULL DEFAULT true,
 PRIMARY KEY (tenant_id, owner_id, kb_id, device_id),
 FOREIGN KEY (tenant_id, owner_id) REFERENCES enterprise.users(tenant_id, id),
 CHECK ((length(kb_id) > 0) AND (length(kb_id) <= 255)),
 CHECK (length(device_id) > 0),
 CHECK (length(device_kind) > 0),
 CHECK (length(token_hash) = 64)
);
CREATE TABLE enterprise.marginnote_cursors (
 tenant_id uuid NOT NULL,
 owner_id text NOT NULL,
 kb_id text NOT NULL,
 device_id text NOT NULL,
 cursor text NOT NULL DEFAULT '',
 updated_at text NOT NULL DEFAULT '',
 PRIMARY KEY (tenant_id, owner_id, kb_id, device_id),
 FOREIGN KEY (tenant_id, owner_id, kb_id, device_id)
  REFERENCES enterprise.marginnote_devices(tenant_id, owner_id, kb_id, device_id)
  ON DELETE CASCADE
);
CREATE TABLE enterprise.marginnote_objects (
 tenant_id uuid NOT NULL,
 owner_id text NOT NULL,
 kb_id text NOT NULL,
 device_id text NOT NULL,
 object_id text NOT NULL,
 object_type text NOT NULL,
 title text NOT NULL DEFAULT '',
 content text NOT NULL DEFAULT '',
 excerpt text,
 document_id text,
 document_title text,
 page integer,
 tags jsonb NOT NULL DEFAULT '[]'::jsonb,
 links jsonb NOT NULL DEFAULT '[]'::jsonb,
 color text,
 created_at text NOT NULL DEFAULT '',
 updated_at text NOT NULL DEFAULT '',
 synced_at text NOT NULL DEFAULT '',
 raw jsonb NOT NULL DEFAULT '{}'::jsonb,
 PRIMARY KEY (tenant_id, owner_id, kb_id, device_id, object_id),
 FOREIGN KEY (tenant_id, owner_id, kb_id, device_id)
  REFERENCES enterprise.marginnote_devices(tenant_id, owner_id, kb_id, device_id)
  ON DELETE CASCADE,
 CHECK (length(object_id) > 0),
 CHECK (object_type IN ('note','excerpt','card','mindmap_node','document','comment')),
 CHECK ((page IS NULL) OR (page >= 0)),
 CHECK (jsonb_typeof(tags) = 'array'),
 CHECK (jsonb_typeof(links) = 'array'),
 CHECK (jsonb_typeof(raw) = 'object')
);
CREATE TABLE enterprise.marginnote_tombstones (
 tenant_id uuid NOT NULL,
 owner_id text NOT NULL,
 kb_id text NOT NULL,
 device_id text NOT NULL,
 object_id text NOT NULL,
 deleted_at text NOT NULL DEFAULT '',
 PRIMARY KEY (tenant_id, owner_id, kb_id, device_id, object_id),
 FOREIGN KEY (tenant_id, owner_id, kb_id, device_id)
  REFERENCES enterprise.marginnote_devices(tenant_id, owner_id, kb_id, device_id)
  ON DELETE CASCADE,
 CHECK (length(object_id) > 0)
);
CREATE INDEX marginnote_objects_type ON enterprise.marginnote_objects USING btree (tenant_id, owner_id, kb_id, object_type, updated_at DESC, object_id);
CREATE INDEX marginnote_objects_document ON enterprise.marginnote_objects USING btree (tenant_id, owner_id, kb_id, document_id, updated_at DESC, object_id) WHERE (document_id IS NOT NULL);
CREATE INDEX marginnote_objects_device_updated ON enterprise.marginnote_objects USING btree (tenant_id, owner_id, kb_id, device_id, updated_at DESC, object_id);
CREATE INDEX marginnote_tombstones_device ON enterprise.marginnote_tombstones USING btree (tenant_id, owner_id, kb_id, device_id, deleted_at DESC, object_id);
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['marginnote_devices','marginnote_cursors','marginnote_objects','marginnote_tombstones'] LOOP
  EXECUTE format('ALTER TABLE enterprise.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY tenant_scope ON enterprise.%I USING (tenant_id = nullif(current_setting(''app.tenant_id'',true),'''')::uuid) WITH CHECK (tenant_id = nullif(current_setting(''app.tenant_id'',true),'''')::uuid)',t);
  EXECUTE format('CREATE POLICY owner_scope ON enterprise.%I AS RESTRICTIVE USING (owner_id = nullif(current_setting(''app.user_id'',true),'''')) WITH CHECK (owner_id = nullif(current_setting(''app.user_id'',true),''''))',t);
 END LOOP;
END $$;
