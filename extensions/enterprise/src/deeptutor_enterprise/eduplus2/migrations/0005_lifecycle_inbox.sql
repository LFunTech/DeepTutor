-- 已验签的订阅通知安全入队；owner tenant_id 是部署收件箱作用域，非目标学校。
-- 真实学校尚未绑定时也可可靠接收，但绝不能因此开放学校资格。
CREATE TABLE eduplus2.lifecycle_inbox (
  tenant_id uuid NOT NULL REFERENCES enterprise.tenants(id),
  event_id text NOT NULL,
  semantic_digest text NOT NULL,
  event_type text NOT NULL,
  external_tenant_id bigint NOT NULL,
  external_app_id bigint NOT NULL,
  external_subscription_id bigint NOT NULL,
  subscription_status text NOT NULL,
  client_id text NOT NULL DEFAULT '',
  actor_subject text NOT NULL DEFAULT '',
  actor_type text NOT NULL DEFAULT '',
  delivery_timestamp bigint NOT NULL,
  processing_status text NOT NULL DEFAULT 'pending_binding'
    CHECK (processing_status IN ('pending_binding','pending_reconcile','reconciling',
                                'verified','denied','retry','rejected')),
  retry_count integer NOT NULL DEFAULT 0,
  last_error_code text NOT NULL DEFAULT '',
  received_at timestamptz NOT NULL DEFAULT now(),
  processed_at timestamptz,
  PRIMARY KEY (tenant_id,event_id),
  CHECK (length(event_id) BETWEEN 1 AND 128),
  CHECK (length(semantic_digest) = 64),
  CHECK (external_tenant_id > 0 AND external_app_id > 0 AND external_subscription_id > 0),
  CHECK (length(subscription_status) BETWEEN 1 AND 64),
  CHECK (length(client_id) <= 255),
  CHECK (length(actor_subject) <= 255),
  CHECK (retry_count >= 0)
);
CREATE INDEX eduplus2_lifecycle_inbox_target_pending
  ON eduplus2.lifecycle_inbox(tenant_id,external_tenant_id,external_app_id,received_at)
  WHERE processing_status IN ('pending_binding','pending_reconcile','retry');

ALTER TABLE eduplus2.lifecycle_inbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE eduplus2.lifecycle_inbox FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON eduplus2.lifecycle_inbox
  USING (tenant_id = nullif(current_setting('app.tenant_id', true),'')::uuid)
  WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true),'')::uuid);

-- 当前在线证明与本地代次；Webhook payload 不能直接设置 allowed。
CREATE TABLE eduplus2.lifecycle_targets (
  tenant_id uuid NOT NULL REFERENCES enterprise.tenants(id),
  external_tenant_id bigint NOT NULL,
  external_app_id bigint NOT NULL,
  generation bigint NOT NULL DEFAULT 1,
  eligibility text NOT NULL DEFAULT 'unknown'
    CHECK (eligibility IN ('unknown','allowed','denied')),
  verified_client_id text NOT NULL DEFAULT '',
  resolve_etag text NOT NULL DEFAULT '',
  proof_checked_at timestamptz,
  proof_expires_at timestamptz,
  retry_count integer NOT NULL DEFAULT 0,
  last_error_code text NOT NULL DEFAULT '',
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id,external_tenant_id,external_app_id),
  CHECK (external_tenant_id > 0 AND external_app_id > 0),
  CHECK (generation > 0 AND retry_count >= 0),
  CHECK (length(verified_client_id) <= 255 AND length(resolve_etag) <= 255),
  CHECK (eligibility <> 'allowed' OR
    (proof_checked_at IS NOT NULL AND proof_expires_at IS NOT NULL
     AND proof_expires_at > proof_checked_at AND length(verified_client_id) > 0))
);
CREATE INDEX eduplus2_lifecycle_targets_retry
  ON eduplus2.lifecycle_targets(tenant_id,updated_at)
  WHERE eligibility <> 'allowed' OR proof_expires_at IS NULL;
CREATE INDEX eduplus2_lifecycle_targets_expiry
  ON eduplus2.lifecycle_targets(tenant_id,external_app_id,proof_expires_at)
  WHERE eligibility = 'allowed';

ALTER TABLE eduplus2.lifecycle_targets ENABLE ROW LEVEL SECURITY;
ALTER TABLE eduplus2.lifecycle_targets FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON eduplus2.lifecycle_targets
  USING (tenant_id = nullif(current_setting('app.tenant_id', true),'')::uuid)
  WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true),'')::uuid);

-- 仅交接待核验身份线索，不创建 TMS principal/assignment，也不证明当前订阅。
CREATE TABLE eduplus2.lifecycle_actor_candidates (
  tenant_id uuid NOT NULL REFERENCES enterprise.tenants(id),
  event_id text NOT NULL,
  school_id uuid NOT NULL REFERENCES enterprise.tenants(id),
  external_tenant_id bigint NOT NULL,
  external_app_id bigint NOT NULL,
  external_subscription_id bigint NOT NULL,
  binding_version bigint NOT NULL,
  actor_issuer text NOT NULL,
  actor_subject text NOT NULL,
  status text NOT NULL DEFAULT 'pending_verification'
    CHECK (status = 'pending_verification'),
  received_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id,event_id),
  FOREIGN KEY (tenant_id,event_id)
    REFERENCES eduplus2.lifecycle_inbox(tenant_id,event_id),
  CHECK (external_tenant_id > 0 AND external_app_id > 0
         AND external_subscription_id > 0 AND binding_version > 0),
  CHECK (length(actor_issuer) BETWEEN 1 AND 255
         AND length(actor_subject) BETWEEN 1 AND 255)
);
CREATE INDEX eduplus2_lifecycle_actor_candidates_school
  ON eduplus2.lifecycle_actor_candidates(school_id,received_at);
ALTER TABLE eduplus2.lifecycle_actor_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE eduplus2.lifecycle_actor_candidates FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON eduplus2.lifecycle_actor_candidates
  USING (tenant_id = nullif(current_setting('app.tenant_id', true),'')::uuid)
  WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true),'')::uuid);
