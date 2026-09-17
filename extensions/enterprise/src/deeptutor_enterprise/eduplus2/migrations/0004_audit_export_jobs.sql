-- EduPlus2 audit export jobs.
-- Export payloads are redacted generated artifacts with bounded retention.

CREATE TABLE eduplus2.audit_export_jobs (
  tenant_id uuid NOT NULL REFERENCES enterprise.tenants(id),
  id uuid NOT NULL,
  requested_by text NOT NULL,
  format text NOT NULL CHECK (format IN ('jsonl','csv')),
  status text NOT NULL CHECK (status IN ('queued','running','completed','failed','expired')),
  filter_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
  row_count integer NOT NULL DEFAULT 0 CHECK (row_count >= 0),
  file_ref text NOT NULL DEFAULT '',
  export_content text NOT NULL DEFAULT '',
  error text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  expires_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, id),
  CHECK (length(requested_by) > 0),
  CHECK (jsonb_typeof(filter_snapshot) = 'object')
);
CREATE INDEX eduplus2_audit_export_jobs_status
  ON eduplus2.audit_export_jobs(tenant_id, status, created_at DESC);
CREATE INDEX eduplus2_audit_export_jobs_requester
  ON eduplus2.audit_export_jobs(tenant_id, requested_by, created_at DESC);

ALTER TABLE eduplus2.audit_export_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE eduplus2.audit_export_jobs FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON eduplus2.audit_export_jobs
  USING (tenant_id = nullif(current_setting('app.tenant_id', true),'')::uuid)
  WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true),'')::uuid);

GRANT SELECT,INSERT,UPDATE,DELETE ON eduplus2.audit_export_jobs TO dt_enterprise_app;
