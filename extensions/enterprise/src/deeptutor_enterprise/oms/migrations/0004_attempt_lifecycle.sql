-- 单次真实 provider attempt 的发出意图、稳定分摊顺序与追加证据。
-- 旧版本没有这些列时保留 NULL 待核对，不伪造历史 dispatch/usage。
ALTER TABLE oms.usage_attempts ADD COLUMN pool_id text;
ALTER TABLE oms.usage_attempts ADD COLUMN request_hash text;
ALTER TABLE oms.usage_attempts ADD CONSTRAINT usage_attempts_request_hash_valid
  CHECK (request_hash IS NULL OR length(request_hash) = 64);
ALTER TABLE oms.usage_attempts DROP CONSTRAINT usage_attempts_status_check;
ALTER TABLE oms.usage_attempts ADD CONSTRAINT usage_attempts_status_check
  CHECK (status IN ('reserved','dispatched','remote_unknown','reconcile_required','settled','released'));

ALTER TABLE oms.attempt_allocations ADD COLUMN allocation_order integer;
ALTER TABLE oms.attempt_allocations ADD CONSTRAINT attempt_allocations_order_positive
  CHECK (allocation_order IS NULL OR allocation_order > 0);
CREATE UNIQUE INDEX attempt_allocations_order
  ON oms.attempt_allocations(tenant_id,attempt_id,allocation_order)
  WHERE allocation_order IS NOT NULL;

CREATE TABLE oms.attempt_evidence_events (
  tenant_id uuid NOT NULL,
  attempt_id uuid NOT NULL,
  id uuid NOT NULL,
  event_kind text NOT NULL,
  reference text NOT NULL,
  observed_units numeric(30,6),
  provider_request_id text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (tenant_id,attempt_id,id),
  FOREIGN KEY (tenant_id,attempt_id) REFERENCES oms.usage_attempts(tenant_id,attempt_id),
  CHECK (event_kind IN ('dispatch_intent','remote_unknown','provider_usage',
                       'verified_reconciliation','confirmed_not_sent','overage')),
  CHECK (length(reference) > 0),
  CHECK (observed_units IS NULL OR observed_units >= 0)
);
CREATE INDEX attempt_evidence_by_attempt
  ON oms.attempt_evidence_events(tenant_id,attempt_id,created_at,id);

ALTER TABLE oms.attempt_evidence_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE oms.attempt_evidence_events FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON oms.attempt_evidence_events
  USING (tenant_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid);
