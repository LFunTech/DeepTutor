-- Partners runtime status projection：按 tenant/owner 隔离，worker/version/TTL 防止旧执行者覆盖新状态。
CREATE TABLE enterprise.partner_runtime_status (
 tenant_id uuid NOT NULL,
 owner_id text NOT NULL,
 partner_id text NOT NULL,
 worker_id text NOT NULL,
 version bigint NOT NULL DEFAULT 1,
 running boolean NOT NULL,
 state text NOT NULL,
 started_at text,
 last_reload_error text,
 payload jsonb NOT NULL,
 updated_at_ms bigint NOT NULL,
 expires_at_ms bigint NOT NULL,
 ttl_ms bigint NOT NULL,
 PRIMARY KEY (tenant_id, owner_id, partner_id),
 FOREIGN KEY (tenant_id, owner_id) REFERENCES enterprise.users(tenant_id, id),
 CHECK ((length(partner_id) > 0) AND (length(partner_id) <= 128)),
 CHECK (length(worker_id) > 0),
 CHECK (version >= 1),
 CHECK (state IN ('running','stopped','reload_failed','start_failed')),
 CHECK ((updated_at_ms >= 0) AND (expires_at_ms >= updated_at_ms)),
 CHECK (ttl_ms >= 0)
);
CREATE INDEX partner_runtime_status_worker ON enterprise.partner_runtime_status USING btree (tenant_id, worker_id, expires_at_ms, partner_id);
CREATE INDEX partner_runtime_status_owner_updated ON enterprise.partner_runtime_status USING btree (tenant_id, owner_id, updated_at_ms DESC, partner_id);
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['partner_runtime_status'] LOOP
  EXECUTE format('ALTER TABLE enterprise.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE enterprise.%I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY tenant_scope ON enterprise.%I USING (tenant_id = nullif(current_setting(''app.tenant_id'',true),'''')::uuid) WITH CHECK (tenant_id = nullif(current_setting(''app.tenant_id'',true),'''')::uuid)',t);
  EXECUTE format('CREATE POLICY owner_scope ON enterprise.%I AS RESTRICTIVE USING (owner_id = nullif(current_setting(''app.user_id'',true),'''')) WITH CHECK (owner_id = nullif(current_setting(''app.user_id'',true),''''))',t);
  EXECUTE format('GRANT SELECT,INSERT,UPDATE,DELETE ON enterprise.%I TO dt_enterprise_app',t);
 END LOOP;
END $$;
