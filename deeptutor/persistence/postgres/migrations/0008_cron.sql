-- Cron schedule/meta/execution 状态：按可信 tenant/owner 隔离，领取和完成均带版本栅栏。
CREATE TABLE enterprise.cron_meta (
 tenant_id uuid NOT NULL,
 owner_id text NOT NULL,
 revision bigint NOT NULL DEFAULT 0,
 updated_at_ms bigint NOT NULL,
 PRIMARY KEY (tenant_id, owner_id),
 FOREIGN KEY (tenant_id, owner_id) REFERENCES enterprise.users(tenant_id, id),
 CHECK (revision >= 0),
 CHECK (updated_at_ms >= 0)
);
CREATE TABLE enterprise.cron_jobs (
 tenant_id uuid NOT NULL,
 owner_id text NOT NULL,
 job_id text NOT NULL,
 owner_key text NOT NULL,
 name text NOT NULL,
 message text NOT NULL,
 schedule_kind text NOT NULL,
 at_ms bigint,
 every_seconds integer,
 cron_expr text,
 tz text NOT NULL DEFAULT '',
 enabled boolean NOT NULL,
 delete_after_run boolean NOT NULL,
 created_at_ms bigint NOT NULL,
 next_run_at_ms bigint,
 last_run_at_ms bigint,
 last_status text,
 last_error text,
 payload jsonb NOT NULL,
 revision bigint NOT NULL DEFAULT 1,
 updated_at_ms bigint NOT NULL,
 PRIMARY KEY (tenant_id, owner_id, job_id),
 FOREIGN KEY (tenant_id, owner_id) REFERENCES enterprise.users(tenant_id, id),
 CHECK ((length(job_id) > 0) AND (length(job_id) <= 128)),
 CHECK ((length(owner_key) > 0) AND (length(owner_key) <= 512)),
 CHECK (schedule_kind IN ('at','every','cron')),
 CHECK (
  ((schedule_kind = 'at') AND (at_ms IS NOT NULL) AND (every_seconds IS NULL) AND (cron_expr IS NULL))
  OR ((schedule_kind = 'every') AND (at_ms IS NULL) AND (every_seconds IS NOT NULL) AND (every_seconds > 0) AND (cron_expr IS NULL))
  OR ((schedule_kind = 'cron') AND (at_ms IS NULL) AND (every_seconds IS NULL) AND (cron_expr IS NOT NULL) AND (length(cron_expr) > 0))
 ),
 CHECK ((next_run_at_ms IS NULL) OR (next_run_at_ms >= 0)),
 CHECK ((last_run_at_ms IS NULL) OR (last_run_at_ms >= 0)),
 CHECK ((last_status IS NULL) OR (last_status IN ('ok','error','skipped','uncertain'))),
 CHECK ((created_at_ms >= 0) AND (updated_at_ms >= 0)),
 CHECK (revision >= 1)
);
CREATE TABLE enterprise.cron_executions (
 tenant_id uuid NOT NULL,
 owner_id text NOT NULL,
 execution_id uuid NOT NULL,
 job_id text NOT NULL,
 owner_key text NOT NULL,
 scheduled_run_at_ms bigint NOT NULL,
 job_revision bigint NOT NULL,
 worker_id text NOT NULL,
 status text NOT NULL,
 claimed_at_ms bigint NOT NULL,
 completed_at_ms bigint,
 duration_ms bigint NOT NULL DEFAULT 0,
 error text,
 payload jsonb NOT NULL,
 PRIMARY KEY (tenant_id, owner_id, execution_id),
 UNIQUE (tenant_id, owner_id, job_id, scheduled_run_at_ms, job_revision),
 FOREIGN KEY (tenant_id, owner_id) REFERENCES enterprise.users(tenant_id, id),
 CHECK ((length(job_id) > 0) AND (length(job_id) <= 128)),
 CHECK ((length(owner_key) > 0) AND (length(owner_key) <= 512)),
 CHECK (length(worker_id) > 0),
 CHECK (status IN ('claimed','ok','error','skipped','uncertain')),
 CHECK (scheduled_run_at_ms >= 0),
 CHECK (job_revision >= 1),
 CHECK (claimed_at_ms >= 0),
 CHECK ((completed_at_ms IS NULL) OR (completed_at_ms >= claimed_at_ms)),
 CHECK (duration_ms >= 0),
 CHECK (((status = 'claimed') AND (completed_at_ms IS NULL)) OR ((status <> 'claimed') AND (completed_at_ms IS NOT NULL)))
);
CREATE INDEX cron_jobs_due ON enterprise.cron_jobs USING btree (tenant_id, owner_id, next_run_at_ms, job_id) WHERE enabled AND next_run_at_ms IS NOT NULL;
CREATE INDEX cron_jobs_owner_key ON enterprise.cron_jobs USING btree (tenant_id, owner_id, owner_key, job_id);
CREATE INDEX cron_executions_job ON enterprise.cron_executions USING btree (tenant_id, owner_id, job_id, scheduled_run_at_ms DESC, execution_id);
CREATE INDEX cron_executions_status ON enterprise.cron_executions USING btree (tenant_id, owner_id, status, claimed_at_ms, execution_id);
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['cron_meta','cron_jobs','cron_executions'] LOOP
  EXECUTE format('ALTER TABLE enterprise.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE enterprise.%I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY tenant_scope ON enterprise.%I USING (tenant_id = nullif(current_setting(''app.tenant_id'',true),'''')::uuid) WITH CHECK (tenant_id = nullif(current_setting(''app.tenant_id'',true),'''')::uuid)',t);
  EXECUTE format('CREATE POLICY owner_scope ON enterprise.%I AS RESTRICTIVE USING (owner_id = nullif(current_setting(''app.user_id'',true),'''')) WITH CHECK (owner_id = nullif(current_setting(''app.user_id'',true),''''))',t);
  EXECUTE format('GRANT SELECT,INSERT,UPDATE,DELETE ON enterprise.%I TO dt_enterprise_app',t);
 END LOOP;
END $$;
