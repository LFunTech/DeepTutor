-- 学校生命周期由已验签 Webhook 投影；旧 online resolve 证明不再决定准入。
-- 保留 0005–0007 的 inbox/候选事实，新增不可变投影，不改写历史事件。
-- 已有 external_tid 重复时迁移失败关闭，须受控清理，不得由 Webhook 猜测合并。
CREATE UNIQUE INDEX enterprise_external_tid_unique
  ON enterprise.tenants(external_tid) WHERE external_tid IS NOT NULL;
CREATE TABLE eduplus2.webhook_school_state (
  tenant_id uuid NOT NULL REFERENCES enterprise.tenants(id),
  external_tenant_id bigint NOT NULL CHECK (external_tenant_id > 0),
  external_app_id bigint NOT NULL CHECK (external_app_id > 0),
  school_id uuid NOT NULL REFERENCES enterprise.tenants(id),
  school_code text NOT NULL DEFAULT '' CHECK (length(school_code) <= 128),
  binding_version bigint NOT NULL CHECK (binding_version > 0),
  generation bigint NOT NULL DEFAULT 1 CHECK (generation > 0),
  eligibility text NOT NULL CHECK (eligibility IN ('unknown','allowed','denied')),
  external_subscription_id bigint NOT NULL CHECK (external_subscription_id > 0),
  last_event_id text NOT NULL CHECK (length(last_event_id) BETWEEN 1 AND 128),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (tenant_id,external_tenant_id,external_app_id),
  UNIQUE (tenant_id,school_id,external_app_id)
);
CREATE INDEX eduplus2_webhook_school_state_school
  ON eduplus2.webhook_school_state(school_id,external_app_id);
ALTER TABLE eduplus2.webhook_school_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE eduplus2.webhook_school_state FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON eduplus2.webhook_school_state
  USING (tenant_id = nullif(current_setting('app.tenant_id',true),'')::uuid)
  WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id',true),'')::uuid);

-- extension 迁移先于 OMS 迁移执行，不能在此引用 OMS binding。
-- 新应用门禁只认本表已投影状态；旧 proof 不作回填，因而历史 allowed 无法自动放行。
