-- EduPlus2 revocation events and active revocation state.
-- Payload summaries are redacted operational metadata; raw tokens/secrets are not persisted.

CREATE TABLE eduplus2.revocation_events (
  tenant_id uuid NOT NULL REFERENCES enterprise.tenants(id),
  event_id text NOT NULL,
  event_type text NOT NULL,
  target_kind text NOT NULL CHECK (target_kind IN ('user','client','app','tenant','permission','subscription')),
  external_tenant_id text NOT NULL DEFAULT '',
  external_user_id text NOT NULL DEFAULT '',
  client_id text NOT NULL DEFAULT '',
  external_app_id text NOT NULL DEFAULT '',
  reason text NOT NULL DEFAULT '',
  event_version text NOT NULL DEFAULT '',
  payload_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  processing_status text NOT NULL CHECK (processing_status IN ('applied','duplicate','ignored','failed')),
  occurred_at timestamptz,
  processed_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, event_id),
  CHECK (length(event_id) > 0),
  CHECK (length(event_type) > 0),
  CHECK (jsonb_typeof(payload_summary) = 'object')
);
CREATE INDEX eduplus2_revocation_events_target
  ON eduplus2.revocation_events(tenant_id, target_kind, external_tenant_id, external_user_id, client_id, processed_at DESC);

CREATE TABLE eduplus2.revocation_state (
  tenant_id uuid NOT NULL REFERENCES enterprise.tenants(id),
  target_kind text NOT NULL CHECK (target_kind IN ('user','client','app','tenant','permission','subscription')),
  external_tenant_id text NOT NULL DEFAULT '',
  external_user_id text NOT NULL DEFAULT '',
  client_id text NOT NULL DEFAULT '',
  external_app_id text NOT NULL DEFAULT '',
  event_id text NOT NULL,
  reason text NOT NULL DEFAULT '',
  event_version text NOT NULL DEFAULT '',
  active boolean NOT NULL DEFAULT true,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, target_kind, external_tenant_id, external_user_id, client_id, external_app_id),
  FOREIGN KEY (tenant_id, event_id) REFERENCES eduplus2.revocation_events(tenant_id, event_id),
  CHECK (
    target_kind <> 'tenant' OR length(external_tenant_id) > 0
  ),
  CHECK (
    target_kind <> 'user' OR (length(external_tenant_id) > 0 AND length(external_user_id) > 0)
  ),
  CHECK (
    target_kind <> 'client' OR length(client_id) > 0
  ),
  CHECK (
    target_kind <> 'app' OR length(external_app_id) > 0
  ),
  CHECK (
    target_kind <> 'permission' OR (
      length(external_tenant_id) > 0
      AND length(external_user_id) > 0
      AND length(client_id) > 0
    )
  )
);
CREATE INDEX eduplus2_revocation_state_active
  ON eduplus2.revocation_state(tenant_id, active, target_kind, updated_at DESC);

DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['revocation_events','revocation_state'] LOOP
    EXECUTE format('ALTER TABLE eduplus2.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY tenant_scope ON eduplus2.%I USING (tenant_id = nullif(current_setting(''app.tenant_id'', true),'''')::uuid) WITH CHECK (tenant_id = nullif(current_setting(''app.tenant_id'', true),'''')::uuid)', t);
  END LOOP;
END $$;
